"""Worker process: claims jobs from PostgreSQL and runs their handlers."""

from __future__ import annotations

import importlib
import logging
import os
import signal
import socket
import time
import traceback
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session

from ..db import queue
from ..db.models import Job, Run, TrainingJob, WorldVersion, now
from ..db.session import session
from .context import BudgetExceeded, JobContext

log = logging.getLogger("rehearsal.worker")

HANDLERS: dict[str, str] = {
    "world_build": "rehearsal.worker.build:handle",
    "world_validate": "rehearsal.worker.build:handle_validate",
    "evaluation": "rehearsal.worker.evaluate:handle",
    "improvement": "rehearsal.worker.improve:handle",
    "autofix": "rehearsal.worker.autofix:handle",
    "factory": "rehearsal.worker.factory:handle",
    "dataset_export": "rehearsal.worker.export:handle_dataset",
    "bundle_export": "rehearsal.worker.export:handle_bundle",
    "training": "rehearsal.training.expert_iteration:handle",
}


def _handler(kind: str) -> Callable[[JobContext], dict[str, Any]]:
    module, _, fn = HANDLERS[kind].partition(":")
    return getattr(importlib.import_module(module), fn)


def _mark_owner_failed(s: Session, job: Job, message: str, status: str = "failed") -> None:
    """Keeps domain rows consistent with a terminally failed (or cancelled) job."""
    if job.kind == "world_build":
        wv = s.get(WorldVersion, job.payload.get("world_version_id"))
        if wv and wv.status != "published":
            wv.status = status
            wv.validation = {**(wv.validation or {}), "error": message[-4000:]}
    elif job.kind == "evaluation":
        if status == "failed" and queue.release_shard(s, job):
            return  # the other shards finish the run
        run = s.get(Run, job.payload.get("run_id"))
        if run and run.status != "finished":
            run.status, run.finished_at = status, now()
    elif job.kind in ("autofix", "factory"):
        for run in s.scalars(select(Run).where(Run.job_id == job.id, Run.status != "finished")):  # its own rehearsals
            run.status, run.finished_at = status, now()
    elif job.kind == "training":
        tj = s.get(TrainingJob, job.payload.get("training_job_id"))
        if tj and tj.status not in ("succeeded",):
            tj.status, tj.finished_at = status, now()


def _run_one(worker_id: str, kinds: list[str] | None = None) -> bool:
    with session() as s:
        job = queue.claim(s, worker_id, kinds)
        if job is None:
            return False
        s.expunge(job)
    log.info("claimed %s (%s) attempt %s", job.id, job.kind, job.attempts)
    try:
        with JobContext(job, worker_id) as ctx:
            result = _handler(job.kind)(ctx)
        if isinstance(result, dict) and ctx.models:
            result = {**result, "models": ctx.models}
        with session() as s:
            row = queue.owned(s, job.id, worker_id, job.attempts)
            queue.finish(s, row, status="succeeded", result=result)  # type: ignore[arg-type]
    except queue.LeaseLost:
        log.warning("job %s claim lost; leaving replacement worker in control", job.id)
    except queue.JobPaused:
        with session() as s:
            queue.pause(s, queue.owned(s, job.id, worker_id, job.attempts))  # type: ignore[arg-type]
    except queue.JobCancelled as exc:
        with session() as s:
            row = queue.owned(s, job.id, worker_id, job.attempts)
            queue.finish(s, row, status="cancelled", error=str(exc))
            _mark_owner_failed(s, row, f"cancelled: {exc}", "cancelled")
    except BudgetExceeded as exc:
        with session() as s:
            row = queue.owned(s, job.id, worker_id, job.attempts)
            queue.finish(s, row, status="failed", error=str(exc))
            _mark_owner_failed(s, row, str(exc))
    except Exception as exc:  # noqa: BLE001
        detail = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc()[-4000:]}"
        log.error("job %s failed: %s", job.id, detail)
        with session() as s:
            row = queue.owned(s, job.id, worker_id, job.attempts)
            retryable = row.attempts < row.max_attempts and not getattr(exc, "terminal", False) and exc.__class__.__name__ not in ("BuildFailed", "SourceError")
            if retryable:
                row.status, row.lease_owner, row.lease_expires_at, row.error = "queued", None, None, detail[-8000:]
                from ..db.events import emit

                emit(s, project_id=row.project_id, stream=row.id, type="job.retrying", summary=f"attempt {row.attempts} failed: {str(exc)[:300]}; will resume from checkpoint")
            else:
                queue.finish(s, row, status="failed", error=detail)
                _mark_owner_failed(s, row, detail)
        if retryable:
            time.sleep(min(30, 2 ** job.attempts))
    return True


def sweep() -> int:
    """Removes sandboxes still recorded by jobs that ended. A paused job keeps its sandbox so it can resume; a job
    stopped or failed while no worker held it (stopped while paused, an application removed) leaves its sandbox
    running and holding memory. Returns how many were removed."""
    from sqlalchemy import or_, select

    from ..runner.runtime import InstanceRecord, WorldInstance

    removed = 0
    with session() as s:
        jobs = s.scalars(select(Job).where(Job.status.in_(("cancelled", "failed", "succeeded")),
                                           or_(Job.checkpoint.has_key("instance"), Job.checkpoint.has_key("lanes")))
                         .limit(5).with_for_update(skip_locked=True)).all()
        for job in jobs:
            ck = dict(job.checkpoint)
            for rec in [ck.pop("instance", None), *ck.pop("lanes", [])]:
                if not rec:
                    continue
                try:
                    WorldInstance(InstanceRecord.from_json(rec)).destroy()
                    removed += 1
                except Exception as exc:  # noqa: BLE001 - an unreadable record must not block the other jobs forever
                    log.warning("could not remove sandbox %s of job %s: %s", rec.get("instance_id"), job.id, exc)
            job.checkpoint = ck  # a later restart starts a fresh sandbox from the saved snapshot
            log.info("removed the sandbox of ended job %s (%s)", job.id, job.status)
    return removed


def run_one(worker_id: str, kinds: list[str] | None = None) -> bool:
    try:
        return _run_one(worker_id, kinds)
    except queue.LeaseLost:
        log.warning("claim lost during finalization; skipped stale write")
        return True


def run_worker(kinds: list[str] | None = None, once: bool = False) -> None:
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    stopping = {"flag": False}

    def stop(*_: Any) -> None:
        stopping["flag"] = True
        log.info("stopping after the current job")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    from ..db.session import engine

    log.info("worker %s started (kinds=%s, database %s)", worker_id, kinds or "all", engine().url.host or "local")
    swept, backoff = 0.0, 0.0
    while not stopping["flag"]:
        try:
            busy = run_one(worker_id, kinds)
            backoff = 0.0
        except (OperationalError, InterfaceError) as exc:
            # The database is unreachable for a moment (network blip, failover, restart). Never let that end the
            # worker: wait and try again. A job that was running resumes from its checkpoint when its lease expires.
            backoff = min(30.0, backoff * 2 or 1.0)
            log.warning("database unreachable (%s); retrying in %.0f s", str(exc).splitlines()[0][:200], backoff)
            time.sleep(backoff)
            continue
        if once and not busy:
            return
        if not busy:
            if time.time() - swept > 60:  # idle workers clean up after ended jobs
                swept = time.time()
                try:
                    sweep()
                except Exception as exc:  # noqa: BLE001 - cleanup must never stop the worker
                    log.warning("sandbox cleanup failed: %s", exc)
            time.sleep(1.0)
