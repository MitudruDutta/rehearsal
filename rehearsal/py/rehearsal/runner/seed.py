"""Executes seed steps (world base state and per-scenario setup)."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from ..core.contracts import SeedStep, dig, render_template, render_value
from .gateway import basic_header, graphql_failed
from .runtime import WorldInstance


def readable(body: str, limit: int = 1500) -> str:
    """A response body for an error message. An HTML error page becomes its visible text: a framework's debug page is
    mostly styles, and the reason it gives (such as which host to allow) comes after them."""
    if "<html" not in body[:1000].lower():
        return body[:limit]
    text = re.sub(r"(?is)<(style|script)\b.*?</\1>|<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:limit]


def _rooted(result: Any, path: str) -> str | None:
    """The same path without the leading parts that do not exist, when that finds a value: a path written as if the
    response were wrapped (``json.data.x``, ``body.data.x``) when paths start at the response body itself."""
    parts = re.sub(r"\[(\d+)\]", r".\1", path.strip()).lstrip("$").lstrip(".").split(".")
    for k in range(1, len(parts)):
        try:
            dig(result, ".".join(parts[k:]))
            return ".".join(parts[k:])
        except KeyError:
            continue
    return None


class SeedError(Exception):
    def __init__(self, index: int, step: SeedStep, detail: str):
        super().__init__(f"seed step {index} ({step.kind} {step.method if step.kind == 'http' else ''} {step.path if step.kind == 'http' else step.command}) failed: {detail}")
        self.index = index
        self.detail = detail


def _last_json(stdout: str) -> Any:
    for line in reversed([ln.strip() for ln in stdout.splitlines() if ln.strip()]):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise KeyError("no JSON line in stdout")


def run_seed(instance: WorldInstance, steps: list[SeedStep], variables: dict[str, Any], *, log: Any = None) -> dict[str, Any]:
    """Runs steps in order, saving response values into ``variables`` (mutated and returned)."""
    for i, step in enumerate(steps):
        scopes = {"vars": variables, "secret": instance.record.secrets}
        try:
            if step.kind == "exec":
                cmd = [render_template(c, scopes) for c in step.command or []]
                rc, out, err = instance.exec(step.service, cmd, user=step.user, timeout=600)
                if rc != 0:
                    raise SeedError(i, step, f"exit {rc}: {(err or out)[-1500:]}")
                for var, path in step.save.items():
                    if path == "$stdout":
                        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
                        if not lines:
                            raise SeedError(i, step, "no stdout to save")
                        variables[var] = lines[-1]
                    else:
                        variables[var] = dig(_last_json(out), path)
                result: Any = out[-500:]
            else:
                headers = {k: render_template(v, scopes) for k, v in step.headers.items()}
                if step.basic_auth:
                    user, pw = (render_template(x, scopes) for x in step.basic_auth)
                    headers["Authorization"] = basic_header(user, pw)
                body = render_value(step.json_body, scopes) if step.json_body is not None else None
                resp = instance.http(step.service, step.method, render_template(step.path, scopes), headers=headers, json_body=body)
                if resp.status_code not in step.expect_status:
                    detail = f"HTTP {resp.status_code}: {readable(resp.text)}"
                    if resp.status_code >= 500:  # the response body rarely says why; the server log does
                        detail += f"\n--- {step.service} log tail ---\n{instance.logs(step.service, 40)[-3000:]}"
                    raise SeedError(i, step, detail)
                try:
                    result = resp.json()
                except ValueError:
                    result = resp.text
                if step.path.rstrip("/").endswith("graphql") and (why := graphql_failed(result)):
                    raise SeedError(i, step, f"GraphQL errors: {why}")
                for var, path in step.save.items():
                    try:
                        variables[var] = dig(result, path)
                    except KeyError as exc:  # show the real response so the path can be corrected in one try
                        fix = _rooted(result, path)
                        hint = f"; paths start at the response body itself, so this one is {fix!r}" if fix else ""
                        raise SeedError(i, step, f"missing value {exc}{hint}; the response was: {json.dumps(result, default=str)[:600]}") from exc
        except KeyError as exc:
            raise SeedError(i, step, f"missing value {exc}") from exc
        if log:
            log(f"seed {i + 1}/{len(steps)} ok{': ' + step.note if step.note else ''}")
    return variables
