"""Python client for the Rehearsal API.

    from rehearsal.sdk import Rehearsal
    client = Rehearsal()  # REHEARSAL_API_KEY and REHEARSAL_URL, else what `rehearsal login` saved
    build = client.worlds.build(application_id)
    job = client.jobs.wait(build["job_id"])
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterator

import httpx

DEFAULT_URL = "https://rehearsalkit.xyz"  # the hosted service; a server of your own: `rehearsal login --url ...` or REHEARSAL_URL


def config_path() -> Path:
    """Where `rehearsal login` keeps the server URL and API key (readable by this user only)."""
    return Path(os.environ.get("REHEARSAL_CONFIG") or Path.home() / ".config" / "rehearsal" / "config.json").expanduser()


def saved_login() -> dict[str, str]:
    try:
        data = json.loads(config_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _env(name: str) -> str | None:
    """An environment value, ignoring an agent client's placeholder it did not expand (such as ${user_config.api_key})."""
    value = (os.environ.get(name) or "").strip()
    return None if not value or value.startswith("${") else value


def save_login(url: str, api_key: str) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.touch(mode=0o600)
    tmp.chmod(0o600)
    tmp.write_text(json.dumps({"url": url.rstrip("/"), "api_key": api_key}, indent=2))
    tmp.replace(path)
    return path


class RehearsalError(Exception):
    def __init__(self, status: int, detail: Any):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


class _Resource:
    def __init__(self, client: "Rehearsal"):
        self.c = client


class Applications(_Resource):
    def create(self, name: str, source: dict[str, Any], images: dict[str, str] | None = None, policies: str = "") -> dict[str, Any]:
        return self.c.post("/v1/applications", {"name": name, "source": source, "images": images or {}, "policies": policies})

    def import_catalog(self) -> list[dict[str, Any]]:
        return self.c.post("/v1/applications/import-catalog", {})

    def list(self) -> list[dict[str, Any]]:
        return self.c.get("/v1/applications")

    def get(self, app_id: str) -> dict[str, Any]:
        return self.c.get(f"/v1/applications/{app_id}")

    def upload_source(self, app_id: str, archive: str) -> dict[str, Any]:
        with open(archive, "rb") as fh:
            return self.c.request("POST", f"/v1/applications/{app_id}/source", files={"file": (os.path.basename(archive), fh, "application/gzip")})


class Worlds(_Resource):
    def build(self, application_id: str, **options: Any) -> dict[str, Any]:
        return self.c.post("/v1/world-builds", {"application_id": application_id, **options})

    def make_agent(self, world_version_id: str, name: str = "", rounds: int = 3, repeats: int = 1) -> dict[str, Any]:
        """Agent Factory: drafts an agent from the world, hardens it with the fix loop and proves it on held-out jobs.
        The finished job's result has every score and `artifact_id`, a zip with a runnable agent and its proof report."""
        return self.c.post("/v1/factory", {"world_version_id": world_version_id, "name": name, "rounds": rounds, "repeats": repeats})

    def list(self) -> list[dict[str, Any]]:
        return self.c.get("/v1/worlds")

    def report_incident(self, wv_id: str, incident: str) -> dict[str, Any]:
        """Turns something an agent got wrong in production into a validated job in this world (a job; poll it). Describe
        what was asked, what the agent did and what should have happened; a transcript is best."""
        return self.c.post(f"/v1/world-versions/{wv_id}/incidents", {"incident": incident})

    def library(self) -> list[dict[str, Any]]:
        """Ready-made worlds any workspace can rehearse an agent on, or make an agent for, without building one."""
        return self.c.get("/v1/library")

    def version(self, wv_id: str) -> dict[str, Any]:
        return self.c.get(f"/v1/world-versions/{wv_id}")

    def scenarios(self, wv_id: str) -> list[dict[str, Any]]:
        return self.c.get(f"/v1/world-versions/{wv_id}/scenarios")

    def validate(self, wv_id: str) -> dict[str, Any]:
        return self.c.post(f"/v1/world-versions/{wv_id}/validate", {})

    def bundle(self, wv_id: str, include_images: bool = False) -> dict[str, Any]:
        return self.c.post(f"/v1/world-versions/{wv_id}/bundle?include_images={str(include_images).lower()}", {})


class Jobs(_Resource):
    def get(self, job_id: str) -> dict[str, Any]:
        return self.c.get(f"/v1/jobs/{job_id}")

    def command(self, job_id: str, command: str) -> dict[str, Any]:
        return self.c.post(f"/v1/jobs/{job_id}/commands", {"command": command})

    def events(self, job_id: str, cursor: int = 0) -> Iterator[dict[str, Any]]:
        return self.c.stream(f"/v1/jobs/{job_id}/events", cursor)

    def wait(self, job_id: str, timeout_s: float = 6 * 3600, poll_s: float = 3) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            job = self.get(job_id)
            if job["status"] in ("succeeded", "failed", "cancelled"):
                return job
            time.sleep(poll_s)
        raise TimeoutError(f"job {job_id} did not finish within {timeout_s} seconds")


