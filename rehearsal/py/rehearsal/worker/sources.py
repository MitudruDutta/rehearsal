"""Materializes an application's source on the runner."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from ..config import settings


MAX_UPLOAD_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_UPLOAD_MEMBER_BYTES = 256 * 1024 * 1024
MAX_UPLOAD_MEMBERS = 10_000
_COMPLETE = ".rehearsal-source-complete"


class SourceError(Exception):
    pass


def materialize(app_id: str, source: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Returns (checkout path, provenance)."""
    kind = source.get("kind")
    root = settings().data_dir / "sources" / app_id
    if kind == "git":
        url, commit = source["url"], source.get("commit") or source.get("ref")
        if not url.startswith(("https://", "git@")):
            raise SourceError("git sources must use https or ssh")
        if commit and commit.startswith("-"):
            raise SourceError("git commit/ref must not begin with an option")
        identity = hashlib.sha256(f"{url}\0{commit or 'HEAD'}".encode()).hexdigest()
        dest = _destination(root, identity)
        if not _complete(dest):
            with tempfile.TemporaryDirectory(prefix=f".{dest.name}-", dir=root) as tmp:
                staging = Path(tmp)
                _git(["git", "init", "-q", str(staging)])
                _git(["git", "-C", str(staging), "remote", "add", "origin", url])
                _git(["git", "-C", str(staging), "fetch", "-q", "--depth", "1", "origin", commit or "HEAD"], timeout=1800)
                _git(["git", "-C", str(staging), "checkout", "-q", "FETCH_HEAD"])
                _git_head(staging, source.get("commit"))
                _publish(staging, dest)
        head = _git_head(dest, source.get("commit"))
        return dest, {"source_kind": "git", "url": url, "ref": source.get("ref"), "commit": head}
    if kind == "local_path":
        path = Path(source["path"]).resolve()
        if not any(path == r or r in path.parents for r in settings().source_roots):
            raise SourceError(f"{path} is outside REHEARSAL_SOURCE_ROOTS")
        if not path.is_dir():
            raise SourceError(f"{path} does not exist")
        return path, {"source_kind": "local_path", "path": str(path)}
    if kind == "upload":
        archive = Path(source["artifact_path"])
        digest = source["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise SourceError("upload sha256 must be a lowercase hexadecimal SHA-256 digest")
        dest = _destination(root, f"upload-{digest}")
        if not _complete(dest):
            try:
                with tempfile.TemporaryDirectory(prefix=f".{dest.name}-", dir=root) as tmp:
                    staging = Path(tmp)
                    expanded = 0
                    with tarfile.open(archive, mode="r|*", errorlevel=2) as tar:
                        for count, member in enumerate(tar, 1):
                            expanded += member.size
                            if (count > MAX_UPLOAD_MEMBERS or member.size < 0
                                    or member.size > MAX_UPLOAD_MEMBER_BYTES
                                    or expanded > MAX_UPLOAD_EXPANDED_BYTES):
                                raise SourceError("source archive exceeds expanded upload/member limit")
                            tar.extract(member, staging, filter="data")
                    _publish(staging, dest)
            except (tarfile.TarError, OSError) as exc:
                raise SourceError(f"source archive extraction failed: {exc}") from exc
        return dest, {"source_kind": "upload", "sha256": source["sha256"]}
    raise SourceError(f"unsupported source kind {kind}")


def _destination(root: Path, name: str) -> Path:
    base = (settings().data_dir / "sources").resolve()
    resolved = root.resolve()
    if resolved == base or not resolved.is_relative_to(base):
        raise SourceError("source destination is outside the sources directory")
    dest = root / name
    if dest.is_symlink() or not dest.resolve().is_relative_to(resolved):
        raise SourceError("source destination is outside its application directory or is a symlink")
    root.mkdir(parents=True, exist_ok=True)
    return dest


def _complete(dest: Path) -> bool:
    marker = dest / _COMPLETE
    return marker.is_file() and not marker.is_symlink()


def _publish(staging: Path, dest: Path) -> None:
    # Exclusive creation prevents archive content from impersonating the completion marker.
    (staging / _COMPLETE).touch(exist_ok=False)
    _destination(dest.parent, dest.name)
    if _complete(dest):
        return  # Another worker finished while this source was being prepared.
    if dest.exists():
        shutil.rmtree(dest)
    try:
        staging.rename(dest)
    except OSError:
        if not _complete(dest):
            raise


def _git_head(dest: Path, expected: str | None) -> str:
    head = _git(["git", "-C", str(dest), "rev-parse", "HEAD"]).strip()
    if expected and head != expected:
        raise SourceError(f"checked out {head}, expected pinned commit {expected}")
    return head


def _git(cmd: list[str], timeout: float = 300) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise SourceError(f"{' '.join(cmd[:3])} failed: {proc.stderr[-1000:]}")
    return proc.stdout
