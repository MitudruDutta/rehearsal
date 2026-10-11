"""Plans, plan limits, and billing through Dodo Payments.

A workspace (organization) is on one plan. The plan sets how many applications it keeps, how many world builds and
episodes it may start each calendar month (UTC), how many sandboxes run its evaluations at once, and a monthly
model-spend safety net. Every limit is checked in the API under a lock on the organization row, so two requests
(even on two API replicas) cannot both take the last episode.

Which plan applies, in order: a plan an operator admin set for the workspace; ``internal`` (no limits) for a
workspace owned by an admin; the plan of an active Dodo Payments subscription; otherwise ``free``.

Dodo Payments is the source of truth for subscriptions and top-up payments. Webhooks and the return from checkout
only trigger ``sync``, which reads the customer's subscriptions and payments back from the Dodo API. Events that
arrive twice, late, or out of order therefore cannot leave a workspace on the wrong plan.

With ``REHEARSAL_PLANS=off`` (the default, for self-hosted servers) none of this applies: there are no plan limits,
and the server-wide ``REHEARSAL_MONTHLY_ALLOWANCE_USD`` is the only spend limit.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, not_, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .db.models import Application, Episode, Job, Membership, Organization, PlanCredit, Project, Run, User, WorldVersion, now


@dataclass(frozen=True)
class Plan:
    name: str
    title: str
    applications: int | None  # None = no limit
    builds: int | None  # world builds a month (or ever, for builds_ever)
    episodes: int | None  # episodes a month
    sandboxes: int | None  # evaluation sandboxes at once, and validation lanes of a build
    active_builds: int | None  # builds in progress at once
    build_budget_usd: float | None  # model-spend cap of one build
    allowance_usd: float | None  # model-spend safety net a month (covers re-checks and improvements too)
    builds_ever: bool = False  # the free plan's one build is for good, not a month
    quiet_hours: bool = False  # evaluations start only in the quiet window
    top_ups: bool = False  # may buy extra builds and episodes for the month


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 1, 1, 40, 1, 1, 5.0, 8.0, builds_ever=True, quiet_hours=True),
    "pro": Plan("pro", "Pro", 3, 2, 750, 2, 1, None, 60.0, top_ups=True),
    "team": Plan("team", "Team", 20, 8, 3000, 4, 2, None, 250.0, top_ups=True),
    "enterprise": Plan("enterprise", "Enterprise", 100, 40, 20000, 8, 4, None, 1500.0, top_ups=True),
    "internal": Plan("internal", "Internal", None, None, None, 8, None, None, None, top_ups=True),
}
RANK = {"free": 0, "pro": 1, "team": 2, "enterprise": 3, "internal": 4}
LIMIT_FIELDS = ("applications", "builds", "episodes", "sandboxes", "active_builds", "build_budget_usd", "allowance_usd")

# What can be bought. Subscriptions set the plan; top-ups add to this month's builds or episodes.
ITEMS: dict[str, dict[str, Any]] = {
    "pro_monthly": {"plan": "pro", "interval": "month"},
    "pro_yearly": {"plan": "pro", "interval": "year"},
    "team_monthly": {"plan": "team", "interval": "month"},
    "team_yearly": {"plan": "team", "interval": "year"},
    "episodes_1000": {"credit": "episodes", "per_unit": 1000, "usd": 20.0},  # usd: extra model allowance it brings
    "build_1": {"credit": "builds", "per_unit": 1, "usd": 10.0},
}
PAID = ("active", "past_due")  # past_due: a renewal failed and Dodo's grace period is running; access stays
STALE_AFTER = timedelta(days=3)  # a paid period this long over without news from Dodo no longer counts as paid
# Spend caps for jobs started without one on a plan with a model-spend safety net, so one job cannot reserve the whole
# month's allowance and block every other job while it runs. Measured: builds $1.70-8.84, episodes $0.016-0.018.
DEFAULT_BUDGET_USD = {"world_build": 20.0, "world_validate": 3.0, "improvement": 2.0}
EPISODE_BUDGET_USD = 0.06


class PlanLimit(Exception):
    """A request goes over the workspace's plan. ``status`` is 402 for a used-up allowance, 429 for capacity in use."""

    def __init__(self, detail: str, status: int = 402):
        super().__init__(detail)
        self.status = status