class Profiles(_Resource):
    def create(self, name: str, system_prompt: str = "", **fields: Any) -> dict[str, Any]:
        return self.c.post("/v1/agent-profiles", {"name": name, "system_prompt": system_prompt, **fields})

    def list(self) -> list[dict[str, Any]]:
        return self.c.get("/v1/agent-profiles")

    def autofix(self, profile_id: str, run_id: str, rounds: int = 3, repeats: int = 1) -> dict[str, Any]:
        """Starts the fix loop: propose a version, rehearse it on train and dev, keep it only if it verifies more, and
        prove the best one against the original on held-out jobs. Returns the job; its result has every round."""
        return self.c.post("/v1/autofix", {"profile_id": profile_id, "run_id": run_id, "rounds": rounds, "repeats": repeats})


class Evaluations(_Resource):
    def create(self, world_version_id: str, profile_ids: list[str], splits: list[str] | None = None, repeats: int | None = None, **fields: Any) -> dict[str, Any]:
        """Without splits or repeats, the server runs every job twice with the default stress layer on."""
        return self.c.post("/v1/evaluations", {"world_version_id": world_version_id, "profile_ids": profile_ids, **({"splits": splits} if splits else {}),
                                               **({"repeats": repeats} if repeats else {}), **fields})

    def compare(self, run_a: str, run_b: str | None = None) -> dict[str, Any]:
        return self.c.get("/v1/compare", params={"run_a": run_a, **({"run_b": run_b} if run_b else {})})


class Runs(_Resource):
    def get(self, run_id: str) -> dict[str, Any]:
        return self.c.get(f"/v1/runs/{run_id}")

    def episodes(self, run_id: str) -> list[dict[str, Any]]:
        return self.c.get(f"/v1/runs/{run_id}/episodes")

    def failures(self, run_id: str) -> dict[str, Any]:
        """Why episodes failed, per agent: named causes, each with its count, its usual fix and example episodes."""
        return self.c.get(f"/v1/runs/{run_id}/failures")

    def episode(self, ep_id: str) -> dict[str, Any]:
        return self.c.get(f"/v1/episodes/{ep_id}")

    def events(self, run_id: str, cursor: int = 0) -> Iterator[dict[str, Any]]:
        return self.c.stream(f"/v1/runs/{run_id}/events", cursor)

    def intervene(self, ep_id: str, **body: Any) -> dict[str, Any]:
        return self.c.post(f"/v1/episodes/{ep_id}/interventions", body)

    def command(self, run_id: str, command: str) -> dict[str, Any]:
        return self.c.post(f"/v1/runs/{run_id}/commands", {"command": command})


class ExternalAgent(_Resource):
    """Drive an episode whose profile uses driver="external"."""

    def observation(self, ep_id: str) -> dict[str, Any]:
        return self.c.get(f"/v1/episodes/{ep_id}/observation")

    def act(self, ep_id: str, actor: str, tool: str, args: dict[str, Any], idempotency_key: str, wait_s: float = 120) -> dict[str, Any]:
        self.c.post(f"/v1/episodes/{ep_id}/actions", {"actor": actor, "tool": tool, "args": args, "idempotency_key": idempotency_key})
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            r = self.c.get(f"/v1/episodes/{ep_id}/actions/{idempotency_key}")
            if r["status"] == "done":
                return r["result"]
            time.sleep(0.5)
        raise TimeoutError("action result not available yet; query again with the same idempotency key")


class Rehearsal:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 60):
        login = saved_login()  # environment wins; an empty or unexpanded variable (an unset plugin option) counts as unset
        self.api_key = api_key or _env("REHEARSAL_API_KEY") or login.get("api_key")
        if not self.api_key:
            raise ValueError("no Rehearsal API key: run `rehearsal login`, or set REHEARSAL_API_KEY")
        self.base_url = (base_url or _env("REHEARSAL_URL") or login.get("url") or DEFAULT_URL).rstrip("/")
        self.http = httpx.Client(base_url=self.base_url, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=timeout)
        self.applications = Applications(self)
        self.worlds = Worlds(self)
        self.jobs = Jobs(self)
        self.profiles = Profiles(self)
        self.evaluations = Evaluations(self)
        self.runs = Runs(self)
        self.external = ExternalAgent(self)

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.http.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json()
                if isinstance(detail, dict):
                    detail = detail.get("detail")
            except ValueError:
                detail = resp.text[:300]  # an HTML error page says nothing useful past this
            raise RehearsalError(resp.status_code, detail)
        return resp.json()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Any) -> Any:
        return self.request("POST", path, json=body)

    def stream(self, path: str, cursor: int = 0) -> Iterator[dict[str, Any]]:
        """Server-sent events with automatic reconnect from the last event id."""
        while True:
            try:
                with self.http.stream("GET", path, params={"cursor": cursor}, timeout=None) as resp:
                    if resp.status_code >= 400:
                        raise RehearsalError(resp.status_code, resp.read().decode()[:500])
                    event, data = None, []
                    for line in resp.iter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:"):
                            data.append(line[5:].strip())
                        elif line == "":
                            if event == "stream.end":
                                return
                            if data:
                                payload = json.loads("\n".join(data))
                                cursor = payload.get("event_id", cursor)
                                yield payload
                            event, data = None, []
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError):
                pass
            time.sleep(1)
