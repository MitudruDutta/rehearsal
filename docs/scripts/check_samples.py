#!/usr/bin/env python3
"""Checks the code samples in the pages against the product, without a server.

    python docs/scripts/check_samples.py

For every page under docs/content/:

    python blocks   must be valid Python
    json blocks     must be valid JSON
    shell blocks    every `rehearsal ...` command must be accepted by the real command-line parser:
                    the command exists, its options exist, and its required arguments are there

This does not run a sample against a server. It catches the common failure: a page that names a command, an
option or an argument that the product does not have. Run it with the repository's Python environment.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_reference import DOCS, capture_parser  # noqa: E402  (sets up a safe environment before any import)

FENCE = re.compile(r"^```(\w+)[^\n]*\n(.*?)^```\s*$", re.S | re.M)
SHELL = {"bash", "sh", "shell", "powershell"}
# What stands before `rehearsal` when a page runs it through another program.
PREFIXES = [
    re.compile(r"^uvx --from \S+ "),
    re.compile(r"^docker compose .*? exec api "),
]


def commands(block: str) -> list[str]:
    """The logical command lines of a shell block: continuation lines joined, comments dropped."""
    joined = re.sub(r"\\\n\s*", " ", block)
    out = []
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for prefix in PREFIXES:
            line = prefix.sub("", line)
        if line.startswith("rehearsal "):
            out.append(line)
    return out


def arguments(command: str) -> list[str]:
    command = re.split(r"\s+(?:>|\||&&)\s*", command)[0]  # what comes after a redirect or a pipe is not ours
    command = re.sub(r"<[a-z][a-z0-9_]*>", "value", command)  # a placeholder stands for some value
    return shlex.split(command)[1:]


def main() -> None:
    parser = capture_parser()
    problems: list[str] = []
    counts = {"python": 0, "json": 0, "commands": 0}

    class Refused(Exception):
        pass

    def refuse(self: argparse.ArgumentParser, message: str) -> None:
        raise Refused(message)

    def leave(self: argparse.ArgumentParser, status: int = 0, message: str | None = None) -> None:
        if status:
            raise Refused((message or "").strip())
        raise Refused("")  # --help and --version leave with status 0: fine

    argparse.ArgumentParser.error = refuse  # type: ignore[method-assign]
    argparse.ArgumentParser.exit = leave  # type: ignore[method-assign]

    for page in sorted((DOCS / "content").rglob("*.mdx")):
        where = page.relative_to(DOCS).as_posix()
        for language, block in FENCE.findall(page.read_text(encoding="utf-8")):
            if language in ("python", "py"):
                counts["python"] += 1
                try:
                    compile(block, where, "exec")
                except SyntaxError as error:
                    problems.append(f"{where}: a Python sample does not parse: {error.msg} (line {error.lineno} of the sample)")
            elif language == "json":
                counts["json"] += 1
                try:
                    json.loads(block)
                except ValueError as error:
                    problems.append(f"{where}: a JSON sample does not parse: {error}")
            elif language in SHELL:
                for command in commands(block):
                    counts["commands"] += 1
                    try:
                        args = arguments(command)
                        if args and args[0] in ("--version", "--help"):
                            continue
                        argparse.ArgumentParser.parse_args(parser, args)
                    except Refused as refused:
                        if str(refused):
                            problems.append(f"{where}: `{command}` is not accepted: {refused}")
                    except ValueError as error:
                        problems.append(f"{where}: `{command}` cannot be read as a command: {error}")

    if problems:
        sys.exit(f"check_samples: {len(problems)} problem{'s' * (len(problems) != 1)}\n  " + "\n  ".join(problems))
    print(f"check_samples: {counts['commands']} rehearsal commands, {counts['python']} Python samples and {counts['json']} JSON samples are valid.")


if __name__ == "__main__":
    main()
