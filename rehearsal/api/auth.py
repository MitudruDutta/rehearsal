"""API keys (hashed at rest) and same-origin session cookies for the console."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import ApiKey, Membership, Organization, Project, User, now
from ..db.session import session

COOKIE = "rh_session"
SESSION_SECONDS = 12 * 3600
SCOPES = {"admin", "read", "write", "evaluator", "agent"}


@dataclass
class Principal:
    project_id: str
    key_id: str
    scopes: list[str]
    user_id: str | None = None  # set for console users; API keys have none

    @property
    def actor(self) -> str:
        return f"user:{self.user_id}" if self.user_id else f"key:{self.key_id}"

    def require(self, scope: str) -> None:
        if "admin" not in self.scopes and scope not in self.scopes:
            raise HTTPException(403, f"{scope} scope required")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def create_key(s: Session, project_id: str, name: str, scopes: list[str] | None = None) -> str:
    scopes = ["admin"] if scopes is None else scopes
    if not scopes or not set(scopes) <= SCOPES:
        raise HTTPException(422, "invalid or empty scopes")
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    s.add(ApiKey(project_id=project_id, name=name, prefix=prefix, hash=_hash(secret), scopes=scopes))
    s.flush()
    return f"rh_{prefix}_{secret}"


def bootstrap(org_name: str = "Local", project_name: str = "default") -> tuple[str, str]:
    """Creates an organisation, project, and admin key; returns (project_id, key)."""
    with session() as s:
        org = Organization(name=org_name)
        s.add(org)
        s.flush()
        project = Project(org_id=org.id, name=project_name)
        s.add(project)
        s.flush()
        return project.id, create_key(s, project.id, "bootstrap admin")


_SCRYPT = {"n": 2**15, "r": 8, "p": 1, "maxmem": 2**26, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        hashlib.scrypt(password.encode(), salt=b"0" * 16, **_SCRYPT)  # same cost for unknown accounts
        return False
    _, salt, digest = stored.split("$")
    return hmac.compare_digest(hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT).hex(), digest)


def create_user(name: str, email: str, password: str) -> str:
    """Email and password registration. The account starts without a workspace; onboarding creates one."""
    email = email.strip().lower()
    with session() as s:
        if s.scalar(select(func.count()).select_from(User).where(User.email == email)):
            raise ValueError("an account with this email already exists; sign in instead")
        user = User(email=email, name=name.strip(), password_hash=hash_password(password), last_login_at=now())
        s.add(user)
        try:
            s.flush()
        except IntegrityError as exc:  # a concurrent sign-up with the same email
            raise ValueError("an account with this email already exists; sign in instead") from exc
        return user.id


def password_login(email: str, password: str) -> tuple[str, str | None]:
    """Returns (user_id, project_id or None before onboarding); one error for wrong email or password."""
    with session() as s:
        user = s.scalars(select(User).where(User.email == email.strip().lower())).first()
        if not check_password(password, user.password_hash if user else None) or user is None:
            raise HTTPException(401, "email or password is incorrect")
        user.last_login_at = now()
        return user.id, default_project(s, user.id)


def add_member(email: str, name: str, password: str | None, project_id: str, role: str = "owner") -> str:
    """Operator command: gives a person access to a project's organisation (and a password, if given)."""
    email = email.strip().lower()
    with session() as s:
        project = s.get(Project, project_id)
        if project is None:
            raise ValueError(f"no project {project_id}")
        user = s.scalars(select(User).where(User.email == email)).first() or User(email=email, name=name)
        if password:
            user.password_hash = hash_password(password)
        s.add(user)
        s.flush()
        if not s.scalars(select(Membership).where(Membership.user_id == user.id, Membership.org_id == project.org_id)).first():
            s.add(Membership(user_id=user.id, org_id=project.org_id, role=role))
        return user.id


GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["accounts.google.com", "https://accounts.google.com"]
_google_keys: jwt.PyJWKClient | None = None


