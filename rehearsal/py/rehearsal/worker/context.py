"""Job context: lease heartbeats, commands, budget, and job-stream events."""

from __future__ import annotations

import logging
import threading
from typing import Any

from .. import pricing
from ..agents import llm
from ..config import settings
from ..db import queue
from ..db.events import emit
from ..db.models import Job
from ..db.session import session

STOPPING = threading.Event()  # set when the worker is told to stop: running jobs are handed back at their next safe point

log = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    pass


class JobContext:
    def __init__(self, job: Job, worker_id: str):
        self.job_id = job.id
        self.project_id = job.project_id
        self.kind = job.kind
        self.payload = dict(job.payload)
        self.checkpoint: dict[str, Any] = dict(job.checkpoint or {})
        self.budget = job.budget_usd
        self.spent = job.spent_usd or 0.0
        self.worker_id = worker_id
        self.attempt = job.attempts
        self._stop: BaseException | None = None
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        # model calls, tokens, cost and latency per role (llm.usage), carried over from earlier attempts in the checkpoint
        self.models: dict[str, dict[str, Any]] = dict(self.checkpoint.get("_models") or {})

    # ------------------------------------------------------------------ lifecycle

    def __enter__(self) -> "JobContext":
        cfg = settings()
        self._thread.start()
        self._price_token = pricing.require_known_prices.set(
            self.budget is not None or cfg.plans or cfg.monthly_allowance_usd > 0)
        self._usage_token = llm.usage.set(self.models)
        return self

    def __exit__(self, *exc: Any) -> None:
        self._halt.set()
        self._thread.join(timeout=5)
        pricing.require_known_prices.reset(self._price_token)
        llm.usage.reset(self._usage_token)

    def _heartbeat(self) -> None:
        with session() as s:
            job = queue.heartbeat(s, self.job_id, self.worker_id, self.attempt, check_commands=False)
        if job.cancel_requested:
            raise queue.JobCancelled("cancel requested")
        if job.pause_requested:
            raise queue.JobPaused("pause requested")

    def _beat(self) -> None:
        interval = max(0.2, settings().lease_seconds / 3)
        while not self._halt.wait(interval):
            try:
                self._heartbeat()
            except (queue.JobCancelled, queue.JobPaused, queue.LeaseLost) as exc:
                self._stop = exc
            except Exception as exc:  # noqa: BLE001 - a transient DB error must not kill the job
                log.warning("heartbeat failed for %s: %s", self.job_id, exc)

    def check(self) -> None:
        """Raises at a safe point if the job was paused, cancelled, or over budget, or this worker is stopping."""
        if self._stop is not None:
            raise self._stop
        if STOPPING.is_set():
            raise queue.Handover("worker stopping")
        try:
            self._heartbeat()
        except (queue.JobCancelled, queue.JobPaused, queue.LeaseLost) as exc:
            self._stop = exc
            raise
        if self.budget is not None and self.spent >= self.budget:
            raise BudgetExceeded(f"model spend ${self.spent:.4f} exceeded budget ${self.budget:.2f}")

    # ------------------------------------------------------------------ helpers

    def log(self, type: str, summary: str, data: dict[str, Any] | None = None) -> None:
        with session() as s:
            self.owned(s)
            emit(s, project_id=self.project_id, stream=self.job_id, type=type, summary=summary, data=data or {})

    def save_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        checkpoint["_models"] = self.models  # usage by role so far, shown while the job runs and kept across attempts
        self.checkpoint = checkpoint
        with session() as s:
            queue.save_checkpoint(s, self.job_id, checkpoint, worker_id=self.worker_id, attempt=self.attempt)

    def request_pause(self, reason: str) -> None:
        """Asks for this job to pause at its next safe point, as the Pause button does, and says why."""
        with session() as s:
            job = self.owned(s)
            job.pause_requested = True
            emit(s, project_id=self.project_id, stream=self.job_id, type="job.guard", summary=reason)

    def add_cost(self, usd: float, tokens: int = 0) -> None:
        if not usd and not tokens:
            return
        with session() as s:
            job = self.owned(s)
            queue.record_spend(s, job, usd, tokens)

        self.spent += usd

    def owned(self, s: Any) -> Job:
        try:
            return queue.owned(s, self.job_id, self.worker_id, self.attempt)
        except queue.LeaseLost as exc:
            self._stop = exc
            raise
