"""Source materialization regressions; no application, Docker, or network."""

import hashlib
import io
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from rehearsal.worker import sources


URL = "https://example.test/source.git"
HEAD = "a" * 40


@pytest.fixture(autouse=True)
def source_settings(tmp_path, monkeypatch):
    config = SimpleNamespace(data_dir=tmp_path / "data", source_roots=(tmp_path / "allowed",))
    monkeypatch.setattr(sources, "settings", lambda: config)
    return config


@pytest.fixture
def git(monkeypatch):
    calls = []

    def run(cmd, timeout=300):
        calls.append(cmd)
        if cmd[1] == "init":
            (Path(cmd[-1]) / ".git").mkdir()
        if "checkout" in cmd:
            (Path(cmd[2]) / "source.txt").write_text("checked out")
        return HEAD + "\n" if "rev-parse" in cmd else ""

    monkeypatch.setattr(sources, "_git", run)
    return calls


def git_source(**extra):
    return {"kind": "git", "url": URL, "ref": "main", **extra}


def archive_source(tmp_path, entries):
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for entry in entries:
            if isinstance(entry, tuple):
                name, body = entry
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
            else:
                tar.addfile(entry)
    return {"kind": "upload", "artifact_path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


def assert_no_partial(config):
    root = config.data_dir / "sources" / "app"
    assert not root.exists() or list(root.iterdir()) == []


@pytest.mark.parametrize("ref", ["../victim", "../../victim", "/absolute", "feature/branch", ".."])
def test_git_ref_cannot_be_a_deletion_path(ref, source_settings, git, tmp_path):
    if ref.startswith("/"):
        ref = str(tmp_path / "absolute")
    victim = source_settings.data_dir / "sources" / "victim"
    victim.mkdir(parents=True)
    (victim / "keep").write_text("untouched")
    source = git_source(ref=ref)
    dest, provenance = sources.materialize("app", source)
    assert dest.parent == source_settings.data_dir / "sources" / "app"
    assert dest.name == hashlib.sha256(f"{URL}\0{ref}".encode()).hexdigest()
    assert (victim / "keep").read_text() == "untouched"
    assert (dest / "source.txt").is_file()
    assert provenance == {"source_kind": "git", "url": URL, "ref": ref, "commit": HEAD}


def test_git_cache_identity_includes_url_and_full_ref(git):
    long_ref = "x" * 40
    paths = [sources.materialize("app", git_source(**extra))[0] for extra in (
        {"ref": long_ref + "a"}, {"ref": long_ref + "b"},
        {"ref": long_ref + "a", "url": "https://example.test/other.git"},
    )]
    assert len(set(paths)) == 3


@pytest.mark.parametrize("field", ["commit", "ref"])
def test_git_absolute_target_stays_contained(field, tmp_path, git):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep").touch()
    # A mocked HEAD equal to the requested pin allows testing commit containment too.
    original = sources._git
    sources._git = lambda cmd, **kw: str(victim) if "rev-parse" in cmd else original(cmd, **kw)
    dest, _ = sources.materialize("app", git_source(**{field: str(victim)}))
    assert dest != victim
    assert (victim / "keep").exists()


@pytest.mark.parametrize("url", ["file:///tmp/repo", "/tmp/repo", "http://example.test/repo", "ssh://example.test/repo"])
def test_git_url_restrictions_remain(url, git, source_settings):
    with pytest.raises(sources.SourceError, match="https or ssh"):
        sources.materialize("app", git_source(url=url))
    assert not git
    assert_no_partial(source_settings)


@pytest.mark.parametrize("url", [URL, "git@example.test:source.git"])
def test_git_completed_checkout_is_reused(url, git):
    source = git_source(url=url)
    dest, _ = sources.materialize("app", source)
    count = len(git)
    assert sources.materialize("app", source)[0] == dest
    assert len(git) == count + 1
    assert "rev-parse" in git[-1]


@pytest.mark.parametrize("step", ["init", "fetch", "checkout", "rev-parse"])
def test_failed_git_checkout_is_cleaned_and_retryable(step, monkeypatch, git, source_settings):
    run = sources._git

    def fail(cmd, **kwargs):
        result = run(cmd, **kwargs)
        if step in cmd:
            raise sources.SourceError("interrupted checkout")
        return result

    monkeypatch.setattr(sources, "_git", fail)
    with pytest.raises(sources.SourceError, match="interrupted"):
        sources.materialize("app", git_source())
    assert_no_partial(source_settings)
    monkeypatch.setattr(sources, "_git", run)
    dest, _ = sources.materialize("app", git_source())
    assert (dest / "source.txt").is_file()


def test_git_timeout_cleans_staging(monkeypatch, source_settings):
    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(sources, "_git", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        sources.materialize("app", git_source())
    assert_no_partial(source_settings)


def test_pin_mismatch_is_never_published(git, source_settings):
    with pytest.raises(sources.SourceError, match="expected pinned commit"):
        sources.materialize("app", git_source(commit="b" * 40))
    assert_no_partial(source_settings)
    dest, provenance = sources.materialize("app", git_source(commit=HEAD))
    assert (dest / "source.txt").exists()
    assert provenance["commit"] == HEAD


def test_incomplete_git_cache_is_rebuilt(git, source_settings):
    identity = hashlib.sha256(f"{URL}\0main".encode()).hexdigest()
    dest = source_settings.data_dir / "sources" / "app" / identity
    (dest / ".git").mkdir(parents=True)
    (dest / "partial").touch()
    assert sources.materialize("app", git_source())[0] == dest
    assert (dest / "source.txt").exists()
    assert not (dest / "partial").exists()


@pytest.mark.parametrize("kind", ["git", "upload"])
def test_destination_symlink_cannot_redirect_deletion(kind, tmp_path, source_settings, git):
    source = git_source() if kind == "git" else archive_source(tmp_path, [("ok", b"ok")])
    name = hashlib.sha256(f"{URL}\0main".encode()).hexdigest() if kind == "git" else f"upload-{source['sha256']}"
    root = source_settings.data_dir / "sources" / "app"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").touch()
    (root / name).symlink_to(outside, target_is_directory=True)
    with pytest.raises(sources.SourceError, match="outside|symlink"):
        sources.materialize("app", source)
    assert (outside / "keep").exists()
    assert not git


@pytest.mark.parametrize("app_id", ["..", "../escape", "/absolute"])
def test_application_root_cannot_escape(app_id, git, tmp_path):
    if app_id.startswith("/"):
        app_id = str(tmp_path / "absolute")
    with pytest.raises(sources.SourceError, match="outside"):
        sources.materialize(app_id, git_source())
    assert not git


def test_application_root_symlink_cannot_escape(tmp_path, source_settings, git):
    root = source_settings.data_dir / "sources"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "app").symlink_to(outside, target_is_directory=True)
    with pytest.raises(sources.SourceError, match="outside"):
        sources.materialize("app", git_source())
    assert list(outside.iterdir()) == []
    assert not git


def test_upload_success_is_atomic_and_cached(tmp_path, monkeypatch, source_settings):
    source = archive_source(tmp_path, [("nested/file", b"contents")])
    final = source_settings.data_dir / "sources" / "app" / f"upload-{source['sha256']}"
    extract = tarfile.TarFile.extract

    def observe(tar, member, path, **kwargs):
        assert not final.exists()
        assert Path(path).parent == final.parent
        return extract(tar, member, path, **kwargs)

    monkeypatch.setattr(tarfile.TarFile, "extract", observe)
    dest, provenance = sources.materialize("app", source)
    assert dest == final
    assert (dest / "nested/file").read_bytes() == b"contents"
    assert provenance == {"source_kind": "upload", "sha256": source["sha256"]}
    Path(source["artifact_path"]).unlink()
    assert sources.materialize("app", source)[0] == dest
    assert list(dest.parent.iterdir()) == [dest]


@pytest.mark.parametrize("malicious", ["../escape", "nested/../../escape"])
def test_archive_traversal_cleans_partial_extraction(malicious, tmp_path, source_settings):
    source = archive_source(tmp_path, [("valid", b"written first"), (malicious, b"bad")])
    with pytest.raises(sources.SourceError):
        sources.materialize("app", source)
    assert_no_partial(source_settings)
    assert not (source_settings.data_dir / "sources" / "escape").exists()


def test_archive_external_symlink_is_rejected(tmp_path, source_settings):
    member = tarfile.TarInfo("link")
    member.type = tarfile.SYMTYPE
    member.linkname = str(tmp_path / "outside")
    source = archive_source(tmp_path, [member])
    with pytest.raises(sources.SourceError):
        sources.materialize("app", source)
    assert_no_partial(source_settings)


@pytest.mark.parametrize("limit,entries", [
    ("MAX_UPLOAD_MEMBER_BYTES", [("large", b"12345")]),
    ("MAX_UPLOAD_EXPANDED_BYTES", [("a", b"123"), ("b", b"456")]),
    ("MAX_UPLOAD_MEMBERS", [("a", b""), ("b", b""), ("c", b"")]),
])
def test_expanded_upload_limits(limit, entries, tmp_path, monkeypatch, source_settings):
    monkeypatch.setattr(sources, limit, 2 if limit == "MAX_UPLOAD_MEMBERS" else 4)
    source = archive_source(tmp_path, entries)
    with pytest.raises(sources.SourceError, match="limit"):
        sources.materialize("app", source)
    assert_no_partial(source_settings)


def test_upload_limits_accept_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "MAX_UPLOAD_MEMBER_BYTES", 3)
    monkeypatch.setattr(sources, "MAX_UPLOAD_EXPANDED_BYTES", 6)
    monkeypatch.setattr(sources, "MAX_UPLOAD_MEMBERS", 2)
    source = archive_source(tmp_path, [("a", b"123"), ("b", b"456")])
    dest, _ = sources.materialize("app", source)
    assert (dest / "a").read_bytes() == b"123"
    assert (dest / "b").read_bytes() == b"456"