class BillingError(Exception):
    def __init__(self, detail: str, status: int = 502):
        super().__init__(detail)
        self.status = status


# --------------------------------------------------------------------------- calendar


def month_start(at: datetime | None = None) -> datetime:
    return (at or now()).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(at: datetime | None = None) -> datetime:
    start = month_start(at)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


def quiet_start(at: datetime | None = None) -> datetime | None:
    """When the next quiet window starts, or None inside it. The window is REHEARSAL_QUIET_HOURS_UTC (HH:MM-HH:MM, UTC)
    and may cross midnight."""
    at = at or now()
    a, b = settings().quiet_hours_utc.split("-")
    start, end = (at.replace(hour=int(x[:2]), minute=int(x[3:5]), second=0, microsecond=0) for x in (a, b))
    t = at.replace(second=0, microsecond=0)
    inside = start <= t < end if start <= end else (t >= start or t < end)
    if inside:
        return None
    return start if start > at else start + timedelta(days=1)


# --------------------------------------------------------------------------- who and which plan


def is_admin(user: User | None) -> bool:
    """Operator admins: REHEARSAL_ADMIN_EMAILS, and only with a Google-verified sign-in, never a self-chosen password."""
    return bool(user and user.google_sub and user.email.lower() in settings().admin_emails)


def org_of(s: Session, project_id: str) -> Organization:
    return s.scalars(select(Organization).join(Project, Project.org_id == Organization.id).where(Project.id == project_id)).one()


def lock(s: Session, project_id: str) -> Organization:
    """Serializes limit checks of one workspace across requests and API replicas (released at commit). A paid period
    that ended without news from Dodo (a lost webhook) is re-read first, so the plan is never stale by more than that."""
    org = org_of(s, project_id)
    s.refresh(org, with_for_update=True)
    b = org.billing or {}
    if billing_enabled() and b.get("status") in PAID and _ended(b) and _when(b.get("synced_at")) < now() - timedelta(minutes=10):
        try:
            sync(s, org)
        except BillingError:
            pass  # Dodo unreachable: the grace period below still applies
    return org


def _when(iso: Any) -> datetime:
    try:
        value = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return value if value.tzinfo else value.replace(tzinfo=now().tzinfo)
    except ValueError:
        return datetime.min.replace(tzinfo=now().tzinfo)


def _ended(b: dict[str, Any]) -> bool:
    return bool(b.get("period_end")) and _when(b["period_end"]) < now()


def paid(b: dict[str, Any]) -> bool:
    """A subscription that Dodo says is paid, and whose period did not end more than STALE_AFTER ago. During Dodo's
    grace period (past_due) access lasts until past_due_ends_at, which only webhooks carry."""
    if b.get("status") not in PAID:
        return False
    if b.get("status") == "past_due" and b.get("past_due_ends_at"):
        return now() < _when(b["past_due_ends_at"])
    return not (b.get("period_end") and _when(b["period_end"]) + STALE_AFTER < now())


def owner(s: Session, org: Organization) -> User | None:
    return s.scalars(select(User).join(Membership, Membership.user_id == User.id)
                     .where(Membership.org_id == org.id, Membership.role == "owner").order_by(Membership.created_at)).first()


def plan_of(s: Session, org: Organization) -> Plan:
    cfg = settings()
    if not cfg.plans:
        return Plan("self_hosted", "Self-hosted", None, None, None, None, None, None, cfg.monthly_allowance_usd or None)
    billing = org.billing or {}
    if org.plan_override in PLANS:
        base = PLANS[org.plan_override]
    elif is_admin(owner(s, org)):
        base = PLANS["internal"]
    elif paid(billing) and billing.get("plan") in PLANS:
        base = PLANS[billing["plan"]]
    else:
        base = PLANS["free"]
    custom = {k: v for k, v in (org.limits_override or {}).items() if k in LIMIT_FIELDS}
    return replace(base, **custom) if custom else base


# --------------------------------------------------------------------------- usage


def _projects(org_id: str) -> Any:
    return select(Project.id).where(Project.org_id == org_id)


def credits(s: Session, org_id: str, kind: str, at: datetime | None = None) -> int:
    month = month_start(at).strftime("%Y-%m")
    return int(s.scalar(select(func.coalesce(func.sum(PlanCredit.quantity), 0)).where(PlanCredit.org_id == org_id, PlanCredit.kind == kind, PlanCredit.month == month)) or 0)