def verify_google(credential: str) -> dict[str, object]:
    """Checks a Google Identity Services ID token: Google's signature, our client ID, issuer, expiry, verified email."""
    global _google_keys
    client_id = settings().google_client_id
    if not client_id:
        raise HTTPException(503, "Google sign-in is not configured on this server (set GOOGLE_CLIENT_ID)")
    if _google_keys is None:
        _google_keys = jwt.PyJWKClient(GOOGLE_CERTS, cache_keys=True, lifespan=3600)
    try:
        key = _google_keys.get_signing_key_from_jwt(credential).key
        claims = jwt.decode(credential, key, algorithms=["RS256"], audience=client_id, issuer=GOOGLE_ISSUERS,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Google sign-in failed: {exc}") from exc
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise HTTPException(401, "Google account has no verified email")
    return claims


def google_user(claims: dict[str, object], allow_new: bool) -> tuple[str, str | None]:
    """Signs in, or registers, a Google account. Returns (user_id, project_id or None before onboarding)."""
    email = str(claims["email"]).lower()
    with session() as s:
        user = s.scalars(select(User).where(User.google_sub == claims["sub"])).first()
        if user is None:
            # Google verified this address, so it may claim an account created by email or by an operator
            user = s.scalars(select(User).where(User.email == email)).first()
            if user is None and not allow_new:
                raise HTTPException(403, "sign-up is closed on this server; ask an organisation owner to add you")
            if user is not None:
                user.password_hash = None  # nobody verified the address behind that password: whoever chose it loses it
            user = user or User(email=email)
            user.google_sub = str(claims["sub"])
            s.add(user)
        user.email = email
        user.name = str(claims.get("name") or user.name or email.split("@")[0])
        user.picture_url = str(claims["picture"]) if claims.get("picture") else None
        user.last_login_at = now()
        s.flush()
        return user.id, default_project(s, user.id)


def default_project(s: Session, user_id: str) -> str | None:
    row = s.execute(
        select(Project.id).join(Membership, Membership.org_id == Project.org_id)
        .where(Membership.user_id == user_id).order_by(Membership.created_at, Project.created_at)
    ).first()
    return row[0] if row else None


FREE_PER_DEVICE_DAYS = 90
FREE_PER_IP = (3, 30)  # workspaces, days: offices and campuses share one address


def create_workspace(user_id: str, org_name: str, project_name: str, *, device: str | None = None, ip: str | None = None) -> str:
    """Onboarding: an organisation owned by this user, with its first project. With plans on, every new workspace
    starts on the free plan, so one person cannot collect free plans: one owned workspace per account, one per
    browser, and a few per network address (operator admins are exempt)."""
    from .. import billing

    with session() as s:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(401, "session revoked")
        if settings().plans and not billing.is_admin(user):
            s.execute(text("SELECT pg_advisory_xact_lock(hashtext('free-workspaces'))"))  # serializes concurrent sign-ups
            owned = s.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user.id, Membership.role == "owner"))
            if owned:
                raise HTTPException(409, "This account already owns a workspace. Sign in to it, or ask us if you need a second one.")
            since = lambda days: now() - timedelta(days=days)  # noqa: E731
            if device and s.scalar(select(func.count()).select_from(Organization).where(Organization.created_device == device, Organization.created_at >= since(FREE_PER_DEVICE_DAYS))):
                raise HTTPException(409, "This browser already created a free workspace. Sign in with the account that owns it, or upgrade that workspace.")
            if ip and (s.scalar(select(func.count()).select_from(Organization).where(Organization.created_ip == ip, Organization.created_at >= since(FREE_PER_IP[1]))) or 0) >= FREE_PER_IP[0]:
                raise HTTPException(429, "Too many free workspaces were created from this network recently. Try again later, or contact us.")
        org = Organization(name=org_name.strip(), owner_name=user.name, created_device=device, created_ip=ip)
        s.add(org)
        s.flush()
        s.add(Membership(user_id=user.id, org_id=org.id, role="owner"))
        project = Project(org_id=org.id, name=project_name.strip() or "default")
        s.add(project)
        s.flush()
        return project.id


