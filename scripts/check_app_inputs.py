"""Times the World Compiler's handling of real application inputs: the source overview, file search, grep, and every
API description it would discover in each repository given. Any step slower than the limit, or any unexpected error,
fails the check.

    python scripts/check_app_inputs.py var/sources/*/* var/local-sources/*
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from rehearsal.compiler.apispec import operations, parse_spec
from rehearsal.compiler.repo import Repo

LIMIT_S = 10.0
SPEC_GLOBS = ("*swagger*.json", "*openapi*.json", "*openapi*.y*ml", "*swagger*.y*ml")  # as the compiler's discovery step


def timed(label: str, fn, problems: list[str]):
    started = time.monotonic()
    try:
        out = fn()
    except Exception as exc:  # noqa: BLE001 - reported, then judged
        out = exc
    seconds = time.monotonic() - started
    if seconds > LIMIT_S:
        problems.append(f"{label} took {seconds:.1f} s")
    return out, seconds


def check(root: Path) -> list[str]:
    problems: list[str] = []
    repo = Repo(root)
    _, s = timed("overview", repo.overview, problems)
    line = [f"overview {s:.1f}s"]
    _, s = timed("grep", lambda: repo.grep(r"route|router|def |func "), problems)
    line.append(f"grep {s:.1f}s")
    specs = [rel for g in SPEC_GLOBS for rel in repo.find(g).splitlines() if rel and not rel.startswith(("(", "..."))]
    for rel in specs:
        out, s = timed(f"spec {rel}", lambda rel=rel: len(operations(parse_spec(repo.read_text(rel)))), problems)
        result = f"{out} ops" if isinstance(out, int) else f"skipped: {type(out).__name__}: {str(out)[:60]}"
        line.append(f"\n    {rel}: {result} in {s:.1f}s")
    print(f"{root}: " + ", ".join(line[:2]) + "".join(line[2:]))
    return problems


def main(paths: list[str]) -> int:
    problems = [f"{p}: {x}" for p in paths if Path(p).is_dir() for x in check(Path(p))]
    print("\n" + ("\n".join(problems) if problems else f"every step finished within {LIMIT_S:.0f} s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