def usage(s: Session, org: Organization, plan: Plan | None = None) -> dict[str, int]:
    """What the workspace uses now. Episodes count from the moment a run is queued; episodes a stopped or failed run
    never started are not counted. A failed build is retried for free (retry continues the same build)."""
    plan = plan or plan_of(s, org)
    projects = _projects(org.id)
    start = month_start()
    builds_since = None if plan.builds_ever else start
    builds = select(func.count()).select_from(WorldVersion).where(WorldVersion.project_id.in_(projects))
    episodes = (select(func.count()).select_from(Episode).join(Run, Run.id == Episode.run_id)
                .where(Run.project_id.in_(projects), Run.created_at >= start,
                       not_((Episode.status == "pending") & Run.status.in_(("failed", "cancelled")))))
    active = Job.project_id.in_(projects) & Job.status.in_(("queued", "running", "paused"))
    return {
        "applications": s.scalar(select(func.count()).select_from(Application).where(Application.project_id.in_(projects), Application.removed_at.is_(None))) or 0,
        "builds": s.scalar(builds if builds_since is None else builds.where(WorldVersion.created_at >= builds_since)) or 0,
        "episodes": s.scalar(episodes) or 0,
        "active_builds": s.scalar(select(func.count()).select_from(Job).where(active, Job.kind == "world_build")) or 0,
        "sandboxes": s.scalar(select(func.count()).select_from(Job).where(active, Job.kind == "evaluation")) or 0,
        "extra_builds": credits(s, org.id, "builds"),
        "extra_episodes": credits(s, org.id, "episodes"),
    }


def allowance(s: Session, project_id: str) -> float | None:
    """This month's model-spend safety net of the project's workspace, with what top-ups add."""
    org = org_of(s, project_id)
    plan = plan_of(s, org)
    if plan.allowance_usd is None:
        return None
    if not settings().plans:
        return plan.allowance_usd
    return plan.allowance_usd + credits(s, org.id, "episodes") / 1000 * ITEMS["episodes_1000"]["usd"] + credits(s, org.id, "builds") * ITEMS["build_1"]["usd"]


# --------------------------------------------------------------------------- limit checks (call inside the request's transaction)


def _more(plan: Plan) -> str:
    if plan.name == "free":
        return " Upgrade to Pro on the Billing page for more."
    if plan.top_ups:
        return " Add a top-up on the Billing page, or move to a bigger plan."
    return ""


def application_room(s: Session, project_id: str) -> int | None:
    """How many more applications the workspace's plan allows; None when it has no limit. Locks the workspace."""
    org = lock(s, project_id)
    plan = plan_of(s, org)
    return None if plan.applications is None else plan.applications - usage(s, org, plan)["applications"]


def check_application(s: Session, project_id: str, adding: int = 1) -> None:
    org = lock(s, project_id)
    plan = plan_of(s, org)
    if plan.applications is None:
        return
    have = usage(s, org, plan)["applications"]
    if have + adding > plan.applications:
        raise PlanLimit(f"The {plan.title} plan keeps {plan.applications} application{'s' * (plan.applications != 1)}, and this workspace has {have}. "
                        f"Remove one on the Applications page first.{_more(plan)}")


@dataclass
class BuildGrant:
    budget_usd: float | None
    lanes: int | None


def check_build(s: Session, project_id: str, budget_usd: float | None) -> BuildGrant:
    org = lock(s, project_id)
    plan = plan_of(s, org)
    used = usage(s, org, plan)
    if plan.active_builds is not None and used["active_builds"] >= plan.active_builds:
        raise PlanLimit(f"The {plan.title} plan runs {plan.active_builds} world build{'s' * (plan.active_builds != 1)} at a time, and one is in progress. "
                        "Wait for it to finish, or stop it.", status=429)
    if plan.builds is not None:
        allowed = plan.builds + used["extra_builds"]
        if used["builds"] >= allowed:
            when = "" if plan.builds_ever else f" this month (renews {next_month():%d %b})"
            raise PlanLimit(f"This workspace has used its {allowed} world build{'s' * (allowed != 1)}{when}. "
                            f"A failed build can still be restarted from its page.{_more(plan)}")
    cap = plan.build_budget_usd
    return BuildGrant(cap if budget_usd is None else (budget_usd if cap is None else min(budget_usd, cap)), plan.sandboxes)


