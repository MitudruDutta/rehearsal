"""The agent plugin stays in step with its sources, the package version, and the secrets rule."""

import importlib.util
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # the repository; the Python package is rehearsal/py


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_plugin_files_match_their_sources():
    build = _module(ROOT / "scripts" / "build_agent_plugin.py", "build_agent_plugin")
    for path, text in build.outputs().items():
        assert path.is_file() and path.read_text() == text, f"{path.relative_to(ROOT)} is stale: run scripts/build_agent_plugin.py"


def test_plugin_version_is_the_package_version():
    version = tomllib.loads((ROOT / "rehearsal/py/pyproject.toml").read_text())["project"]["version"]
    for manifest in ["agent-plugin/plugin.json", "agent-plugin/.claude-plugin/plugin.json", "agent-plugin/.codex-plugin/plugin.json"]:
        assert json.loads((ROOT / manifest).read_text())["version"] == version, manifest


def test_mcp_server_pins_a_release_that_has_rehearsal_login():
    args = json.loads((ROOT / "agent-plugin" / "mcp.json").read_text())["mcpServers"]["rehearsal"]["args"]
    assert args[:2] == ["--from", "rehearsal-kit[mcp]>=0.1.1"] and args[2:] == ["rehearsal", "mcp"]


def test_no_secret_in_plugin_files_and_placeholders_name_declared_options():
    claude = json.loads((ROOT / "agent-plugin" / ".claude-plugin" / "plugin.json").read_text())
    declared = set(claude["userConfig"])
    assert claude["userConfig"]["api_key"]["sensitive"] is True
    for path in (ROOT / "agent-plugin").rglob("*.json"):
        text = path.read_text()
        assert not re.search(r"rh_[0-9a-f]{8}_", text), f"{path} contains an API key"
        assert set(re.findall(r"\$\{user_config\.(\w+)\}", text)) <= declared, path
    portable = (ROOT / "agent-plugin" / ".mcp.portable.json").read_text()
    assert "${" not in portable  # clients other than Claude Code must not receive placeholders they cannot expand
