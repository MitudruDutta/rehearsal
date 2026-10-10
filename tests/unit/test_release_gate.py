"""The publish workflow's version gate refuses every way a release can be wrong."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_release", ROOT / ".github" / "scripts" / "check-release.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def _repo(tmp_path: Path, version: str, changelog: str | None = None, plugin: str | None = None) -> Path:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "rehearsal-kit"\nversion = "{version}"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog if changelog is not None else f"# Changelog\n\n## {version}\n\n- change\n")
    (tmp_path / "agent-plugin").mkdir()
    (tmp_path / "agent-plugin" / "plugin.json").write_text(json.dumps({"version": plugin or version}))
    return tmp_path


@pytest.fixture
def pypi(monkeypatch):
    def published(versions):
        monkeypatch.setattr(gate, "published_versions", lambda name: list(versions))
    return published


def test_a_new_higher_version_passes(tmp_path, pypi, monkeypatch):
    pypi(["0.1.0"])
    monkeypatch.setenv("RELEASE_TAG", "v0.1.1")
    assert gate.version_problems(_repo(tmp_path, "0.1.1")) == []


@pytest.mark.parametrize("published, version, expect", [
    (["0.1.0", "0.1.1"], "0.1.1", "already on PyPI"),
    (["0.2.0"], "0.1.5", "not higher"),
    (["0.1.0"], "0.1.01", "normalized"),
    (["0.1.0"], "banana", "not a valid PEP 440"),
])
def test_bad_versions_are_refused(tmp_path, pypi, monkeypatch, published, version, expect):
    pypi(published)
    monkeypatch.delenv("RELEASE_TAG", raising=False)
    problems = gate.version_problems(_repo(tmp_path, version))
    assert any(expect in p for p in problems), problems


def test_tag_changelog_and_plugin_must_agree(tmp_path, pypi, monkeypatch):
    pypi(["0.1.0"])
    monkeypatch.setenv("RELEASE_TAG", "v0.1.2")
    problems = gate.version_problems(_repo(tmp_path, "0.1.1", changelog="# Changelog\n\n## 0.1.0\n", plugin="0.1.0"))
    assert any("tag" in p for p in problems) and any("CHANGELOG" in p for p in problems) and any("agent-plugin" in p for p in problems)


def test_a_release_with_problems_exits_but_a_dry_run_only_warns(tmp_path, pypi, monkeypatch, capsys):
    pypi(["0.1.1"])
    repo = _repo(tmp_path, "0.1.1")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    gate.check_version(repo)
    assert "::warning::" in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_EVENT_NAME", "release")
    with pytest.raises(SystemExit):
        gate.check_version(repo)