@dataclass
class EvaluationGrant:
    sandboxes: int | None  # sandboxes free for this run (None = no workspace cap)
    not_before: datetime | None  # free plan: when the quiet window opens


def check_evaluation(s: Session, project_id: str, episodes: int) -> EvaluationGrant:
    org = lock(s, project_id)
    plan = plan_of(s, org)
    used = usage(s, org, plan)
    if plan.episodes is not None:
        left = plan.episodes + used["extra_episodes"] - used["episodes"]
        if episodes > left:
            raise PlanLimit(f"This run needs {episodes} episodes and the workspace has {max(0, left)} left this month (renews {next_month():%d %b}). "
                            f"Run fewer: choose one split, fewer jobs, or one repeat.{_more(plan)}")
    free = None
    if plan.sandboxes is not None:
        free = plan.sandboxes - used["sandboxes"]
        if free <= 0:
            raise PlanLimit(f"All {plan.sandboxes} sandbox{'es' * (plan.sandboxes != 1)} of the {plan.title} plan are in use by another run. "
                            "Wait for it to finish, or stop it.", status=429)
    return EvaluationGrant(free, quiet_start() if plan.quiet_hours else None)


def check_retry(s: Session, project_id: str, job: Job) -> Any:
    """A stopped or failed evaluation shard that is restarted brings its run's unstarted episodes back, and takes a
    sandbox again: both count against the plan as if the run were new. Returns the job's new not_before."""
    if job.kind not in ("evaluation", "world_build"):
        return job.not_before
    org = lock(s, project_id)
    plan = plan_of(s, org)
    used = usage(s, org, plan)
    if job.kind == "world_build":
        if plan.active_builds is not None and used["active_builds"] >= plan.active_builds:
            raise PlanLimit(f"All {plan.active_builds} build slots of the {plan.title} plan are in use.", 429)
        if plan.build_budget_usd is not None:
            job.budget_usd = min(job.budget_usd, plan.build_budget_usd) if job.budget_usd is not None else plan.build_budget_usd
        job.payload = {**job.payload, "options": {**job.payload.get("options", {}), "parallel": plan.sandboxes or 0}}
        return job.not_before
    run = s.get(Run, job.payload.get("run_id"))
    if run is not None and run.status in ("failed", "cancelled") and plan.episodes is not None:
        back = s.scalar(select(func.count()).select_from(Episode).where(Episode.run_id == run.id, Episode.status == "pending")) or 0
        left = plan.episodes + used["extra_episodes"] - used["episodes"]
        if back > left:
            raise PlanLimit(f"Restarting this run brings back {back} episodes it never started, and the workspace has {max(0, left)} left this month "
                            f"(renews {next_month():%d %b}).{_more(plan)}")
    if plan.sandboxes is not None and used["sandboxes"] >= plan.sandboxes:
        raise PlanLimit(f"All {plan.sandboxes} sandbox{'es' * (plan.sandboxes != 1)} of the {plan.title} plan are in use. Wait for a run to finish, or stop it.", status=429)
    return quiet_start() if plan.quiet_hours else None


# --------------------------------------------------------------------------- summary for the console


def summary(s: Session, org: Organization) -> dict[str, Any]:
    plan = plan_of(s, org)
    used = usage(s, org, plan)
    billing = org.billing or {}
    return {
        "plan": asdict(plan), "usage": used, "month": month_start().strftime("%Y-%m"), "renews": next_month().date().isoformat(),
        "quiet_hours_utc": settings().quiet_hours_utc if plan.quiet_hours else None, "next_quiet_start": (q.isoformat() if plan.quiet_hours and (q := quiet_start()) else None),
        "override": org.plan_override, "limits_override": org.limits_override or {},
        "subscription": {**{k: billing.get(k) for k in ("status", "plan", "interval", "period_end", "cancel_at_period_end")}, "paid": paid(billing)} if billing.get("subscription_id") else None,
        "billing_enabled": billing_enabled(), "items": sorted(k for k in ITEMS if settings().dodo_products.get(k)),
        "plans": {k: asdict(v) for k, v in PLANS.items() if k != "internal"},
    }


# --------------------------------------------------------------------------- Dodo Payments


def billing_enabled() -> bool:
    cfg = settings()
    return bool(cfg.plans and cfg.dodo_api_key)


