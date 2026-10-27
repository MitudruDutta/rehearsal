"""Repository access stays inside synthetic source trees; no services needed."""

import os
from pathlib import Path

import pytest

from rehearsal.compiler.repo import MAX_READ, Repo, RepoError


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "README.md").write_text("inside marker\nsecond line\n")
    nested = root / "docs"
    nested.mkdir()
    (nested / "openapi.json").write_text('{"inside": "marker"}\n')
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "openapi.json").write_text("outside marker\n")
    (root / "internal.txt").symlink_to("README.md")
    (root / "internal-dir").symlink_to("docs", target_is_directory=True)
    (root / "external-openapi.json").symlink_to(outside / "openapi.json")
    (nested / "external-openapi.json").symlink_to(outside / "openapi.json")
    (root / "external-dir").symlink_to(outside, target_is_directory=True)
    return Repo(root)


@pytest.mark.parametrize("method", ["overview", "list_dir", "find", "grep"])
def test_scans_skip_external_links(checkout, monkeypatch, method):
    original_stat = Path.stat
    original_read = Path.read_text
    original_scandir = os.scandir

    def check_path(path):
        assert not path.is_relative_to(checkout.root.parent / "outside")
        assert "external" not in path.name

    def confined_stat(path, *args, **kwargs):
        # Path.resolve may stat its resolved target before checking confinement.
        assert "external" not in path.name
        return original_stat(path, *args, **kwargs)

    def confined_read(path, *args, **kwargs):
        check_path(path)
        return original_read(path, *args, **kwargs)

    def confined_scandir(path):
        check_path(Path(path))
        assert Path(path).name != "internal-dir"
        return original_scandir(path)

    args = {"find": ("*",), "grep": ("marker",)}.get(method, ())
    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "stat", confined_stat)
        guarded.setattr(Path, "read_text", confined_read)
        guarded.setattr(os, "scandir", confined_scandir)
        result = getattr(checkout, method)(*args)
    assert "external" not in result
    assert "outside" not in result
    assert "README.md" in result


@pytest.mark.parametrize("rel", [
    "external-openapi.json", "docs/external-openapi.json",
    "external-dir/openapi.json", "../outside/openapi.json",
])
@pytest.mark.parametrize("method", ["read_text", "read_file"])
def test_reads_reject_escaping_paths(checkout, rel, method):
    with pytest.raises(RepoError, match="escapes"):
        getattr(checkout, method)(rel)


def test_listing_rejects_external_directory_link(checkout):
    with pytest.raises(RepoError, match="escapes"):
        checkout.list_dir("external-dir")
    assert "external" not in checkout.list_dir("docs")
    assert "openapi.json" in checkout.list_dir("internal-dir")


def test_internal_file_links_and_normal_search(checkout):
    assert checkout.read_text("internal.txt") == "inside marker\nsecond line\n"
    assert checkout.read_file("internal.txt", start=2, end=2) == "2: second line"
    assert checkout.grep("inside", glob="*.txt") == "internal.txt:1: inside marker"
    assert checkout.find("*openapi*.json") == "docs/openapi.json"
    assert "docs/openapi.json" in checkout.overview()
    assert "internal-dir/" in checkout.list_dir()
    assert "internal.txt" in checkout.find("*.txt")
    assert "internal-dir/openapi.json" not in checkout.grep("marker")
    assert checkout.grep("absent") == "(no matches)"
    assert checkout.find("*.absent") == "(no matches)"


def test_raw_read_is_unformatted_and_untruncated(checkout, monkeypatch):
    text = "x" * (MAX_READ + 1) + "\n"
    (checkout.root / "large.txt").write_text(text)
    assert checkout.read_text("large.txt") == text
    assert "truncated" in checkout.read_file("large.txt")
    monkeypatch.setattr(checkout, "read_text", lambda rel: "delegated\n")
    assert checkout.read_file("README.md") == "1: delegated"


@pytest.mark.parametrize("method", ["read_text", "read_file"])
@pytest.mark.parametrize("rel", ["missing.txt", "docs"])
def test_reads_require_a_file(checkout, method, rel):
    with pytest.raises(RepoError, match="not a file"):
        getattr(checkout, method)(rel)


def test_broken_and_looping_links_do_not_break_scans(checkout):
    (checkout.root / "broken-openapi.json").symlink_to("missing.json")
    (checkout.root / "loop-openapi.json").symlink_to("loop-openapi.json")
    assert "broken" not in checkout.overview()
    assert "loop" not in checkout.list_dir()
    assert checkout.find("*openapi.json") == "docs/openapi.json"
    assert "inside marker" in checkout.grep("marker")
    with pytest.raises(RepoError):
        checkout.read_text("loop-openapi.json")
