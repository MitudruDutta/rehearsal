"""Process configuration read from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    # Only fills variables that are not already set, so real environment wins.
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    session_secret: str
    source_roots: tuple[Path, ...]
    model_compiler: str
    model_agent: str
    model_participant: str
    model_improver: str
    neatlogs_api_key: str | None
    kaggle_api_token: str | None
    google_client_id: str | None = None  # enables "Sign in with Google" in the console
    signup: str = "closed"  # "open" lets anyone create an organisation and get an admin key from the console
    lease_seconds: int = 60
    run_parallel: int = 4  # evaluation shards per run: each is one job, one worker, one sandbox
    build_parallel: int = 4  # scenarios a build writes and validates at once (validation lanes each run a copy of the world)
    max_active_builds: int = 0  # per project; 0 = no limit (set both on a shared server)
    max_active_runs: int = 0
    monthly_allowance_usd: float = 0.0  # model spend a workspace may use per calendar month on the server's keys; 0 = no limit
    container_memory: str = "1g"
    container_cpus: str = "1.0"
    container_pids: int = 256
    extra: dict = field(default_factory=dict)

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    def stored_path(self, path: str | Path) -> str:
        """How a path under the data folder is kept in the database: relative to it, so a data folder copied to
        another machine (or mounted elsewhere) still works. Paths outside it stay absolute."""
        p = Path(path).resolve()
        try:
            return str(p.relative_to(self.data_dir))
        except ValueError:
            return str(p)

    def data_path(self, stored: str | None) -> Path:
        """The real location of a path kept with stored_path (absolute paths from older rows are returned as they are)."""
        return self.data_dir / (stored or "")


@lru_cache
def settings() -> Settings:
    _load_dotenv(Path(os.environ.get("REHEARSAL_ENV_FILE", ".env")))
    env = os.environ.get
    data_dir = Path(env("REHEARSAL_DATA_DIR", "./var")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    roots = tuple(
        Path(p).resolve() for p in env("REHEARSAL_SOURCE_ROOTS", "./examples").split(",") if p.strip()
    )
    default_chain = "groq:openai/gpt-oss-120b,openrouter:openai/gpt-oss-120b,google:gemini-2.5-flash"
    return Settings(
        database_url=env(
            "REHEARSAL_DATABASE_URL", "postgresql+psycopg://rehearsal:rehearsal@127.0.0.1:5433/rehearsal"
        ),
        data_dir=data_dir,
        session_secret=env("REHEARSAL_SESSION_SECRET", "dev-only-session-secret"),
        source_roots=roots,
        model_compiler=env("REHEARSAL_MODEL_COMPILER", default_chain),
        model_agent=env("REHEARSAL_MODEL_AGENT", default_chain),
        model_participant=env("REHEARSAL_MODEL_PARTICIPANT", "groq:openai/gpt-oss-20b,google:gemini-2.5-flash"),
        model_improver=env("REHEARSAL_MODEL_IMPROVER", env("REHEARSAL_MODEL_COMPILER", default_chain)),
        neatlogs_api_key=env("NEATLOGS_API_KEY") or None,
        kaggle_api_token=env("KAGGLE_API_TOKEN") or None,
        google_client_id=env("GOOGLE_CLIENT_ID") or None,
        signup=env("REHEARSAL_SIGNUP", "closed"),
        lease_seconds=int(env("REHEARSAL_LEASE_SECONDS", "60")),
        run_parallel=int(env("REHEARSAL_RUN_PARALLEL", "4")),
        build_parallel=int(env("REHEARSAL_BUILD_PARALLEL", "4")),
        max_active_builds=int(env("REHEARSAL_MAX_ACTIVE_BUILDS", "0")),
        max_active_runs=int(env("REHEARSAL_MAX_ACTIVE_RUNS", "0")),
        monthly_allowance_usd=float(env("REHEARSAL_MONTHLY_ALLOWANCE_USD", "0")),
        container_memory=env("REHEARSAL_CONTAINER_MEMORY", "1g"),
        container_cpus=env("REHEARSAL_CONTAINER_CPUS", "1.0"),
        container_pids=int(env("REHEARSAL_CONTAINER_PIDS", "256")),
    )