def _dodo(method: str, path: str, **kw: Any) -> Any:
    cfg = settings()
    live = cfg.dodo_environment == "live_mode"  # anything else is test mode, so a typo can never charge real cards
    key = cfg.dodo_api_key or ""
    if (live and key.startswith("dodo_test_")) or (not live and key.startswith("dodo_live_")):
        raise BillingError(f"DODO_PAYMENTS_API_KEY is a {'test' if live else 'live'} key but DODO_PAYMENTS_ENVIRONMENT is {cfg.dodo_environment}.", 503)
    base = "https://live.dodopayments.com" if live else "https://test.dodopayments.com"
    try:
        # short timeout: a webhook re-reads several resources and Dodo gives up on a delivery after 30 seconds
        r = httpx.request(method, base + path, headers={"Authorization": f"Bearer {key}"}, timeout=8, **kw)
    except httpx.HTTPError as exc:
        raise BillingError(f"Could not reach Dodo Payments ({type(exc).__name__}); try again in a minute.") from exc
    if r.status_code >= 400:
        raise BillingError(f"Dodo Payments refused the request ({r.status_code}): {r.text[:300]}", 502 if r.status_code >= 500 else 409)
    return r.json() if r.content else {}


def _product(item: str) -> str:
    pid = settings().dodo_products.get(item)
    if item not in ITEMS or not pid:
        raise BillingError(f"{item} is not for sale on this server", 422)
    return pid


def _customer(s: Session, org: Organization) -> str:
    billing = dict(org.billing or {})
    if not billing.get("customer_id"):
        user = owner(s, org)
        c = _dodo("POST", "/customers", json={"email": user.email if user else f"{org.id}@invalid.example", "name": org.name, "metadata": {"org_id": org.id}})
        billing["customer_id"] = c["customer_id"]
        org.billing = billing
    return billing["customer_id"]


def checkout(s: Session, org: Organization, item: str, quantity: int = 1) -> str:
    """A hosted Dodo checkout page for a plan or a top-up. Returns its URL."""
    if not billing_enabled():
        raise BillingError("Billing is not set up on this server.", 503)
    product = _product(item)
    plan = plan_of(s, org)
    if "plan" in ITEMS[item]:
        status = (org.billing or {}).get("status")
        if status in PAID:
            raise BillingError("This workspace already has a subscription: change its plan instead.", 409)
        if status in ("on_hold", "paused"):  # a second subscription would charge twice once the first one recovers
            raise BillingError("This workspace's subscription is on hold. Update the payment method in the payment portal to resume it.", 409)
        quantity = 1
    elif not plan.top_ups:
        raise BillingError("Top-ups are for paid plans. Upgrade to Pro first.", 409)
    body = {"product_cart": [{"product_id": product, "quantity": max(1, min(quantity, 50))}], "customer": {"customer_id": _customer(s, org)},
            "return_url": f"{settings().public_url}/app/billing/?checkout=done", "metadata": {"org_id": org.id, "item": item}}
    return _dodo("POST", "/checkouts", json=body)["checkout_url"]


def change_plan(s: Session, org: Organization, item: str) -> None:
    billing = org.billing or {}
    if "plan" not in ITEMS.get(item, {}):
        raise BillingError(f"{item} is not a plan", 422)
    if billing.get("status") == "past_due":  # Dodo rejects plan changes until the failed renewal is paid
        raise BillingError("The last renewal payment failed. Update the payment method in the payment portal, then change the plan.", 409)
    if billing.get("status") != "active":
        raise BillingError("No active subscription to change; choose a plan to subscribe.", 409)
    # prevent_change: if the charge fails, the workspace stays on its current plan instead of going on hold
    _dodo("POST", f"/subscriptions/{billing['subscription_id']}/change-plan",
          json={"product_id": _product(item), "quantity": 1, "proration_billing_mode": "prorated_immediately", "on_payment_failure": "prevent_change"})
    sync(s, org)


def portal(s: Session, org: Organization) -> str:
    cid = (org.billing or {}).get("customer_id")
    if not billing_enabled() or not cid:
        raise BillingError("This workspace has no billing account yet.", 409)
    return _dodo("POST", f"/customers/{cid}/customer-portal/session", params={"return_url": f"{settings().public_url}/app/billing/"})["link"]


