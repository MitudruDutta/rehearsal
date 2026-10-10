"""Versioned REST API, SSE event streams, and the static console.

Every handler resolves the caller's project from its key/session and filters
every lookup by it. Long operations return job ids; their progress is the
job's event stream.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from ..config import settings
from ..core.contracts import AgentProfile, ScenarioSpec
from ..db import queue
from ..db.events import emit, serialize
from ..db.models import (
    Action,
    AgentProfileRow,
    ApiKey,
    Application,
    Artifact,
    Credential,
    Episode,
    Event,
    Job,
    Message,
    Organization,
    Project,
    User,
    Run,
    Scenario,
    TrainingJob,
    World,
    WorldVersion,
    now,
)
from ..db.session import session
from ..worker.evaluate import summarize_run
from .auth import (
    COOKIE,
    SESSION_SECONDS,
    Principal,
    create_key,
    create_user,
    create_workspace,
    google_user,
    password_login,
    principal,
    user_cookie,
    verify_google,
)

app = FastAPI(title="Rehearsal API", version="1.0.0")


@app.exception_handler(queue.AllowanceExhausted)
async def _allowance_exhausted(request: Request, exc: queue.AllowanceExhausted) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": str(exc)})
REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent / "static"


def _get(s: Any, model: Any, id_: str, p: Principal) -> Any:
    row = s.get(model, id_)
    if row is None or getattr(row, "project_id", p.project_id) != p.project_id:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return row


def _cols(row: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    out = {}
    for c in row.__table__.columns:
        if c.name in exclude:
            continue
        v = getattr(row, c.name)
        out[c.name] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


# --------------------------------------------------------------------------- accounts
# The console signs in people (Google, or email and password); API keys authenticate the CLI, SDK, and CI.

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=320, pattern=EMAIL)
    password: str = Field(min_length=10, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=200)


_attempts: dict[str, list[float]] = {}  # ponytail: per-process limiter; use the proxy's rate limit with several API replicas


def _throttle(key: str, limit: int, window_s: float, message: str) -> None:
    recent = [t for t in _attempts.get(key, []) if time.time() - t < window_s]
    if len(recent) >= limit:
        raise HTTPException(429, message)
    _attempts[key] = [*recent, time.time()]


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@app.post("/v1/auth/signup", status_code=201)
def sign_up(body: SignupIn, response: Response, request: Request) -> dict[str, Any]:
    """Creates an account and signs the browser in; onboarding then creates the workspace."""
    if settings().signup != "open":
        raise HTTPException(403, "sign-up is closed on this server; ask an organisation owner to add you")
    _throttle(f"signup:{_ip(request)}", 5, 3600, "too many sign-ups from this address; try again in an hour")
    try:
        user_id = create_user(body.name, body.email, body.password)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _set_session(response, request, user_cookie(user_id, None))
    return {"needs_onboarding": True}


@app.post("/v1/auth/login")
def sign_in(body: LoginIn, response: Response, request: Request) -> dict[str, Any]:
    _throttle(f"login:{_ip(request)}:{body.email.strip().lower()}", 10, 900, "too many sign-in attempts; wait 15 minutes")
    user_id, project_id = password_login(body.email, body.password)
    _set_session(response, request, user_cookie(user_id, project_id))
    return {"needs_onboarding": project_id is None}


def _set_session(response: Response, request: Request, value: str) -> None:
    response.set_cookie(COOKIE, value, max_age=SESSION_SECONDS, httponly=True, samesite="lax", secure=request.url.scheme == "https")


class GoogleIn(BaseModel):
    credential: str = Field(min_length=20, max_length=8192)


@app.post("/v1/auth/google")
def google_sign_in(body: GoogleIn, response: Response, request: Request) -> dict[str, Any]:
    """Signs in (registering on first use) with a Google Identity Services ID token."""
    user_id, project_id = google_user(verify_google(body.credential), allow_new=settings().signup == "open")
    _set_session(response, request, user_cookie(user_id, project_id))
    return {"needs_onboarding": project_id is None}


class WorkspaceIn(BaseModel):
    organization: str = Field(min_length=1, max_length=200)
    project: str = Field(default="default", min_length=1, max_length=200)


@app.post("/v1/onboarding/workspace", status_code=201)
def onboarding_workspace(body: WorkspaceIn, response: Response, request: Request, p: Principal = Depends(principal)) -> dict[str, Any]:
    """First step after a new user signs in: the organisation they own and its first project."""
    if not p.user_id:
        raise HTTPException(400, "workspaces are created by signed-in users, not API keys")
    project_id = create_workspace(p.user_id, body.organization, body.project)
    _set_session(response, request, user_cookie(p.user_id, project_id))
    return {"project_id": project_id}


@app.delete("/v1/session")
def end_session(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/v1/me")
def me(p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        project = s.get(Project, p.project_id) if p.project_id else None
        org = s.get(Organization, project.org_id) if project else None
        user = s.get(User, p.user_id) if p.user_id else None
        return {
            "project_id": p.project_id or None, "key_id": p.key_id, "scopes": p.scopes,
            "project": project.name if project else None, "organization": org.name if org else None,
            "user": {"name": user.name, "email": user.email, "picture_url": user.picture_url} if user else None,
            "needs_onboarding": bool(p.user_id) and not p.project_id,
        }


@app.get("/v1/health")
def health() -> dict[str, Any]:
    wheels = sorted(p.name for p in DOWNLOADS.glob("*.whl"))
    cfg = settings()
    return {"status": "ok", "signup": cfg.signup, "google_client_id": cfg.google_client_id, "client_wheel": f"/downloads/{wheels[-1]}" if wheels else None}


# --------------------------------------------------------------------------- applications


class SourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["git", "local_path", "upload"]
    url: str | None = None
    ref: str | None = None
    commit: str | None = None
    path: str | None = None


class ApplicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source: SourceIn
    images: dict[str, str] = Field(default_factory=dict)
    policies: str = ""
    notes: str = ""
    connection_mode: Literal["source"] = "source"


@app.post("/v1/applications", status_code=201)
def create_application(body: ApplicationIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    source = body.source.model_dump(exclude_none=True)
    allowed = {"git": {"kind", "url", "ref", "commit"}, "local_path": {"kind", "path"}, "upload": {"kind"}}
    if set(source) - allowed[body.source.kind]:
        raise HTTPException(422, "source fields do not match source kind")
    if body.source.kind == "git":
        url = body.source.url or ""
        try:
            parsed = urlsplit(url)
            https = parsed.scheme == "https" and parsed.hostname and parsed.username is None and parsed.password is None and not parsed.fragment and not parsed.query
            ssh = re.fullmatch(r"git@[A-Za-z0-9.-]+:[^\s]+", url)
        except ValueError:
            https = ssh = False
        if not (https or ssh) or any(c.isspace() or ord(c) < 32 for c in url):
            raise HTTPException(422, "git source needs an HTTPS or git@host:path URL")
        if body.source.ref is not None and (not body.source.ref or body.source.ref.startswith("-") or any(c.isspace() or ord(c) < 32 for c in body.source.ref)):
            raise HTTPException(422, "invalid git ref")
        if body.source.commit is not None and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", body.source.commit):
            raise HTTPException(422, "commit must be a full lowercase hexadecimal object ID")
    elif body.source.kind == "local_path":
        if not body.source.path:
            raise HTTPException(422, "local_path source needs path")
        try:
            path = Path(body.source.path).resolve()
            roots = [Path(root).resolve() for root in settings().source_roots]
            valid = any(path == root or root in path.parents for root in roots) and path.is_dir()
        except (OSError, RuntimeError, ValueError):
            valid = False
        if not valid:
            raise HTTPException(422, "local source must be a directory within configured source roots")
        source["path"] = str(path)
    with session() as s:
        if s.scalars(select(Application).where(Application.project_id == p.project_id, Application.name == body.name)).first():
            raise HTTPException(409, f"application {body.name} exists")
        a = Application(project_id=p.project_id, name=body.name, source=source, images=body.images, policies=body.policies, notes=body.notes)
        s.add(a)
        s.flush()
        return _cols(a)


@app.post("/v1/applications/import-catalog", status_code=201)
def import_catalog(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    """Registers the pinned third-party applications from the packaged catalog (rehearsal/assets/catalog.yaml)."""
    catalog = yaml.safe_load(files("rehearsal").joinpath("assets/catalog.yaml").read_text())
    out = []
    with session() as s:
        for entry in catalog["applications"]:
            existing = s.scalars(select(Application).where(Application.project_id == p.project_id, Application.name == entry["name"])).first()
            if existing:
                out.append(_cols(existing))
                continue
            a = Application(
                project_id=p.project_id, name=entry["name"], source=entry["source"], images=entry.get("images", {}),
                notes=f"split={entry['split']}; domain={entry.get('domain')}; license={entry.get('license')}",
            )
            s.add(a)
            s.flush()
            out.append(_cols(a))
    return out


@app.get("/v1/applications")
def list_applications(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        return [_cols(a) for a in s.scalars(select(Application).where(Application.project_id == p.project_id, Application.removed_at.is_(None)).order_by(Application.created_at))]


@app.delete("/v1/applications/{app_id}")
def remove_application(app_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    """Removes an application from the console. Its builds stop; finished runs stay in the run history."""
    p.require("admin")
    with session() as s:
        a = _get(s, Application, app_id, p)
        if a.removed_at:
            raise HTTPException(404, "not found")
        stopped = 0
        for j in s.scalars(select(Job).where(Job.project_id == p.project_id, Job.kind == "world_build", Job.status.in_(("queued", "running", "paused")),
                                             Job.payload["application_id"].astext == a.id).with_for_update()):
            queue.command(s, j, "stop")
            stopped += 1
        a.removed_at = now()
        a.name = f"{a.name} (removed {a.id[-6:]})"[:200]  # frees the name: it is unique per workspace
        return {"removed": True, "builds_stopped": stopped}


@app.get("/v1/applications/{app_id}")
def get_application(app_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        a = _get(s, Application, app_id, p)
        worlds = [_cols(w) for w in s.scalars(select(World).where(World.application_id == a.id))]
        return {**_cols(a), "worlds": worlds}


@app.post("/v1/applications/{app_id}/source", status_code=201)
async def upload_source(app_id: str, file: UploadFile = File(...), p: Principal = Depends(principal)) -> dict[str, Any]:
    """Uploads a .tar.gz of the application source (extracted safely by the runner)."""
    with session() as s:
        _get(s, Application, app_id, p)
    dest_dir = settings().artifacts_dir / p.project_id / "sources"
    dest_dir.mkdir(parents=True, exist_ok=True)
    import uuid
    tmp = dest_dir / f"upload-{uuid.uuid4().hex}.tmp"
    digest, size = hashlib.sha256(), 0
    with tmp.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > 500 * 1024 * 1024:
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, "source archive over 500 MB")
            digest.update(chunk)
            fh.write(chunk)
    final = dest_dir / f"{digest.hexdigest()}.tar.gz"
    tmp.replace(final)
    with session() as s:
        a = _get(s, Application, app_id, p)
        art = Artifact(project_id=p.project_id, kind="source_upload", name=file.filename or "source.tar.gz", path=str(final), sha256=digest.hexdigest(), size=size)
        s.add(art)
        a.source = {"kind": "upload", "artifact_path": str(final), "sha256": digest.hexdigest()}
        s.flush()
        return {"artifact_id": art.id, "sha256": art.sha256, "size": size}


# --------------------------------------------------------------------------- world builds


class BuildIn(BaseModel):
    application_id: str
    model: str | None = None
    budget_usd: float | None = None
    auto_approve: bool = True
    scenario_target: int = Field(default=8, ge=1, le=30)
    max_repair_rounds: int = Field(default=2, ge=0, le=5)
    check_determinism: bool = True


@app.post("/v1/world-builds", status_code=202)
def start_build(body: BuildIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        a = _get(s, Application, body.application_id, p)
        if a.removed_at:
            raise HTTPException(404, "not found")
        _room(s, p.project_id, "world_build", settings().max_active_builds, "world builds")
        s.execute(select(Application.id).where(Application.id == a.id).with_for_update())
        world = s.scalars(select(World).where(World.application_id == a.id)).first()
        if world is None:
            world = World(project_id=p.project_id, application_id=a.id, name=a.name)
            s.add(world)
            s.flush()
        version = (s.scalar(select(func.max(WorldVersion.version)).where(WorldVersion.world_id == world.id)) or 0) + 1
        wv = WorldVersion(project_id=p.project_id, world_id=world.id, version=version, status="building")
        s.add(wv)
        s.flush()
        job = queue.enqueue(
            s, project_id=p.project_id, kind="world_build", max_attempts=3, budget_usd=body.budget_usd,
            payload={
                "application_id": a.id, "world_id": world.id, "world_version_id": wv.id, "model": body.model, "auto_approve": body.auto_approve,
                "options": {"scenario_target": body.scenario_target, "max_repair_rounds": body.max_repair_rounds, "check_determinism": body.check_determinism},
            },
        )
        wv.build_job_id = job.id
        return {"job_id": job.id, "world_id": world.id, "world_version_id": wv.id, "version": version}


# --------------------------------------------------------------------------- jobs


@app.get("/v1/jobs")
def list_jobs(kind: str | None = None, p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        q = select(Job).where(Job.project_id == p.project_id).order_by(Job.created_at.desc()).limit(100)
        if kind:
            q = q.where(Job.kind == kind)
        return [_cols(j, ("checkpoint",)) for j in s.scalars(q)]


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        j = _get(s, Job, job_id, p)
        out = _cols(j, ("checkpoint",))
        out["completed_phases"] = (j.checkpoint or {}).get("done", [])
        return out


def _reopen_owner(s: Any, job: Job) -> None:
    """Reopen domain state atomically with a failed job's retry command."""
    if job.kind == "world_build":
        wv = s.get(WorldVersion, job.payload.get("world_version_id"))
        if wv and wv.status in ("failed", "cancelled"):
            wv.status = "building"
    elif job.kind == "evaluation":
        run = s.get(Run, job.payload.get("run_id"))
        if run and run.status in ("failed", "cancelled"):
            run.status, run.finished_at = "running", None


