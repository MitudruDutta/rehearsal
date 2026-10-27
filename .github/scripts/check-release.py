"""Release gates for rehearsal-kit.

    python check-release.py --version-only   # before building: version, tag, PyPI, changelog, agent plugin, npm package
    python check-release.py                  # after `python -m build`: the tag again, plus archive contents

The version gate is strict for a published GitHub Release (GITHUB_EVENT_NAME=release). On a manual dry run it
reports problems as warnings, so the rest of the pipeline can still be exercised.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tarfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

PYPI_JSON = "https://pypi.org/pypi/{name}/json"


def project(root: Path) -> dict:
    return tomllib.loads((root / "pyproject.toml").read_text())["project"]


def check_tag(version: str) -> None:
    tag = os.environ.get("RELEASE_TAG")
    if tag and tag != f"v{version}":
        raise ValueError(f"Release tag {tag!r} must match pyproject.toml: v{version}")


def published_versions(name: str) -> list[str]:
    """Every version PyPI knows for the project, yanked ones included (a yanked number can never be reused)."""
    try:
        with urllib.request.urlopen(PYPI_JSON.format(name=name), timeout=30) as response:
            return list(json.load(response)["releases"])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []  # first release
        raise


def version_problems(root: Path) -> list[str]:
    from packaging.version import InvalidVersion, Version

    meta = project(root)
    version = meta["version"]
    problems: list[str] = []
    try:
        new = Version(version)
    except InvalidVersion:
        return [f"pyproject.toml version {version!r} is not a valid PEP 440 version"]
    if str(new) != version:
        problems.append(f"write the version in normalized form: {new} (not {version})")
    tag = os.environ.get("RELEASE_TAG")
    if tag and tag != f"v{version}":
        problems.append(f"release tag {tag!r} does not match pyproject.toml version: expected v{version}")

    existing = published_versions(meta["name"])
    if version in existing:
        problems.append(f"{meta['name']} {version} is already on PyPI; raise the version in pyproject.toml")
    parsed = []
    for v in existing:
        try:
            parsed.append(Version(v))
        except InvalidVersion:
            continue
    if parsed and new <= max(parsed):
        problems.append(f"{version} is not higher than the newest version on PyPI ({max(parsed)})")

    changelog = root / "CHANGELOG.md"
    if not changelog.is_file() or not re.search(rf"^## {re.escape(version)}\b", changelog.read_text(), re.M):
        problems.append(f"CHANGELOG.md has no '## {version}' section describing this release")

    plugin = root / "agent-plugin" / "plugin.json"
    if plugin.is_file():
        plugin_version = json.loads(plugin.read_text()).get("version")
        if plugin_version != version:
            problems.append(f"agent-plugin/plugin.json version {plugin_version} must equal {version}; "
                            "set it and run scripts/build_agent_plugin.py")

    npm = root / "rehearsal" / "ts" / "package.json"
    if npm.is_file():
        npm_version = json.loads(npm.read_text()).get("version")
        if npm_version != version:
            problems.append(f"rehearsal/ts/package.json version {npm_version} must equal {version}; both packages are released together")
    return problems


def check_version(root: Path) -> None:
    problems = version_problems(root)
    meta = project(root)
    if not problems:
        print(f"Version gate passed: {meta['name']} {meta['version']} is new, tagged, in the changelog, and matches the agent plugin")
        return
    strict = os.environ.get("GITHUB_EVENT_NAME") == "release"
    for p in problems:
        print(f"::{'error' if strict else 'warning'}::{p}")
    if strict:
        sys.exit(1)
    print("Manual run: version problems reported as warnings; a release with them would be refused.")


def check_archives(root: Path) -> None:
    meta = project(root)
    check_tag(meta["version"])
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
    # every migration in the source tree must ship, or `rehearsal migrate` stops short on installed servers
    required |= {f"rehearsal/db/migrations/versions/{p.name}" for p in (root / "rehearsal/db/migrations/versions").glob("[0-9]*.py")}
    archives = list((root / "dist").glob("*.whl")) + list((root / "dist").glob("*.tar.gz"))
    if len(archives) != 2 or sum(p.suffix == ".whl" for p in archives) != 1:
        raise ValueError("Expected exactly one wheel and one source archive in dist/")
    for archive in archives:
        if not archive.name.startswith(f"{meta['name'].replace('-', '_')}-{meta['version']}"):
            raise ValueError(f"{archive.name} does not carry version {meta['version']}")
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
    print(f"Release {meta['name']} {meta['version']}: version and archive resources verified")


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[2]
    if "--version-only" in sys.argv:
        check_version(repo)
    else:
        check_archives(repo)