def _item_of(product_id: str | None) -> str | None:
    return next((k for k, v in settings().dodo_products.items() if v and v == product_id), None)


def _all_dodo(path: str, **params: Any):
    """Dodo pages start at zero and contain at most 100 items."""
    seen: set[str] = set()
    for page in range(1000):
        items = _dodo("GET", path, params={**params, "page_size": 100, "page_number": page}).get("items", [])
        fresh = 0
        for item in items:
            identity = str(item.get("payment_id") or item.get("subscription_id") or "")
            if identity and identity not in seen:
                fresh += 1
                seen.add(identity)
                yield item
        if len(items) < 100:
            return
        if not fresh:
            raise BillingError("Dodo repeated a billing page; synchronization was not applied.")
    raise BillingError("Dodo billing history exceeds the supported pagination range.")


def _payment_credits(s: Session, org: Organization | None, payment_id: str) -> list[PlanCredit]:
    ref = f"dodo:{payment_id}"
    query = select(PlanCredit).where(or_(PlanCredit.ref == ref, PlanCredit.ref.startswith(ref + ":", autoescape=True)))
    if org is not None:
        query = query.where(PlanCredit.org_id == org.id)
    return list(s.scalars(query))


def _retained_units(full: dict[str, Any], quantities: dict[str, int]) -> dict[str, int]:
    if full.get("refund_status") == "full":
        return dict.fromkeys(quantities, 0)
    if full.get("refund_status") != "partial":
        return quantities
    items = _dodo("GET", f"/payments/{full['payment_id']}/line-items").get("items", [])
    if len(items) != len(quantities):
        raise BillingError("Refund invoice lines cannot be matched one-to-one to products; the line and product counts differ.")
    result = {}
    used: set[int] = set()
    for pid, quantity in quantities.items():
        if len(quantities) == 1 and len(items) == 1:
            matches = [0]
        else:
            name = _dodo("GET", f"/products/{pid}").get("name")
            matches = [index for index, item in enumerate(items) if name and item.get("name") == name]
        if len(matches) != 1 or matches[0] in used:
            # Invoice lines expose no product id. Never guess which entitlement
            # was refunded if names cannot establish a unique correspondence.
            raise BillingError("Refund invoice lines cannot be matched uniquely to products; reconcile their names in Dodo.")
        used.add(matches[0])
        line = items[matches[0]]
        remaining = int(line["refundable_amount"])
        if remaining < 0:
            raise BillingError("Dodo returned a negative refundable amount.")
        # A partial refund keeps access until the whole invoice line is refunded.
        result[pid] = 0 if remaining == 0 else quantity
    return result


def _sync_payment(s: Session, org: Organization, full: dict[str, Any]) -> None:
    if full.get("status") != "succeeded" or (full.get("metadata") or {}).get("org_id", org.id) != org.id:
        return
    recorded = _payment_credits(s, None, full["payment_id"])
    if any(credit.org_id != org.id for credit in recorded):
        return
    cart = full.get("product_cart") or []
    quantities: dict[str, int] = {}
    for line in cart:
        pid = line.get("product_id")
        if pid:
            quantities[pid] = quantities.get(pid, 0) + int(line.get("quantity") or 1)
    retained = _retained_units(full, quantities)
    existing = {credit.ref: credit for credit in recorded}
    paid_at = _when(full.get("created_at") or now().isoformat())
    ref = f"dodo:{full['payment_id']}"
    for pid, units in retained.items():
        item = ITEMS.get(_item_of(pid) or "", {})
        if "credit" not in item:
            continue
        key = ref if len(cart) == 1 else f"{ref}:{pid}"
        credit = existing.get(key)
        quantity = item["per_unit"] * units
        if credit is None:
            s.add(PlanCredit(org_id=org.id, kind=item["credit"], quantity=quantity,
                            month=month_start(paid_at).strftime("%Y-%m"), ref=key,
                            note=f"top-up {_item_of(pid)} x{quantities[pid]}"))
        elif full.get("refund_status"):
            credit.quantity = min(credit.quantity, quantity)  # a stale read cannot restore refunded credits
    s.flush()


