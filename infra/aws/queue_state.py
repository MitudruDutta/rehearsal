"""Prints "<due> <active>": jobs a worker would claim now, and jobs a worker is running under a live lease.
Run inside the api or worker container: docker compose ... exec -T api python - < infra/aws/queue_state.py"""

from sqlalchemy import func, or_, select

from rehearsal.db.models import Job, now
from rehearsal.db.session import session

with session() as s:
    t = now()
    due = s.scalar(select(func.count()).select_from(Job).where(or_(
        (Job.status == "queued") & (Job.not_before.is_(None) | (Job.not_before <= t)),  # the same rule as the queue's claim
        (Job.status == "running") & (Job.lease_expires_at < t))))
    active = s.scalar(select(func.count()).select_from(Job).where(Job.status == "running", Job.lease_expires_at >= t))
print(due, active)
