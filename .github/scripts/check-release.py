"""Validate release version and required resources before publishing archives."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import tarfile
import tomllib
import zipfile


def check_release(root: Path) -> None:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    tag = os.environ.get("RELEASE_TAG")
    if tag and tag != f"v{project['version']}":
        raise ValueError(f"Release tag {tag!r} must match pyproject.toml: v{project['version']}")

    required = {
        "rehearsal/py.typed",
        "rehearsal/db/alembic.ini",
        "rehearsal/db/migrations/env.py",
        "rehearsal/db/migrations/script.py.mako",
        "rehearsal/db/migrations/versions/0010_model_spend.py",
        "rehearsal/assets/catalog.yaml",
        "rehearsal/assets/compose.yaml",
        "rehearsal/assets/skill/SKILL.md",
        "rehearsal/providers/Dockerfile",
        "rehearsal/api/static/index.html",
        "rehearsal/api/static/app/billing/index.html",
        "rehearsal/api/static/app/admin/index.html",
        "rehearsal/api/static/fonts/Bricolage-Grotesque-OFL.txt",
        "rehearsal/api/static/fonts/Instrument-Sans-OFL.txt",
    }
    archives = list((root / "dist").glob("*.whl")) + list((root / "dist").glob("*.tar.gz"))
    if len(archives) != 2 or sum(p.suffix == ".whl" for p in archives) != 1:
        raise ValueError("Expected exactly one wheel and one source archive in dist/")
    for archive in archives:
        if archive.suffix == ".whl":
            with zipfile.ZipFile(archive) as wheel:
                names = set(wheel.namelist())
        else:
            with tarfile.open(archive) as source:
                names = {name.split("/", 1)[1] for name in source.getnames() if "/" in name}
        missing = required - names
        if missing:
            raise ValueError(f"{archive.name}: missing required resources: {sorted(missing)}")
        for name in names:
            if {".env", ".git", "node_modules", "var"}.intersection(PurePosixPath(name).parts):
                raise ValueError(f"{archive.name}: unexpected private/runtime path: {name}")
    print(f"Release {project['name']} {project['version']}: version and archive resources verified")


if __name__ == "__main__":
    check_release(Path(__file__).resolve().parents[2])