def sync(s: Session, org: Organization) -> dict[str, Any]:
    """Reads the workspace's subscriptions and payments back from Dodo and applies them. Safe to call any number of times."""
    billing = dict(org.billing or {})
    cid = billing.get("customer_id")
    if not billing_enabled() or not cid:
        return billing
    mine = lambda x: (x.get("metadata") or {}).get("org_id", org.id) == org.id  # noqa: E731 - one Dodo customer could be shared by email
    subs = [x for x in _all_dodo("/subscriptions", customer_id=cid)
            if mine(x) and ITEMS.get(_item_of(x.get("product_id")) or "", {}).get("plan")]
    if subs:
        def key(x: dict[str, Any]) -> tuple:
            item = ITEMS[_item_of(x["product_id"]) or ""]
            return (x.get("status") in PAID, RANK.get(item["plan"], 0), x.get("created_at") or "")
        cur = max(subs, key=key)
        item = ITEMS[_item_of(cur["product_id"]) or ""]
        billing.update(subscription_id=cur["subscription_id"], status=cur.get("status"), plan=item["plan"], interval=item["interval"],
                       period_end=cur.get("next_billing_date"), cancel_at_period_end=bool(cur.get("cancel_at_next_billing_date")))
        if billing["status"] != "past_due":
            billing.pop("past_due_ends_at", None)
    else:
        for key in ("subscription_id", "status", "plan", "interval", "period_end", "cancel_at_period_end", "past_due_ends_at"):
            billing.pop(key, None)
    for pay in _all_dodo("/payments", customer_id=cid, status="succeeded"):
        if pay.get("subscription_id") or (pay.get("subscription_ids") or []):
            continue
        recorded = _payment_credits(s, None, pay["payment_id"])
        if any(credit.org_id != org.id for credit in recorded) or (recorded and not pay.get("refund_status")):
            continue
        full = _dodo("GET", f"/payments/{pay['payment_id']}")
        _sync_payment(s, org, full)
    billing["synced_at"] = now().isoformat()
    org.billing = billing
    return billing


def verify_webhook(headers: Any, body: bytes) -> None:
    """Standard Webhooks signature check: HMAC-SHA256 over "{id}.{timestamp}.{body}" with the endpoint's secret."""
    secret = settings().dodo_webhook_key
    wid, ts, sigs = headers.get("webhook-id"), headers.get("webhook-timestamp"), headers.get("webhook-signature") or ""
    if not (secret and wid and ts and ts.isdigit()):
        raise BillingError("missing webhook signature", 401)
    if abs(time.time() - int(ts)) > 300:
        raise BillingError("webhook timestamp too old", 401)
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except ValueError as exc:
        raise BillingError("DODO_PAYMENTS_WEBHOOK_KEY is not a valid signing secret (whsec_...)", 500) from exc
    want = base64.b64encode(hmac.new(key, f"{wid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    if not any(hmac.compare_digest(want.encode(), part.split(",", 1)[1].encode()) for part in sigs.split() if part.startswith("v1,")):
        raise BillingError("bad webhook signature", 401)


def org_for_event(s: Session, data: dict[str, Any]) -> Organization | None:
    org_id = (data.get("metadata") or {}).get("org_id")
    if org_id and (org := s.get(Organization, org_id)):
        return org
    cid = (data.get("customer") or {}).get("customer_id")
    return s.scalars(select(Organization).where(Organization.billing["customer_id"].astext == cid)).first() if cid else None


def apply_event(s: Session, org: Organization, event: dict[str, Any]) -> None:
    """What only the webhook says: the grace-period deadline, and refunds of top-ups. A refunded top-up keeps its
    credit row at quantity 0, so a later sync cannot add it again (the payment itself stays "succeeded")."""
    data = event.get("data") or {}
    etype = str(event.get("type", ""))
    billing = dict(org.billing or {})
    if etype.startswith("subscription.") and data.get("past_due_ends_at") and data.get("subscription_id") == billing.get("subscription_id"):
        billing["past_due_ends_at"] = data["past_due_ends_at"]
        org.billing = billing
    if etype == "refund.succeeded" and data.get("payment_id"):
        if data.get("is_partial"):
            full = _dodo("GET", f"/payments/{data['payment_id']}")
            full["refund_status"] = full.get("refund_status") or "partial"
            _sync_payment(s, org, full)
        else:
            for credit in _payment_credits(s, org, data["payment_id"]):
                credit.note, credit.quantity = f"{credit.note}; refunded ({credit.quantity} removed)", 0