def _room(s: Any, project_id: str, kind: str, limit: int, what: str) -> None:
    """A shared server bounds how much one project runs at once (0 = no limit), so one account cannot fill the workers."""
    if not limit:
        return
    active = s.scalars(select(Job.payload).where(Job.project_id == project_id, Job.kind == kind, Job.status.in_(("queued", "running", "paused")))).all()
    if len({(x or {}).get("run_id") or id(x) for x in active}) >= limit:
        raise HTTPException(429, f"this workspace already has {limit} {what} in progress; wait for one to finish or stop it")


class CommandIn(BaseModel):
    command: Literal["pause", "resume", "stop", "retry"]


@app.post("/v1/jobs/{job_id}/commands")
def job_command(job_id: str, body: CommandIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        j = _get(s, Job, job_id, p)
        s.refresh(j, with_for_update=True)
        try:
            queue.command(s, j, body.command)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if body.command == "retry":
            _reopen_owner(s, j)
        return {"status": j.status, "pause_requested": j.pause_requested, "cancel_requested": j.cancel_requested}


# --------------------------------------------------------------------------- SSE


async def _stream(stream: str, request: Request, cursor: int, terminal: Any) -> Any:
    idle = 0.0
    while True:
        if await request.is_disconnected():
            return
        with session() as s:
            rows = list(s.scalars(select(Event).where(Event.stream == stream, Event.id > cursor).order_by(Event.id).limit(200)))
            payload = [serialize(e) for e in rows]
            done = terminal(s)
        for ev in payload:
            cursor = ev["event_id"]
            yield f"id: {cursor}\ndata: {json.dumps(ev, default=str)}\n\n"
        if payload:
            idle = 0.0
            continue
        if done:
            yield "event: stream.end\ndata: {}\n\n"
            return
        idle += 0.5
        if idle >= 15:
            idle = 0.0
            yield ": keep-alive\n\n"
        await asyncio.sleep(0.5)


def _cursor(request: Request, cursor: int | None) -> int:
    last = request.headers.get("last-event-id")
    return int(last) if last and last.isdigit() else (cursor or 0)


@app.get("/v1/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, cursor: int | None = None, p: Principal = Depends(principal)) -> StreamingResponse:
    with session() as s:
        _get(s, Job, job_id, p)

    def terminal(s: Any) -> bool:
        j = s.get(Job, job_id)
        return j is not None and j.status in ("succeeded", "failed", "cancelled")

    return StreamingResponse(_stream(job_id, request, _cursor(request, cursor), terminal), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/v1/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, cursor: int | None = None, p: Principal = Depends(principal)) -> StreamingResponse:
    with session() as s:
        _get(s, Run, run_id, p)

    def terminal(s: Any) -> bool:
        r = s.get(Run, run_id)
        return r is not None and r.status in ("finished", "failed", "cancelled")

    return StreamingResponse(_stream(run_id, request, _cursor(request, cursor), terminal), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/v1/streams/{stream}/events/page")
def events_page(stream: str, cursor: int = 0, limit: int = 500, p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    """Non-streaming page of events (for replay and reconnect snapshots)."""
    with session() as s:
        rows = s.scalars(select(Event).where(Event.stream == stream, Event.project_id == p.project_id, Event.id > cursor).order_by(Event.id).limit(min(limit, 2000)))
        return [serialize(e) for e in rows]


# --------------------------------------------------------------------------- worlds & scenarios


@app.get("/v1/worlds")
def list_worlds(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        out = []
        live = select(Application.id).where(Application.removed_at.is_(None))
        for w in s.scalars(select(World).where(World.project_id == p.project_id, World.application_id.in_(live)).order_by(World.created_at)):
            versions = s.scalars(select(WorldVersion).where(WorldVersion.world_id == w.id).order_by(WorldVersion.version))
            out.append({**_cols(w), "versions": [{"id": v.id, "version": v.version, "status": v.status, "content_hash": v.content_hash, "build_job_id": v.build_job_id} for v in versions]})
        return out


@app.get("/v1/world-versions/{wv_id}")
def get_world_version(wv_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    p.require("evaluator")
    with session() as s:
        wv = _get(s, WorldVersion, wv_id, p)
        out = _cols(wv, ("private", "snapshot_dir"))
        out["scenario_counts"] = dict(s.execute(select(Scenario.split, func.count()).where(Scenario.world_version_id == wv.id).group_by(Scenario.split)).all())
        return out


@app.get("/v1/world-versions/{wv_id}/scenarios")
def list_scenarios(wv_id: str, p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        _get(s, WorldVersion, wv_id, p)
        return [_cols(sc, ("snapshot_dir",)) for sc in s.scalars(select(Scenario).where(Scenario.world_version_id == wv_id).order_by(Scenario.split, Scenario.slug))]


@app.get("/v1/scenarios/{sc_id}")
def get_scenario(sc_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        return _cols(_get(s, Scenario, sc_id, p), ("snapshot_dir",))


@app.post("/v1/scenarios/{sc_id}/approve")
def approve_scenario(sc_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        sc = _get(s, Scenario, sc_id, p)
        if sc.status not in ("validated", "approved"):
            raise HTTPException(409, f"only validated scenarios can be approved (status {sc.status})")
        sc.status, sc.approved_by, sc.approved_at = "approved", p.actor, now()
        return _cols(sc)


@app.post("/v1/scenarios/{sc_id}/reject")
def reject_scenario(sc_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        sc = _get(s, Scenario, sc_id, p)
        sc.status = "rejected"
        return _cols(sc)


class ScenarioProposal(BaseModel):
    scenario: dict[str, Any]


@app.post("/v1/world-versions/{wv_id}/scenarios", status_code=202)
def propose_scenario(wv_id: str, body: ScenarioProposal, p: Principal = Depends(principal)) -> dict[str, Any]:
    """Adds a scenario to a published world; it is validated before it can be approved."""
    try:
        spec = ScenarioSpec.model_validate(body.scenario)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, str(exc)[:2000]) from exc
    with session() as s:
        wv = _get(s, WorldVersion, wv_id, p)
        if wv.status != "published":
            raise HTTPException(409, "world version is not published")
        if s.scalars(select(Scenario).where(Scenario.world_version_id == wv_id, Scenario.slug == spec.id)).first():
            raise HTTPException(409, f"scenario {spec.id} exists")
        sc = Scenario(project_id=p.project_id, world_version_id=wv_id, slug=spec.id, family=spec.family, split=spec.split, spec=spec.model_dump(mode="json"), status="proposed")
        s.add(sc)
        s.flush()
        job = queue.enqueue(s, project_id=p.project_id, kind="world_validate", payload={"world_version_id": wv_id, "scenario_ids": [sc.id]})
        return {"scenario_id": sc.id, "job_id": job.id}


@app.post("/v1/world-versions/{wv_id}/validate", status_code=202)
def revalidate(wv_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        wv = _get(s, WorldVersion, wv_id, p)
        if wv.status != "published":
            raise HTTPException(409, "world version is not published")
        job = queue.enqueue(s, project_id=p.project_id, kind="world_validate", payload={"world_version_id": wv_id})
        return {"job_id": job.id}


# --------------------------------------------------------------------------- agent profiles


class ProfileIn(BaseModel):
    name: str
    system_prompt: str = ""
    tool_guidance: dict[str, str] = Field(default_factory=dict)
    model: str | None = None
    temperature: float = 0.2
    max_turns_per_actor: int = 25
    driver: Literal["llm", "external"] = "llm"


@app.post("/v1/agent-profiles", status_code=201)
def create_profile(body: ProfileIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"profile-version:{p.project_id}:{body.name}"})
        version = (s.scalar(select(func.max(AgentProfileRow.version)).where(AgentProfileRow.project_id == p.project_id, AgentProfileRow.name == body.name)) or 0) + 1
        spec = AgentProfile(version=version, **body.model_dump())
        row = AgentProfileRow(project_id=p.project_id, name=body.name, version=version, spec=spec.model_dump())
        s.add(row)
        s.flush()
        return _cols(row)


@app.get("/v1/agent-profiles")
def list_profiles(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        return [_cols(r) for r in s.scalars(select(AgentProfileRow).where(AgentProfileRow.project_id == p.project_id).order_by(AgentProfileRow.name, AgentProfileRow.version))]


@app.get("/v1/agent-profiles/{prof_id}")
def get_profile(prof_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        return _cols(_get(s, AgentProfileRow, prof_id, p))


# --------------------------------------------------------------------------- evaluations


class EvaluationIn(BaseModel):
    world_version_id: str
    profile_ids: list[str] = Field(min_length=1)
    # Properly tested by default: every job, twice, with the default stress layer on.
    splits: list[Literal["train", "dev", "holdout"]] = Field(default_factory=lambda: ["train", "dev", "holdout"])
    scenario_ids: list[str] | None = None
    repeats: int = Field(default=2, ge=1, le=20)
    default_stress: bool = True
    budget_usd: float | None = None
    max_episode_cost_usd: float | None = None


@app.post("/v1/evaluations", status_code=202)
def create_evaluation(body: EvaluationIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        wv = _get(s, WorldVersion, body.world_version_id, p)
        if wv.status != "published":
            raise HTTPException(409, "world version is not published")
        profiles = [_get(s, AgentProfileRow, pid, p) for pid in body.profile_ids]
        q = select(Scenario).where(Scenario.world_version_id == wv.id, Scenario.status == "approved")
        q = q.where(Scenario.id.in_(body.scenario_ids)) if body.scenario_ids else q.where(Scenario.split.in_(body.splits))
        scenarios = list(s.scalars(q.order_by(Scenario.slug)))
        if not scenarios:
            raise HTTPException(422, "no approved scenarios match")
        _room(s, p.project_id, "evaluation", settings().max_active_runs, "evaluation runs")
        run = Run(project_id=p.project_id, world_version_id=wv.id, config={**body.model_dump(), "profiles": [f"{r.name}@v{r.version}" for r in profiles], "world_content_hash": wv.content_hash})
        s.add(run)
        s.flush()
        n = 0
        for rep in range(body.repeats):
            for sc in scenarios:
                for prof in profiles:
                    s.add(Episode(project_id=p.project_id, run_id=run.id, scenario_id=sc.id, profile_id=prof.id, seed=rep))
                    n += 1
        # Each shard pays one sandbox start, so more shards than half the episodes gains little.
        shards = max(1, min(settings().run_parallel, -(-n // 2)))
        left = queue.allowance_left(s, p.project_id)
        total = body.budget_usd if left is None else min(body.budget_usd or left, left)
        budget = total / shards if total is not None else None  # shards share the run's budget, not one each
        jobs = [queue.enqueue(s, project_id=p.project_id, kind="evaluation", payload={"run_id": run.id, "max_episode_cost_usd": body.max_episode_cost_usd, "default_stress": body.default_stress}, budget_usd=budget, max_attempts=5)
                for _ in range(shards)]
        run.job_id = jobs[0].id
        emit(s, project_id=p.project_id, stream=run.id, type="run.queued", summary=f"{n} episodes queued", data={"shards": shards})
        return {"run_id": run.id, "job_id": jobs[0].id, "episodes": n, "shards": shards}


@app.get("/v1/runs")
def list_runs(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        return [_cols(r) for r in s.scalars(select(Run).where(Run.project_id == p.project_id).order_by(Run.created_at.desc()).limit(100))]


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        return _cols(_get(s, Run, run_id, p))


@app.post("/v1/runs/{run_id}/commands")
def run_command(run_id: str, body: CommandIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    """A run is several shard jobs; the command goes to every shard it applies to."""
    with session() as s:
        _get(s, Run, run_id, p)
        ids = [j.id for j in queue.run_jobs(s, run_id)]
    out, refused = None, HTTPException(409, "run has no job")
    for job_id in ids:
        try:
            out = job_command(job_id, body, p)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            refused = exc
    if out is None:
        raise refused
    return out


@app.get("/v1/runs/{run_id}/episodes")
def list_episodes(run_id: str, p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    p.require("evaluator")
    with session() as s:
        _get(s, Run, run_id, p)
        rows = s.execute(
            select(Episode, Scenario.slug, Scenario.split, AgentProfileRow.name, AgentProfileRow.version)
            .join(Scenario, Scenario.id == Episode.scenario_id)
            .outerjoin(AgentProfileRow, AgentProfileRow.id == Episode.profile_id)
            .where(Episode.run_id == run_id)
            .order_by(Episode.id)
        ).all()
        return [{**_cols(e, ("state", "instance")), "scenario": slug, "split": split, "profile": f"{n}@v{v}"} for e, slug, split, n, v in rows]


@app.get("/v1/episodes/{ep_id}")
def get_episode(ep_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        e = _get(s, Episode, ep_id, p)
        actions = [_cols(a, ("request", "response")) for a in s.scalars(select(Action).where(Action.episode_id == ep_id).order_by(Action.seq))]
        messages = [_cols(m) for m in s.scalars(select(Message).where(Message.episode_id == ep_id).order_by(Message.seq))]
        sc = s.get(Scenario, e.scenario_id)
        state = e.state or {}
        return {
            **_cols(e, ("state", "instance")),
            "scenario": {"id": sc.id, "slug": sc.slug, "title": sc.spec.get("title"), "goals": sc.spec.get("goals"), "actors": sc.spec.get("actors"), "participant": {k: sc.spec.get("participant", {}).get(k) for k in ("name", "persona", "facts", "channel")}, "split": sc.split} if sc else None,
            "actions": actions,
            "messages": messages,
            "goal_version": state.get("goal_version"),
            "step": state.get("step"),
        }


class InterventionIn(BaseModel):
    kind: Literal["customer_message", "goal_change", "fault", "revoke_tool", "grant_tool"]
    text: str | None = None
    goal_version: int | None = None
    tool: str | None = None
    fault_mode: Literal["drop_response", "error", "timeout_before", "rate_limit"] | None = None
    role: str | None = None
    count: int = 1


@app.post("/v1/episodes/{ep_id}/interventions", status_code=202)
def intervene(ep_id: str, body: InterventionIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        e = _get(s, Episode, ep_id, p)
        if e.status != "running":
            raise HTTPException(409, "episode is not running")
        ev = emit(s, project_id=p.project_id, stream=e.run_id, episode_id=e.id, type="intervention.requested", summary=f"operator requested {body.kind}", data=body.model_dump(exclude_none=True))
        return {"event_id": ev.id}


# ---- bring-your-own-agent ----------------------------------------------------


@app.get("/v1/episodes/{ep_id}/observation")
def observation(ep_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        e = _get(s, Episode, ep_id, p)
        ev = s.scalars(select(Event).where(Event.stream == e.run_id, Event.episode_id == ep_id, Event.type == "external.turn").order_by(Event.id.desc())).first()
        answered = ev is not None and s.scalars(select(Event.id).where(Event.stream == e.run_id, Event.episode_id == ep_id, Event.id > ev.id,
                                                                       Event.type == "external.action.submitted").limit(1)).first() is not None
        return {"episode_status": e.status, "turn": serialize(ev) if ev else None, "awaiting_action": e.status == "running" and ev is not None and not answered}


class ExternalActionIn(BaseModel):
    actor: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=64)


@app.post("/v1/episodes/{ep_id}/actions", status_code=202)
def submit_action(ep_id: str, body: ExternalActionIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        e = s.scalars(select(Episode).where(Episode.id == ep_id, Episode.project_id == p.project_id).with_for_update()).first()
        if e is None:
            raise HTTPException(404, f"Episode {ep_id} not found")
        # Serialize with turn publication as well as concurrent submissions.
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": e.run_id})
        dup = s.scalars(select(Event).where(Event.stream == e.run_id, Event.episode_id == ep_id, Event.type == "external.action.submitted", Event.data["idempotency_key"].astext == body.idempotency_key)).first()
        if dup:
            if any(dup.data.get(k) != v for k, v in body.model_dump().items()):
                raise HTTPException(409, "idempotency key already used for a different action")
            return {"event_id": dup.id, "duplicate": True}
        if e.status != "running":
            raise HTTPException(409, "episode is not running")
        profile = s.get(AgentProfileRow, e.profile_id) if e.profile_id else None
        if profile is None or profile.spec.get("driver", "llm") != "external":
            raise HTTPException(409, "episode does not use an external agent")
        turn = s.scalars(select(Event).where(Event.stream == e.run_id, Event.episode_id == ep_id, Event.type == "external.turn").order_by(Event.id.desc())).first()
        if turn is None or turn.data.get("actor") != body.actor:
            raise HTTPException(409, "actor does not match the current external turn")
        tools = {t.get("function", {}).get("name") for t in turn.data.get("tools", [])}
        if body.tool not in tools:
            raise HTTPException(422, "tool is not offered in the current external turn")
        consumed = s.scalars(select(Event.id).where(Event.stream == e.run_id, Event.episode_id == ep_id, Event.id > turn.id, Event.type.in_(["external.action.submitted", "external.action.result"])).limit(1)).first()
        if consumed is not None:
            raise HTTPException(409, "current external turn already has an action")
        ev = emit(s, project_id=p.project_id, stream=e.run_id, episode_id=ep_id, actor_id=body.actor, type="external.action.submitted", summary=f"{body.actor} submitted {body.tool}", data=body.model_dump())
        return {"event_id": ev.id, "duplicate": False}


@app.get("/v1/episodes/{ep_id}/actions/{key}")
def action_result(ep_id: str, key: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        e = _get(s, Episode, ep_id, p)
        ev = s.scalars(select(Event).where(Event.stream == e.run_id, Event.episode_id == ep_id, Event.type == "external.action.result", Event.data["idempotency_key"].astext == key)).first()
        return {"status": "done", "result": ev.data.get("result")} if ev else {"status": "pending"}


# --------------------------------------------------------------------------- comparison


@app.get("/v1/compare")
def compare(run_a: str, run_b: str | None = None, p: Principal = Depends(principal)) -> dict[str, Any]:
    """Compares profiles within one run, or two runs on the same pinned world version."""
    with session() as s:
        a = _get(s, Run, run_a, p)
        b = _get(s, Run, run_b, p) if run_b else None
        if b and b.world_version_id != a.world_version_id:
            raise HTTPException(409, "runs use different world versions; their graders are not comparable")
        result = {"world_version_id": a.world_version_id, "world_content_hash": a.config.get("world_content_hash"), "runs": {a.id: a.summary}}
        if b:
            result["runs"][b.id] = b.summary
        return result


# --------------------------------------------------------------------------- improvement, exports, training


class ImproveIn(BaseModel):
    profile_id: str
    run_id: str  # a run on train/dev scenarios whose failures guide the revision


@app.post("/v1/improvements", status_code=202)
def improve(body: ImproveIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        _get(s, AgentProfileRow, body.profile_id, p)
        _get(s, Run, body.run_id, p)
        job = queue.enqueue(s, project_id=p.project_id, kind="improvement", payload=body.model_dump())
        return {"job_id": job.id}


class DatasetIn(BaseModel):
    run_ids: list[str] = Field(min_length=1)
    splits: list[Literal["train", "dev"]] = Field(default_factory=lambda: ["train"])
    verified_only: bool = True


@app.post("/v1/dataset-exports", status_code=202)
def dataset_export(body: DatasetIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        for rid in body.run_ids:
            _get(s, Run, rid, p)
        job = queue.enqueue(s, project_id=p.project_id, kind="dataset_export", payload=body.model_dump())
        return {"job_id": job.id}


class TrainingIn(BaseModel):
    world_version_id: str
    base_model: str = "Qwen/Qwen3-1.7B"
    rounds: int = Field(default=2, ge=1, le=6)
    rollouts_per_scenario: int = Field(default=4, ge=1, le=32)
    serve_base_url: str = "http://127.0.0.1:8001/v1"
    kaggle_gpu: Literal["NvidiaTeslaT4", "NvidiaTeslaP100"] = "NvidiaTeslaT4"
    budget_usd: float | None = None


@app.post("/v1/training-jobs", status_code=202)
def start_training(body: TrainingIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    # Weight training is not built yet; profile improvement (/v1/improvements) is the supported path.
    raise HTTPException(501, "Training a model on your practice worlds (reinforcement learning) is coming soon. Every episode already ends with a verified score from the application's database; today you can export verified episodes as a dataset with `rehearsal export`, and improve an agent's instructions with `rehearsal improve`.")
    with session() as s:
        wv = _get(s, WorldVersion, body.world_version_id, p)
        if wv.status != "published":
            raise HTTPException(409, "world version is not published")
        tj = TrainingJob(project_id=p.project_id, world_version_id=wv.id, base_model=body.base_model, config=body.model_dump())
        s.add(tj)
        s.flush()
        job = queue.enqueue(s, project_id=p.project_id, kind="training", payload={"training_job_id": tj.id}, budget_usd=body.budget_usd, max_attempts=5)
        tj.job_id = job.id
        return {"training_job_id": tj.id, "job_id": job.id}


@app.get("/v1/training-jobs")
def list_training(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        return [_cols(t) for t in s.scalars(select(TrainingJob).where(TrainingJob.project_id == p.project_id).order_by(TrainingJob.created_at.desc()))]


@app.get("/v1/training-jobs/{tj_id}")
def get_training(tj_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        return _cols(_get(s, TrainingJob, tj_id, p))


@app.post("/v1/world-versions/{wv_id}/bundle", status_code=202)
def bundle(wv_id: str, include_images: bool = False, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        wv = _get(s, WorldVersion, wv_id, p)
        if wv.status != "published":
            raise HTTPException(409, "world version is not published")
        job = queue.enqueue(s, project_id=p.project_id, kind="bundle_export", payload={"world_version_id": wv_id, "include_images": include_images})
        return {"job_id": job.id}


@app.get("/v1/artifacts")
def list_artifacts(kind: str | None = None, p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        q = select(Artifact).where(Artifact.project_id == p.project_id).order_by(Artifact.created_at.desc())
        if kind:
            q = q.where(Artifact.kind == kind)
        return [_cols(a, ("path",)) for a in s.scalars(q)]


@app.get("/v1/artifacts/{art_id}")
def get_artifact(art_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        return _cols(_get(s, Artifact, art_id, p), ("path",))


@app.get("/v1/artifacts/{art_id}/download")
def download_artifact(art_id: str, p: Principal = Depends(principal)) -> FileResponse:
    with session() as s:
        art = _get(s, Artifact, art_id, p)
        if art.kind == "private_evaluation_bundle":
            p.require("evaluator")
        path = Path(art.path)
    root = settings().artifacts_dir.resolve()
    if root not in path.resolve().parents or not path.is_file():
        raise HTTPException(404, "artifact file missing")
    return FileResponse(path, filename=path.name)


# --------------------------------------------------------------------------- dashboard

PHASE_ORDER = ["inspect", "plan", "materialize", "discover", "seed", "adapt", "author", "validate", "package"]


@app.get("/v1/dashboard")
def dashboard(p: Principal = Depends(principal)) -> dict[str, Any]:
    """Everything the overview screen needs in one call."""
    p.require("evaluator")
    pid = p.project_id
    with session() as s:
        apps = {a.id: a for a in s.scalars(select(Application).where(Application.project_id == pid, Application.removed_at.is_(None)))}
        worlds = [w for w in s.scalars(select(World).where(World.project_id == pid)) if w.application_id in apps]
        versions = list(s.scalars(select(WorldVersion).where(WorldVersion.project_id == pid).order_by(WorldVersion.version)))
        runs = list(s.scalars(select(Run).where(Run.project_id == pid).order_by(Run.created_at)))
        profiles = list(s.scalars(select(AgentProfileRow).where(AgentProfileRow.project_id == pid).order_by(AgentProfileRow.name, AgentProfileRow.version)))
        jobs = list(s.scalars(select(Job).where(Job.project_id == pid, Job.status.in_(["queued", "running", "paused"])).order_by(Job.created_at)))
        sc_counts = s.execute(
            select(Scenario.world_version_id, Scenario.split, func.count()).where(Scenario.project_id == pid, Scenario.status == "approved").group_by(Scenario.world_version_id, Scenario.split)
        ).all()
        ep_counts = dict(s.execute(select(Episode.status, func.count()).where(Episode.project_id == pid).group_by(Episode.status)).all())
        spend = s.scalar(select(func.coalesce(func.sum(Job.spent_usd), 0.0)).where(Job.project_id == pid)) or 0.0
        recent = [serialize(e) for e in s.scalars(
            select(Event).where(Event.project_id == pid, Event.type.in_([
                "world.published", "compiler.phase.completed", "compiler.repair", "run.finished", "goal.revised", "fault.injected",
                "episode.finished", "profile.proposed", "job.failed", "job.succeeded",
            ])).order_by(Event.id.desc()).limit(14)
        )]
        # say which application each milestone belongs to
        world_app = {w.id: apps[w.application_id].name for w in worlds if w.application_id in apps}
        version_app = {v.id: world_app.get(v.world_id, "") for v in versions}
        for ev in recent:
            stream = ev["stream"]
            if stream.startswith("job_"):
                jj = s.get(Job, stream)
                app_ = apps.get((jj.payload or {}).get("application_id")) if jj else None
                ev["context"] = app_.name if app_ else (version_app.get((jj.payload or {}).get("world_version_id"), "") if jj else "")
            elif stream.startswith("run_"):
                rr = s.get(Run, stream)
                ev["context"] = version_app.get(rr.world_version_id, "") if rr else ""
        live = []
        by_run: dict[str, dict[str, Any]] = {}  # a run is several shard jobs; the overview shows it once
        for j in jobs:
            shown = by_run.get(j.payload.get("run_id")) if j.kind == "evaluation" else None
            if shown is not None:
                shown["spent_usd"] = (shown["spent_usd"] or 0) + (j.spent_usd or 0)
                shown["shards"] += 1
                continue
            last = s.scalars(select(Event).where(Event.stream == j.id).order_by(Event.id.desc())).first()
            item: dict[str, Any] = {"job_id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "spent_usd": j.spent_usd, "last": last.summary if last else "", "last_event": serialize(last) if last else None}
            if j.kind == "world_build":
                app_ = apps.get(j.payload.get("application_id"))
                done = (j.checkpoint or {}).get("done", [])
                item.update({"application": app_.name if app_ else "?", "done": len(done), "phase": next((ph for ph in PHASE_ORDER if ph not in done), "package")})
            if j.kind == "evaluation":
                run = s.get(Run, j.payload.get("run_id"))
                total = s.scalar(select(func.count()).select_from(Episode).where(Episode.run_id == run.id)) if run else 0
                finished = s.scalar(select(func.count()).select_from(Episode).where(Episode.run_id == run.id, Episode.status.in_(["finished", "error"]))) if run else 0
                verified = s.scalar(select(func.count()).select_from(Episode).where(Episode.run_id == run.id, Episode.reward == 1)) if run else 0
                item.update({"run_id": run.id if run else None, "episodes": total, "finished": finished, "verified": verified, "profiles": (run.config or {}).get("profiles", []) if run else [], "shards": 1})
                by_run[j.payload.get("run_id")] = item
            if j.kind == "world_validate":
                wv = s.get(WorldVersion, j.payload.get("world_version_id"))
                q = select(func.count()).select_from(Scenario).where(Scenario.world_version_id == (wv.id if wv else None), Scenario.status != "rejected")
                if j.payload.get("scenario_ids"):
                    q = select(func.count()).select_from(Scenario).where(Scenario.id.in_(j.payload["scenario_ids"]))
                results = list(s.scalars(select(Event.summary).where(Event.stream == j.id, Event.type == "validation.result")))
                withdrawn = sum(1 for r in results if not r.endswith(": valid"))  # no longer counted by the query above
                item.update({"world_version_id": wv.id if wv else None, "world": f"{world_app.get(wv.world_id, 'world')} v{wv.version}" if wv else "world",
                             "checked": len(results), "total": (s.scalar(q) + (0 if j.payload.get("scenario_ids") else withdrawn)) if wv else 0})
            if j.kind == "improvement":
                prof = s.get(AgentProfileRow, j.payload.get("profile_id"))
                item.update({"agent": f"{prof.name} v{prof.version}" if prof else "agent", "run_id": j.payload.get("run_id")})
            live.append(item)

    counts: dict[str, dict[str, int]] = {}
    for wv_id, split, n in sc_counts:
        counts.setdefault(wv_id, {})[split] = n
    by_world_runs: dict[str, list[Run]] = {}
    for r in runs:
        by_world_runs.setdefault(r.world_version_id, []).append(r)
    world_rows = []
    for w in worlds:
        vs = [v for v in versions if v.world_id == w.id]
        published = [v for v in vs if v.status == "published"]
        latest = vs[-1] if vs else None
        current = published[-1] if published else None
        results = []
        if current:
            for r in by_world_runs.get(current.id, []):
                if r.status != "finished":
                    continue
                for prof, summ in summarize_run(r.id, fair_only=True).get("profiles", {}).items():
                    name, _, ver = prof.rpartition("@v")
                    results.append({
                        "run_id": r.id, "profile": prof, "name": name, "version": int(ver or 1), "splits": r.config.get("splits"),
                        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                        "success_rate": summ["overall"].get("success_rate"), "episodes": summ["overall"].get("finished"),
                        "overall": summ["overall"], "dev": summ.get("dev"), "holdout": summ.get("holdout"),
                    })
        world_rows.append({
            "application": apps[w.application_id].name if w.application_id in apps else w.name,
            "application_id": w.application_id,
            "notes": apps[w.application_id].notes if w.application_id in apps else "",
            "latest": {"id": latest.id, "version": latest.version, "status": latest.status, "build_job_id": latest.build_job_id} if latest else None,
            "published": {"id": current.id, "version": current.version, "tools": len(current.manifest.get("tools", [])), "roles": len(current.manifest.get("roles", [])), "scenarios": counts.get(current.id, {}), "spent_usd": (current.provenance or {}).get("spent_usd"), "repairs": sum(1 for r in (current.validation or {}).get("repairs", []) if r.get("outcome") == "repaired")} if current else None,
            "results": results[-12:],
        })
    for a in apps.values():
        if not any(w.application_id == a.id for w in worlds):
            world_rows.append({"application": a.name, "application_id": a.id, "notes": a.notes, "latest": None, "published": None, "results": []})

    chains: dict[str, list[dict[str, Any]]] = {}
    for prof in profiles:
        best = None
        for r in runs:
            summ = (r.summary or {}).get("profiles", {}).get(f"{prof.name}@v{prof.version}")
            if summ:
                best = {"run_id": r.id, "success_rate": summ["overall"].get("success_rate"), "splits": r.config.get("splits")}
        chains.setdefault(prof.name, []).append({"id": prof.id, "version": prof.version, "created_by": prof.created_by, "rationale": prof.rationale[:240], "latest": best})

    return {
        "totals": {
            "applications": len(apps),
            "worlds_published": sum(1 for v in versions if v.status == "published"),
            "scenarios": sum(n for c in counts.values() for n in c.values()),
            "episodes": ep_counts.get("finished", 0),
            "verified": sum(1 for r in runs for summ in (r.summary or {}).get("profiles", {}).values() for _ in range(summ["overall"].get("successes", 0))),
            "spend_usd": round(float(spend), 4),
        },
        "live": live,
        "worlds": world_rows,
        "agents": [{"name": n, "versions": v} for n, v in chains.items()],
        "recent": recent,
    }


@app.get("/v1/usage")
def usage(p: Principal = Depends(principal)) -> dict[str, Any]:
    """Model spend this month, the workspace allowance, and what is left of it."""
    with session() as s:
        start = queue.month_start()
        by_kind = dict(s.execute(select(Job.kind, func.coalesce(func.sum(Job.spent_usd), 0.0)).where(Job.project_id == p.project_id, Job.created_at >= start).group_by(Job.kind)).all())
        cap = settings().monthly_allowance_usd or None
        renews = (start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)).date().isoformat()
        return {"month": start.strftime("%Y-%m"), "spent_usd": round(sum(by_kind.values()), 4), "by_kind": {k: round(v, 4) for k, v in by_kind.items()},
                "allowance_usd": cap, "left_usd": None if cap is None else round(queue.allowance_left(s, p.project_id) or 0.0, 4), "renews": renews}


@app.get("/v1/pricing")
def model_pricing(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    """Billing price and market range for every configured model, with sources."""
    from .. import pricing

    cfg = settings()
    return pricing.report({"compiler": cfg.model_compiler, "agent": cfg.model_agent, "participant": cfg.model_participant, "improver": cfg.model_improver})


# --------------------------------------------------------------------------- keys & credentials


@app.get("/v1/api-keys")
def list_keys(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with session() as s:
        return [_cols(k, ("hash",)) for k in s.scalars(select(ApiKey).where(ApiKey.project_id == p.project_id))]


class KeyIn(BaseModel):
    name: str
    scopes: list[Literal["admin", "read", "write", "evaluator", "agent"]] = Field(default_factory=lambda: ["admin"], min_length=1)


@app.post("/v1/api-keys", status_code=201)
def new_key(body: KeyIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    p.require("admin")
    with session() as s:
        return {"api_key": create_key(s, p.project_id, body.name, body.scopes), "note": "shown once; store it now"}


@app.delete("/v1/api-keys/{key_id}")
def revoke_key(key_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    p.require("admin")
    with session() as s:
        k = _get(s, ApiKey, key_id, p)
        k.revoked_at = now()
        return {"revoked": k.id}


class CredentialIn(BaseModel):
    name: str
    kind: Literal["model_provider", "application", "training"]
    env_var: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")


@app.post("/v1/credentials", status_code=201)
def add_credential(body: CredentialIn, p: Principal = Depends(principal)) -> dict[str, Any]:
    """Registers a credential by reference: the runner reads it from its own environment."""
    with session() as s:
        c = Credential(project_id=p.project_id, **body.model_dump())
        s.add(c)
        s.flush()
        return _cols(c, ("encrypted_value",))


@app.get("/v1/credentials")
def list_credentials(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    import os

    with session() as s:
        return [{**_cols(c, ("encrypted_value",)), "available_on_runner": bool(c.env_var and os.environ.get(c.env_var))} for c in s.scalars(select(Credential).where(Credential.project_id == p.project_id))]


@app.delete("/v1/credentials/{cred_id}")
def delete_credential(cred_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with session() as s:
        c = _get(s, Credential, cred_id, p)
        s.delete(c)
        return {"deleted": cred_id}


# --------------------------------------------------------------------------- console


@app.middleware("http")
async def _no_cache_pages(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"  # pages change with each console build; assets are content-hashed
    return response


DOWNLOADS = Path(os.environ.get("REHEARSAL_DOWNLOADS_DIR") or settings().data_dir / "downloads")
if DOWNLOADS.is_dir():
    # the client wheel (pip wheel --no-deps -w var/downloads .), so users install the CLI from this server
    app.mount("/downloads", StaticFiles(directory=DOWNLOADS), name="downloads")

if STATIC.is_dir():
    # Next.js static export: /app/build/ -> app/build/index.html. Mounted last, so /v1 routes win.
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="console")


def write_openapi(dest: Path) -> None:
    dest.write_text(json.dumps(app.openapi(), indent=1))

