"""PostgreSQL job queue: SKIP LOCKED claiming, leases, heartbeats, checkpoints.

A job is claimable when queued, or when running with an expired lease (its
worker died). Attempts are counted at claim time; a job whose lease expires
more than ``max_attempts`` times fails instead of looping forever. Handlers
persist a checkpoint after each completed phase and resume from it.
"""

from __future__ import annotations

from datetime import timedelta
import math
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from .. import billing
from ..config import settings
from .events import emit
from .models import Episode, Job, ModelSpend, Project, Run, TrainingJob, WorldVersion, now


class JobCancelled(Exception):
    pass


class LeaseLost(Exception):
    """This claim no longer owns the job; never finalize another claim."""


class JobPaused(Exception):
    pass


class Handover(Exception):
    """The worker is stopping (a deploy or restart): give the job back at a safe point instead of losing its lease."""


SPENDING = {"world_build", "evaluation", "improvement", "world_validate"}  # job kinds that call models on the server's keys


class AllowanceExhausted(Exception):
    pass


month_start = billing.month_start


def spend_projects(project_id: str) -> Any:
    """Hosted allowances belong to a workspace; a self-hosted cap covers the server."""
    if not settings().plans:
        return None
    org = select(Project.org_id).where(Project.id == project_id).scalar_subquery()
    return select(Project.id).where(Project.org_id == org)


def month_spend(s: Session, project_id: str) -> float:
    q = select(func.coalesce(func.sum(ModelSpend.spent_usd), 0.0)).where(ModelSpend.month == month_start().strftime("%Y-%m"))
    projects = spend_projects(project_id)
    if projects is not None:
        q = q.where(ModelSpend.project_id.in_(projects))
    return float(s.scalar(q) or 0.0)


def record_spend(s: Session, job: Job, usd: float, tokens: int = 0) -> None:
    """Caller holds the job's ownership lock; usage and its dated ledger commit together."""
    if not math.isfinite(usd) or usd < 0 or tokens < 0:
        raise ValueError("model usage must be finite and non-negative")
    job.spent_usd = (job.spent_usd or 0.0) + usd
    job.tokens = (job.tokens or 0) + tokens
    if usd:
        month = month_start().strftime("%Y-%m")
        row = s.scalars(select(ModelSpend).where(ModelSpend.job_id == job.id, ModelSpend.month == month)).first()
        if row is None:
            s.add(ModelSpend(job_id=job.id, project_id=job.project_id, month=month, spent_usd=usd))
        else:
            row.spent_usd += usd


def allowance_left(s: Session, project_id: str) -> float | None:
    """Model money this workspace can still commit this month, or None without a limit (the plan's safety net, or the
    server-wide allowance on self-hosted servers). The unspent budgets of jobs still in progress are already
    committed, so two jobs cannot both count on the same dollars."""
    cap = billing.allowance(s, project_id)
    if cap is None:
        return None
    q = select(Job.budget_usd, Job.spent_usd).where(Job.status.in_(("queued", "running", "paused")), Job.budget_usd.is_not(None))
    projects = spend_projects(project_id)
    if projects is not None:
        q = q.where(Job.project_id.in_(projects))
    active = s.execute(q).all()
    reserved = sum(max(0.0, b - (sp or 0.0)) for b, sp in active)
    return max(0.0, cap - month_spend(s, project_id) - reserved)


def reserve(s: Session, project_id: str, kind: str, budget_usd: float | None) -> float | None:
    if budget_usd is not None and (not math.isfinite(budget_usd) or budget_usd < 0):
        raise ValueError("budget must be finite and non-negative")
    if kind not in SPENDING:
        return budget_usd
    billing.lock(s, project_id)
    if not settings().plans and settings().monthly_allowance_usd:
        # Distinct organizations share this cap. Organization locks alone cannot serialize it.
        s.execute(text("SELECT pg_advisory_xact_lock(731894211)"))
    if (left := allowance_left(s, project_id)) is not None:
        if left <= 0:
            raise AllowanceExhausted(
                f"This workspace has used its ${billing.allowance(s, project_id) or 0:.2f} model allowance for this month, including jobs still running. "
                "It renews on the 1st; until then, stop a running job or wait for one to finish."
            )
        if budget_usd is None:
            budget_usd = billing.DEFAULT_BUDGET_USD.get(kind)
        budget_usd = left if budget_usd is None else min(budget_usd, left)  # the job stops itself at this spend
    return budget_usd