def test_upload_directory_members_count_toward_limit(tmp_path, monkeypatch, source_settings):
    monkeypatch.setattr(sources, "MAX_UPLOAD_MEMBERS", 1)
    directory = tarfile.TarInfo("dir")
    directory.type = tarfile.DIRTYPE
    source = archive_source(tmp_path, [directory, ("dir/file", b"")])
    with pytest.raises(sources.SourceError, match="limit"):
        sources.materialize("app", source)
    assert_no_partial(source_settings)


def test_failed_archive_extraction_is_retryable(tmp_path, monkeypatch, source_settings):
    source = archive_source(tmp_path, [("file", b"complete")])
    extract = tarfile.TarFile.extract

    def fail(tar, member, path, **kwargs):
        extract(tar, member, path, **kwargs)
        raise OSError("interrupted extraction")

    monkeypatch.setattr(tarfile.TarFile, "extract", fail)
    with pytest.raises(sources.SourceError, match="interrupted"):
        sources.materialize("app", source)
    assert_no_partial(source_settings)
    monkeypatch.setattr(tarfile.TarFile, "extract", extract)
    dest, _ = sources.materialize("app", source)
    assert (dest / "file").read_bytes() == b"complete"


def test_incomplete_upload_cache_is_rebuilt(tmp_path, source_settings):
    source = archive_source(tmp_path, [("file", b"complete")])
    dest = source_settings.data_dir / "sources" / "app" / f"upload-{source['sha256']}"
    dest.mkdir(parents=True)
    (dest / "partial").touch()
    assert sources.materialize("app", source)[0] == dest
    assert (dest / "file").read_bytes() == b"complete"
    assert not (dest / "partial").exists()


