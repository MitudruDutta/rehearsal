"""Read-only, path-confined access to an application's source checkout."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "dist", "build", ".next", "coverage", "tmp", "log", ".cache"}
NOTABLE = re.compile(
    r"(?i)(^readme|docker-?compose.*\.ya?ml$|^dockerfile|\.env\.example$|\.env\.sample$|^env\.example|swagger.*\.(json|ya?ml)$|openapi.*\.(json|ya?ml)$|schema\.graphql$|\.graphql$|^procfile$|^makefile$|app\.ini|settings\.py$|config\.php$|routes\.rb$|^package\.json$|^gemfile$|^go\.mod$|^pyproject\.toml$|^composer\.json$|policy|policies|contributing)"
)
MAX_READ = 24_000


class RepoError(Exception):
    pass


class Repo:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise RepoError(f"source checkout {root} does not exist")

    def _resolve(self, rel: str) -> Path:
        try:
            path = (self.root / rel.lstrip("/")).resolve()
        except (OSError, RuntimeError) as exc:
            raise RepoError(f"cannot resolve {rel}") from exc
        if path != self.root and self.root not in path.parents:
            raise RepoError("path escapes the source tree")
        return path

    def overview(self, max_entries: int = 400) -> str:
        """Top of the tree plus notable files anywhere (compose, Dockerfiles, API specs, docs)."""
        lines = []
        for entry in sorted(self.root.iterdir()):
            if entry.name in SKIP_DIRS:
                continue
            try:
                path = self._resolve(str(entry.relative_to(self.root)))
                kind = "/" if path.is_dir() else f" ({path.stat().st_size}b)"
            except (RepoError, OSError):
                continue
            lines.append(f"{entry.name}{kind}")
        notable = []
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            rel_dir = Path(dirpath).relative_to(self.root)
            if len(rel_dir.parts) > 6:
                continue
            for f in filenames:
                if NOTABLE.search(f):
                    p = rel_dir / f
                    try:
                        path = self._resolve(str(p))
                        notable.append(f"{p} ({path.stat().st_size}b)")
                    except (RepoError, OSError):
                        continue
            if len(notable) > max_entries:
                break
        return "Top level:\n" + "\n".join(lines) + "\n\nNotable files:\n" + "\n".join(sorted(notable)[:max_entries])

    def list_dir(self, rel: str = ".") -> str:
        path = self._resolve(rel)
        if not path.is_dir():
            raise RepoError(f"{rel} is not a directory")
        out = []
        for entry in sorted(path.iterdir())[:300]:
            if entry.name in SKIP_DIRS:
                continue
            try:
                candidate = self._resolve(str(entry.relative_to(self.root)))
                kind = "/" if candidate.is_dir() else f" ({candidate.stat().st_size}b)"
            except (RepoError, OSError):
                continue
            out.append(entry.name + kind)
        return "\n".join(out) or "(empty)"

    def read_text(self, rel: str) -> str:
        """Read unformatted, untruncated text from a file inside the source tree."""
        path = self._resolve(rel)
        if not path.is_file():
            raise RepoError(f"{rel} is not a file")
        return path.read_text(errors="replace")

    def read_file(self, rel: str, start: int = 1, end: int | None = None) -> str:
        lines = self.read_text(rel).splitlines()
        start = max(1, start)
        end = min(len(lines), end or len(lines))
        chunk = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
        if len(chunk) > MAX_READ:
            chunk = chunk[:MAX_READ] + f"\n... truncated; file has {len(lines)} lines, read a narrower range"
        return chunk or "(empty file)"

    def grep(self, pattern: str, glob: str = "*", max_hits: int = 80) -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise RepoError(f"bad regex: {exc}") from exc
        hits = []
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                if not fnmatch.fnmatch(f, glob):
                    continue
                rel = (Path(dirpath) / f).relative_to(self.root)
                try:
                    p = self._resolve(str(rel))
                    if not p.is_file() or p.stat().st_size > 2_000_000:
                        continue
                    for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                        if rx.search(line):
                            hits.append(f"{rel}:{n}: {line.strip()[:200]}")
                            if len(hits) >= max_hits:
                                return "\n".join(hits) + "\n... more hits truncated"
                except (RepoError, OSError):
                    continue
        return "\n".join(hits) or "(no matches)"

    def find(self, name_glob: str, max_hits: int = 100) -> str:
        hits = []
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                if fnmatch.fnmatch(f, name_glob):
                    rel = str((Path(dirpath) / f).relative_to(self.root))
                    try:
                        if not self._resolve(rel).is_file():
                            continue
                    except (RepoError, OSError):
                        continue
                    hits.append(rel)
                    if len(hits) >= max_hits:
                        return "\n".join(hits) + "\n..."
        return "\n".join(hits) or "(no matches)"