def enqueue(s: Session, *, project_id: str, kind: str, payload: dict[str, Any], priority: int = 0, max_attempts: int = 3,
            budget_usd: float | None = None, not_before: Any = None) -> Job:
    budget_usd = reserve(s, project_id, kind, budget_usd)
    job = Job(project_id=project_id, kind=kind, payload=payload, priority=priority, max_attempts=max_attempts, budget_usd=budget_usd, not_before=not_before)
    s.add(job)
    s.flush()
    emit(s, project_id=project_id, stream=job.id, type="job.queued", summary=f"{kind} queued", data={"kind": kind})
    return job


def claim(s: Session, worker_id: str, kinds: list[str] | None = None) -> Job | None:
    lease = timedelta(seconds=settings().lease_seconds)
    q = (
        select(Job)
        .where(or_((Job.status == "queued") & (Job.not_before.is_(None) | (Job.not_before <= now())),
                   (Job.status == "running") & (Job.lease_expires_at < now())))
        .order_by(Job.priority.desc(), Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if kinds:
        q = q.where(Job.kind.in_(kinds))
    while True:
        job = s.scalars(q).first()
        if job is None:
            return None
        resumed = job.status == "running"
        if job.attempts < job.max_attempts:
            break
        job.status, job.error, job.finished_at = "failed", (job.error or "") + "\nlease expired too many times", now()
        emit(s, project_id=job.project_id, stream=job.id, type="job.failed", summary="gave up after repeated worker loss")
        job.lease_owner, job.lease_expires_at = None, None
        if job.kind != "evaluation" or not release_shard(s, job):
            _fail_owner(s, job)
        s.flush()
    job.status, job.lease_owner, job.lease_expires_at = "running", worker_id, now() + lease
    job.attempts += 1
    job.started_at = job.started_at or now()
    emit(
        s,
        project_id=job.project_id,
        stream=job.id,
        type="job.resumed" if resumed or job.checkpoint else "job.started",
        summary=f"{'resumed from checkpoint' if job.checkpoint else 'started'} by {worker_id} (attempt {job.attempts})",
        data={"worker": worker_id, "attempt": job.attempts, "checkpoint": sorted(job.checkpoint)},
    )
    return job


def heartbeat(s: Session, job_id: str, worker_id: str, attempt: int | None = None, *, check_commands: bool = True) -> Job:
    """Extends the lease; raises if this worker lost it, or a command arrived."""
    lease = timedelta(seconds=settings().lease_seconds)
    res = s.execute(
        update(Job)
        .where(Job.id == job_id, Job.lease_owner == worker_id, Job.status == "running", Job.lease_expires_at > now(),
               *([Job.attempts == attempt] if attempt is not None else []))
        .values(lease_expires_at=now() + lease)
        .returning(Job.cancel_requested, Job.pause_requested)
    ).first()
    if res is None:
        raise LeaseLost("lease lost")
    if check_commands and res.cancel_requested:
        raise JobCancelled("cancel requested")
    if check_commands and res.pause_requested:
        raise JobPaused("pause requested")
    return s.get(Job, job_id)  # type: ignore[return-value]


def save_checkpoint(s: Session, job_id: str, checkpoint: dict[str, Any], *, worker_id: str | None = None, attempt: int | None = None) -> None:
    if worker_id is not None:
        owned(s, job_id, worker_id, attempt)
    s.execute(update(Job).where(Job.id == job_id).values(checkpoint=checkpoint))


def finish(s: Session, job: Job, *, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    job.status, job.finished_at, job.lease_owner, job.lease_expires_at = status, now(), None, None
    if result is not None:
        job.result = result
    if error is not None:
        job.error = error[-8000:]
    emit(s, project_id=job.project_id, stream=job.id, type=f"job.{status}", summary=(error or status)[:500], data=result or {})


def pause(s: Session, job: Job) -> None:
    job.status, job.lease_owner, job.lease_expires_at, job.pause_requested = "paused", None, None, False
    job.attempts = max(0, job.attempts - 1)  # pausing is not a failed attempt
    emit(s, project_id=job.project_id, stream=job.id, type="job.paused", summary="paused; resumes from last checkpoint")


def hand_back(s: Session, job: Job) -> None:
    """Returns a job to the queue from a stopping worker. Like a pause, it is not a failed attempt, so restarting workers
    during a deploy never uses up a build's attempts."""
    job.status, job.lease_owner, job.lease_expires_at = "queued", None, None
    job.attempts = max(0, job.attempts - 1)
    emit(s, project_id=job.project_id, stream=job.id, type="job.handed_back", summary="the worker stopped; another worker resumes from the last checkpoint")


def command(s: Session, job: Job, cmd: str) -> None:
    if cmd == "pause" and job.status in ("queued", "running"):
        if job.status == "queued":
            job.status = "paused"
        else:
            job.pause_requested = True
    elif cmd == "resume" and job.status == "paused":
        job.status, job.pause_requested = "queued", False
    elif cmd == "retry" and job.status in ("failed", "cancelled"):  # continue from the last checkpoint
        if job.kind in SPENDING:
            remaining = None if job.budget_usd is None else max(0.0, job.budget_usd - (job.spent_usd or 0.0))
            if remaining == 0:
                raise AllowanceExhausted("This job already used its budget; start a new job with a new budget.")
            remaining = reserve(s, job.project_id, job.kind, remaining)
            job.budget_usd = None if remaining is None else (job.spent_usd or 0.0) + remaining
        job.status, job.attempts, job.error, job.finished_at = "queued", 0, None, None
        job.cancel_requested = job.pause_requested = False  # a stop sent before the failure must not cancel the retry
    elif cmd == "stop" and job.status in ("queued", "running", "paused"):
        if job.status == "running":
            job.cancel_requested = True
        else:
            job.status, job.finished_at = "cancelled", now()
            _fail_owner(s, job, "cancelled")
    else:
        raise ValueError(f"cannot {cmd} a {job.status} job")
    emit(s, project_id=job.project_id, stream=job.id, type="job.command", summary=f"{cmd} requested", data={"command": cmd})


def owned(s: Session, job_id: str, worker_id: str, attempt: int | None = None) -> Job:
    """Lock the current claim while its domain/checkpoint writes commit."""
    job = s.scalars(select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True)).first()
    if (job is None or job.status != "running" or job.lease_owner != worker_id
            or (attempt is not None and job.attempts != attempt)
            or job.lease_expires_at is None or job.lease_expires_at <= now()):
        raise LeaseLost("lease lost")
    return job


def run_jobs(s: Session, run_id: str) -> list[Job]:
    """The evaluation shards of one run."""
    return list(s.scalars(select(Job).where(Job.kind == "evaluation", Job.payload["run_id"].astext == run_id).order_by(Job.created_at)))


def release_shard(s: Session, job: Job) -> bool:
    """A failed shard hands its unfinished episodes back. Returns whether another shard is still there to take them.

    The run row is the lock shared with the shard's own exit decision (evaluate._settle), so a shard cannot leave
    in the instant another one hands work back."""
    run_id = job.payload.get("run_id")
    s.scalars(select(Run).where(Run.id == run_id).with_for_update()).first()
    s.execute(update(Episode).where(Episode.job_id == job.id, Episode.status.in_(("pending", "running"))).values(job_id=None))
    return any(j.id != job.id and j.status in ("queued", "running", "paused") and not (j.checkpoint or {}).get("shard_done") for j in run_jobs(s, run_id))


def _fail_owner(s: Session, job: Job, status: str = "failed") -> None:
    if job.kind == "world_build":
        row = s.get(WorldVersion, job.payload.get("world_version_id"))
        if row is not None and row.status != "published":
            row.status = status
    elif job.kind == "evaluation":
        row = s.get(Run, job.payload.get("run_id"))
        if row is not None and row.status != "finished":
            row.status, row.finished_at = status, now()
    elif job.kind in ("autofix", "factory"):
        for row in s.scalars(select(Run).where(Run.job_id == job.id, Run.status != "finished")):
            row.status, row.finished_at = status, now()
    elif job.kind == "training":
        row = s.get(TrainingJob, job.payload.get("training_job_id"))
        if row is not None and row.status != "succeeded":
            row.status, row.finished_at = status, now()