def test_upload_digest_cannot_be_a_path(tmp_path, source_settings):
    source = archive_source(tmp_path, [("file", b"ok")])
    source["sha256"] = "../../outside"
    with pytest.raises(sources.SourceError, match="sha256"):
        sources.materialize("app", source)
    assert_no_partial(source_settings)


def test_local_path_allowlist_remains(source_settings, tmp_path):
    allowed = source_settings.source_roots[0]
    allowed.mkdir()
    assert sources.materialize("app", {"kind": "local_path", "path": str(allowed)}) == (
        allowed, {"source_kind": "local_path", "path": str(allowed)},
    )
    with pytest.raises(sources.SourceError, match="outside"):
        sources.materialize("app", {"kind": "local_path", "path": str(tmp_path)})


def test_git_checkout_is_atomic(monkeypatch, git, source_settings):
    final = source_settings.data_dir / "sources" / "app" / hashlib.sha256(f"{URL}\0main".encode()).hexdigest()
    run = sources._git

    def observe(cmd, **kwargs):
        if "checkout" in cmd:
            assert not final.exists()
            assert Path(cmd[2]).parent == final.parent
        return run(cmd, **kwargs)

    monkeypatch.setattr(sources, "_git", observe)
    assert sources.materialize("app", git_source())[0] == final
    assert list(final.parent.iterdir()) == [final]