def verify_key(raw: str) -> Principal | None:
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != "rh":
        return None
    with session() as s:
        key = s.scalars(select(ApiKey).where(ApiKey.prefix == parts[1], ApiKey.revoked_at.is_(None))).first()
        if key is None or not hmac.compare_digest(key.hash, _hash(parts[2])):
            return None
        key.last_used_at = now()
        return Principal(key.project_id, key.id, list(key.scopes))


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings().session_secret, salt="rh-session")


def user_cookie(user_id: str, project_id: str | None) -> str:
    return _serializer().dumps({"u": user_id, "p": project_id})


ROLE_SCOPES = {"owner": ["admin"], "admin": ["admin"], "member": ["read", "write", "evaluator"]}
BEFORE_ONBOARDING = {"/v1/me", "/v1/onboarding/workspace"}
DEVICE_COOKIE = "rh_device"  # random per browser, set at sign-in; limits free workspaces per browser  # all a signed-in user without a project may call


def _user_principal(request: Request, data: dict[str, object]) -> Principal:
    with session() as s:
        user = s.get(User, data["u"])
        if user is None:
            raise HTTPException(401, "session revoked")
        project_id = data.get("p")
        if not project_id:
            if request.url.path.rstrip("/") in BEFORE_ONBOARDING:
                return Principal("", f"user:{user.id}", [], user.id)
            raise HTTPException(409, "create a workspace first")
        project = s.get(Project, project_id)
        member = project and s.scalars(select(Membership).where(Membership.user_id == user.id, Membership.org_id == project.org_id)).first()
        if not member:
            raise HTTPException(401, "no access to this project")
        return Principal(str(project_id), f"user:{user.id}", list(ROLE_SCOPES.get(member.role, ["read"])), user.id)


def principal(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        p = verify_key(header[7:].strip())
        if p is None:
            raise HTTPException(401, "invalid API key")
        return authorize(request, p)
    cookie = request.cookies.get(COOKIE)
    if cookie:
        try:
            data = _serializer().loads(cookie, max_age=SESSION_SECONDS)
        except (BadSignature, SignatureExpired) as exc:
            raise HTTPException(401, "session expired") from exc
        if "u" not in data:
            raise HTTPException(401, "session expired")  # an old API-key console session
        return authorize(request, _user_principal(request, data))
    raise HTTPException(401, "authentication required")


def authorize(request: Request, p: Principal) -> Principal:
    """Enforce scopes for both bearer and cookie authentication."""
    path = request.url.path.rstrip("/")
    if path in BEFORE_ONBOARDING:
        return p
    if path.startswith("/v1/admin"):
        if not p.user_id:
            raise HTTPException(403, "operator admin pages need a console sign-in, not an API key")
        p.require("read" if request.method in ("GET", "HEAD", "OPTIONS") else "write")  # the handler checks the operator admin list
    elif path.startswith(("/v1/api-keys", "/v1/credentials", "/v1/billing/checkout", "/v1/billing/change", "/v1/billing/portal")):
        p.require("admin")
    elif path.startswith("/v1/episodes/") and (
        path.endswith("/observation") or "/actions" in path
    ):
        if "agent" not in p.scopes:
            p.require("write" if request.method == "POST" else "read")
    elif ("/scenarios" in path or path.startswith("/v1/scenarios/")
          or path.startswith("/v1/episodes/") or "/events" in path
          or path.startswith("/v1/streams/") or path.startswith("/v1/artifacts")
          or path == "/v1/dashboard" or path.startswith("/v1/world-versions/")
          or (path.startswith("/v1/runs/") and path.endswith("/episodes"))):
        p.require("evaluator")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            p.require("write")
    else:
        p.require("read" if request.method in ("GET", "HEAD", "OPTIONS") else "write")
    return p
