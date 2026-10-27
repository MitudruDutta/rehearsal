"""Generate every client-specific file of the Rehearsal agent plugin from its sources.

Sources (edit these):
    agent-plugin/plugin.json          Agent Plugins 1.0.0 manifest; its version must equal rehearsal/py/pyproject.toml's
    agent-plugin/mcp.json             Agent Plugins 1.0.0 MCP config (the stdio server, started with uvx from PyPI)
    agent-plugin/overlays/claude.json Claude Code extras: display name, optional user options and the env they fill
    rehearsal/py/rehearsal/assets/skill/  the Rehearsal skill, also shipped in the Python and npm packages

Generated (never edit by hand):
    agent-plugin/skills/rehearsal/                  copy of the skill
    agent-plugin/.claude-plugin/plugin.json         Claude Code manifest
    agent-plugin/.mcp.json                          Claude Code MCP config, with the user options in env
    agent-plugin/.mcp.portable.json                 the same server without client-specific placeholders
    agent-plugin/.codex-plugin/plugin.json          Codex manifest
    agent-plugin/.cursor-plugin/plugin.json         Cursor manifest
    agent-plugin/providers/antigravity/             Antigravity CLI (agy) bundle: its closed plugin.json schema cannot
                                                    sit next to the Agent Plugins manifest, so it gets its own folder
    .claude-plugin/marketplace.json                 marketplace for `claude plugin marketplace add MitudruDutta/rehearsal`
    .agents/plugins/marketplace.json                marketplace for `codex plugin marketplace add MitudruDutta/rehearsal`

Usage:
    python scripts/build_agent_plugin.py               write the generated files
    python scripts/build_agent_plugin.py --check       exit 1 if any generated file differs from its sources (CI runs this)
    python scripts/build_agent_plugin.py --export DIR  write a standalone plugin repository to DIR: the plugin at the
                                                       root (for clients that install from a repository root, such as
                                                       Goose, Qwen Code, Hermes Agent and OpenClaw), its
                                                       Claude Code marketplace, and a Codex bundle under plugins/
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "agent-plugin"
PY = ROOT / "rehearsal" / "py"  # the Python package
SKILL = PY / "rehearsal" / "assets" / "skill"


def _read(path: Path) -> dict:
    data = json.loads(path.read_text())
    data.pop("//", None)
    return data


def _json(value: dict) -> str:
    return json.dumps(value, indent=4, ensure_ascii=False) + "\n"


def outputs() -> dict[Path, str]:
    plugin, mcp, claude = _read(PLUGIN / "plugin.json"), _read(PLUGIN / "mcp.json"), _read(PLUGIN / "overlays" / "claude.json")
    version = tomllib.loads((PY / "pyproject.toml").read_text())["project"]["version"]
    if plugin["version"] != version:
        raise SystemExit(f"agent-plugin/plugin.json version {plugin['version']} must equal rehearsal/py/pyproject.toml version {version}")
    common = {k: plugin[k] for k in ("name", "version", "description", "author", "homepage", "repository", "license", "keywords")}
    servers = {name: {k: v for k, v in s.items() if k != "type"} for name, s in mcp["mcpServers"].items()}
    portable = {"mcpServers": {name: {"type": "stdio", **s} for name, s in servers.items()}}
    claude_mcp = {"mcpServers": {name: {"type": "stdio", **s, "env": claude["env"]} for name, s in servers.items()}}
    interface = plugin["extensions"]["com.openai"]["interface"]
    files: dict[Path, str] = {
        PLUGIN / ".claude-plugin" / "plugin.json": _json({**common, "displayName": claude["displayName"], "userConfig": claude["userConfig"]}),
        PLUGIN / ".mcp.json": _json(claude_mcp),
        PLUGIN / ".mcp.portable.json": _json(portable),
        PLUGIN / ".codex-plugin" / "plugin.json": _json({**common, "skills": "./skills/", "mcpServers": "./.mcp.portable.json", "interface": interface}),
        PLUGIN / ".cursor-plugin" / "plugin.json": _json({**common, "skills": "skills/", "mcpServers": ".mcp.portable.json"}),
        PLUGIN / "providers" / "antigravity" / "plugin.json": _json({
            "$schema": "https://antigravity.google/schemas/v1/plugin.json", "name": plugin["name"], "description": plugin["description"],
        }),
        PLUGIN / "providers" / "antigravity" / "mcp_config.json": _json({"mcpServers": servers}),
        ROOT / ".claude-plugin" / "marketplace.json": _json({
            "name": "rehearsal",
            "owner": plugin["author"],
            "metadata": {"description": "Rehearsal plugin marketplace for Claude Code.", "version": version},
            "plugins": [{"name": plugin["name"], "source": "./agent-plugin", "description": plugin["description"], "version": version,
                         "author": plugin["author"], "homepage": plugin["homepage"], "repository": plugin["repository"],
                         "license": plugin["license"], "keywords": plugin["keywords"], "category": "development"}],
        }),
        ROOT / ".agents" / "plugins" / "marketplace.json": _json({
            "name": "rehearsal",
            "interface": {"displayName": interface["displayName"]},
            "plugins": [{"name": plugin["name"], "source": {"source": "local", "path": "./agent-plugin"},
                         "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": interface["category"]}],
        }),
    }
    for src in sorted(SKILL.rglob("*.md")):
        for skills in (PLUGIN / "skills", PLUGIN / "providers" / "antigravity" / "skills"):
            files[skills / "rehearsal" / src.relative_to(SKILL)] = src.read_text()
    return files


def export(target: Path) -> None:
    """The plugin as its own repository. Codex is given a materialized bundle because its marketplace does not accept
    a source path that points at the marketplace root itself."""
    import shutil

    generated = outputs()
    files = {p: t for p, t in generated.items() if PLUGIN in p.parents}
    plugin = _read(PLUGIN / "plugin.json")
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty; export into a new or empty folder")
    for p, text in files.items():
        for base in (target, target / "plugins" / plugin["name"]):
            out = base / p.relative_to(PLUGIN)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)
    for name in ("plugin.json", "mcp.json", "README.md"):
        shutil.copy(PLUGIN / name, target / name)
        shutil.copy(PLUGIN / name, target / "plugins" / plugin["name"] / name)
    if (ROOT / "LICENSE").is_file():
        shutil.copy(ROOT / "LICENSE", target / "LICENSE")
    market = json.loads(generated[ROOT / ".claude-plugin" / "marketplace.json"])
    market["plugins"][0]["source"] = "./"
    (target / ".claude-plugin" / "marketplace.json").write_text(_json(market))
    codex = json.loads(generated[ROOT / ".agents" / "plugins" / "marketplace.json"])
    codex["plugins"][0]["source"]["path"] = f"./plugins/{plugin['name']}"
    (target / ".agents" / "plugins").mkdir(parents=True, exist_ok=True)
    (target / ".agents" / "plugins" / "marketplace.json").write_text(_json(codex))
    print(f"Exported the plugin repository to {target}")


def main(check: bool) -> None:
    files = outputs()
    owned = [PLUGIN / "skills", PLUGIN / "providers"]  # every file under these folders is generated
    stale_skill = {p for d in owned for p in d.rglob("*") if p.is_file()} - set(files)
    stale_skill |= {p for p in [PLUGIN / "gemini-extension.json"] if p.exists()}  # Gemini CLI became Antigravity CLI
    drift = sorted(str(p.relative_to(ROOT)) for p, text in files.items() if not p.is_file() or p.read_text() != text)
    drift += sorted(f"{p.relative_to(ROOT)} (no longer generated)" for p in stale_skill)
    if check:
        if drift:
            raise SystemExit("Agent plugin files are out of date. Run: python scripts/build_agent_plugin.py\n  " + "\n  ".join(drift))
        print(f"Agent plugin files match their sources ({len(files)} files)")
        return
    for p in stale_skill:
        p.unlink()
    for p, text in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    print(f"Wrote {len(files)} files" + (f"; updated: {', '.join(drift)}" if drift else "; nothing changed"))


if __name__ == "__main__":
    if "--export" in sys.argv:
        export(Path(sys.argv[sys.argv.index("--export") + 1]).resolve())
    else:
        main("--check" in sys.argv)
