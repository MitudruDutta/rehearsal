"""Start an installed `rehearsal mcp` over stdio the way an AI assistant does, and check what it offers.

    python smoke-mcp.py /path/to/venv/bin/rehearsal

No server or API key is involved: the MCP server must start without one, list every tool, and answer a tool call
with the instruction to sign in instead of crashing.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED = {
    "workspace_status", "list_applications", "add_application", "build_world", "job_status", "control_job",
    "list_worlds", "list_scenarios", "recheck_world", "list_agents", "create_agent", "run_evaluation",
    "run_results", "episode_details", "improve_agent", "compare_runs", "waiting_turns", "take_action",
}


async def main(rehearsal: str) -> None:
    home = tempfile.mkdtemp()  # no saved login, no environment key
    env = {"PATH": os.environ["PATH"], "HOME": home, "REHEARSAL_CONFIG": os.path.join(home, "none.json")}
    async with stdio_client(StdioServerParameters(command=rehearsal, args=["mcp"], env=env)) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), 30)
            tools = {t.name for t in (await session.list_tools()).tools}
            missing = EXPECTED - tools
            assert not missing, f"MCP server is missing tools: {sorted(missing)}"
            result = await session.call_tool("workspace_status", {})
            text = result.content[0].text if result.content else ""
            assert result.isError and "rehearsal login" in text, f"unexpected answer without a key: {text[:300]}"
    print(f"MCP server OK: {len(tools)} tools; without a key it asks for `rehearsal login`")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
