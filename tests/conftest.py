"""Integration tests that touch PostgreSQL use a separate `rehearsal_test` database."""

import os

import pytest

TEST_DB = "postgresql+psycopg://rehearsal:rehearsal@127.0.0.1:5433/rehearsal_test"


def _prepare_db() -> bool:
    import psycopg

    try:
        with psycopg.connect("postgresql://rehearsal:rehearsal@127.0.0.1:5433/rehearsal", autocommit=True, connect_timeout=3) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = 'rehearsal_test'").fetchone():
                conn.execute("CREATE DATABASE rehearsal_test")
    except psycopg.OperationalError:
        return False
    return True


# Tests do not inherit plan enforcement or operator admins from a developer's .env (environment wins over .env).
os.environ["REHEARSAL_PLANS"] = "off"
os.environ["REHEARSAL_ADMIN_EMAILS"] = ""
# Tests must never reach a real account: no payments, no traces in the team's neatlogs dashboard, no model calls.
for _k in ("DODO_PAYMENTS_API_KEY", "DODO_PAYMENTS_WEBHOOK_KEY", "NEATLOGS_API_KEY", "LITELLM_API_KEY"):
    os.environ[_k] = ""

DB_AVAILABLE = _prepare_db()
if DB_AVAILABLE:
    os.environ["REHEARSAL_DATABASE_URL"] = TEST_DB
    os.environ.setdefault("REHEARSAL_DATA_DIR", "/tmp/rehearsal-test-data")
    os.environ["REHEARSAL_LEASE_SECONDS"] = "2"
    from rehearsal.db.session import upgrade

    upgrade()


@pytest.fixture
def db():
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL on 127.0.0.1:5433 is not running (rehearsal up)")