def test_upload_digest_uses_all_64_characters(tmp_path):
    source = archive_source(tmp_path, [("file", b"first")])
    source["sha256"] = "a" * 16 + "b" * 48
    first, _ = sources.materialize("app", source)
    source = archive_source(tmp_path, [("file", b"second")])
    source["sha256"] = "a" * 16 + "c" * 48
    second, _ = sources.materialize("app", source)
    assert first != second
    assert (first / "file").read_bytes() == b"first"
    assert (second / "file").read_bytes() == b"second"


@pytest.mark.parametrize("kind", ["git", "upload"])
def test_publish_failure_cleans_staging(kind, tmp_path, monkeypatch, git, source_settings):
    def fail(*args, **kwargs):
        raise OSError("publish failed")

    monkeypatch.setattr(Path, "rename", fail)
    source = git_source() if kind == "git" else archive_source(tmp_path, [("file", b"ok")])
    with pytest.raises((OSError, sources.SourceError), match="publish failed"):
        sources.materialize("app", source)
    assert_no_partial(source_settings)


def test_archive_cannot_supply_completion_marker(tmp_path, source_settings):
    source = archive_source(tmp_path, [(sources._COMPLETE, b"fake completion")])
    with pytest.raises(sources.SourceError):
        sources.materialize("app", source)
    assert_no_partial(source_settings)


def test_invalid_archive_is_cleaned(tmp_path, source_settings):
    source = archive_source(tmp_path, [])
    Path(source["artifact_path"]).write_bytes(b"not a tar archive")
    with pytest.raises(sources.SourceError):
        sources.materialize("app", source)
    assert_no_partial(source_settings)


def test_safe_archive_links_still_work(tmp_path):
    symlink = tarfile.TarInfo("symlink")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "file"
    hardlink = tarfile.TarInfo("hardlink")
    hardlink.type = tarfile.LNKTYPE
    hardlink.linkname = "file"
    source = archive_source(tmp_path, [("file", b"ok"), symlink, hardlink])
    dest, _ = sources.materialize("app", source)
    assert (dest / "symlink").read_bytes() == b"ok"
    assert (dest / "hardlink").stat().st_ino == (dest / "file").stat().st_ino


@pytest.mark.parametrize("field", ["commit", "ref"])
@pytest.mark.parametrize("value", ["--upload-pack=malicious", "-o", "--help"])
def test_git_target_cannot_inject_options(field, value, git, source_settings):
    with pytest.raises(sources.SourceError, match="option"):
        sources.materialize("app", git_source(**{field: value}))
    assert not git
    assert_no_partial(source_settings)
