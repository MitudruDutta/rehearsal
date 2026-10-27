"""Privileged read-only state access for the oracle and the compiler's validator.

Checks are untrusted text (a model proposes them), so every probe enforces:

* exactly one statement (no ``;`` except trailing), no client meta-commands;
* a read-only transaction / authorizer on the database side;
* parameters bound by the database client, never spliced into SQL text
  (MySQL session variables are escaped, which is the client's only option).
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import tempfile
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import monotonic
from typing import Any

from ..core.contracts import StateProbe, render_template
from ..runner.runtime import WorldInstance

NULL = "__RH_NULL__"
SEP = "\x1f"
PARAM = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")
SQLITE_TIMEOUT_S = 15
SQLITE_MAX_ROWS = 1000
SQLITE_MAX_VALUE_BYTES = 1024 * 1024
SQLITE_MAX_RESULT_BYTES = 4 * 1024 * 1024


class ProbeError(Exception):
    pass


def single_statement(sql: str) -> str:
    body = sql.strip().rstrip(";").strip()
    if not body:
        raise ProbeError("empty query")
    if ";" in body:
        raise ProbeError("checks must be a single statement")
    if "\\" in body:
        raise ProbeError("client meta-commands are not allowed")
    return body


def params_used(sql: str) -> list[str]:
    return sorted(set(PARAM.findall(sql)))


def _sqlite_authorizer(action: int, *_args: Any) -> int:
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def query_sqlite_conn(conn: sqlite3.Connection, sql: str, params: dict[str, Any]) -> list[tuple]:
    body = single_statement(sql)
    names = params_used(body)
    missing = [p for p in names if p not in params]
    if missing:
        raise ProbeError(f"unbound parameters {missing}")
    deadline = monotonic() + SQLITE_TIMEOUT_S
    previous_length = conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    conn.set_authorizer(_sqlite_authorizer)
    try:
        # Also bound SQL-generated strings/blobs: a single row can exhaust memory.
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(previous_length, SQLITE_MAX_VALUE_BYTES))
        conn.set_progress_handler(lambda: monotonic() >= deadline, 1000)
        # Bound returned rows without limiting the input to aggregates such as COUNT(*).
        rows = []
        result_bytes = 0
        with closing(conn.execute(body, {k: params[k] for k in names})) as cursor:
            for row in cursor:
                if len(rows) >= SQLITE_MAX_ROWS:
                    raise ProbeError(f"sqlite: result exceeds {SQLITE_MAX_ROWS} rows")
                result_bytes += sum(len(value.encode("utf-8")) if isinstance(value, str)
                                    else len(value) if isinstance(value, bytes) else 64 for value in row)
                if result_bytes > SQLITE_MAX_RESULT_BYTES:
                    raise ProbeError(f"sqlite: result exceeds {SQLITE_MAX_RESULT_BYTES} bytes")
                rows.append(row)
        return rows
    except sqlite3.Error as exc:
        raise ProbeError(f"sqlite: {exc}") from exc
    finally:
        conn.set_progress_handler(None, 0)
        conn.set_authorizer(None)
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, previous_length)


class Prober:
    """Runs read-only queries against one world instance's state probes."""

    def __init__(self, instance: WorldInstance):
        self.instance = instance
        self.probes = {p.name: p for p in instance.manifest.state_probes}
        self._sqlite_cache: dict[str, sqlite3.Connection] = {}

    def probe(self, name: str | None) -> StateProbe:
        if not self.probes:
            raise ProbeError("world declares no state probe")
        if name is None:
            return next(iter(self.probes.values()))
        if name not in self.probes:
            raise ProbeError(f"unknown probe {name}")
        return self.probes[name]

    def invalidate(self) -> None:
        for conn in self._sqlite_cache.values():
            conn.close()
        self._sqlite_cache.clear()

    def _secret(self, value: str | None) -> str | None:
        return render_template(value, {"secret": self.instance.record.secrets}) if value else value

    # ------------------------------------------------------------------ query

    def query(self, sql: str, params: dict[str, Any] | None = None, probe: str | None = None) -> list[tuple]:
        params = params or {}
        p = self.probe(probe)
        if p.kind == "sqlite":
            return query_sqlite_conn(self._sqlite(p), sql, params)
        if p.kind == "postgres":
            return self._postgres(p, sql, params)
        return self._mysql(p, sql, params)

    def _sqlite(self, p: StateProbe) -> sqlite3.Connection:
        if p.name not in self._sqlite_cache:
            tmp = Path(tempfile.mkdtemp(prefix="rh-probe-"))
            base = Path(p.path).name  # type: ignore[arg-type]
            if not self.instance.copy_out(p.service, p.path, tmp / base):  # type: ignore[arg-type]
                raise ProbeError(f"could not copy {p.path} from {p.service}")
            for suffix in ("-wal", "-shm"):
                self.instance.copy_out(p.service, f"{p.path}{suffix}", tmp / f"{base}{suffix}")
            self._sqlite_cache[p.name] = sqlite3.connect(tmp / base)
        return self._sqlite_cache[p.name]

    def _postgres(self, p: StateProbe, sql: str, params: dict[str, Any]) -> list[tuple]:
        body = single_statement(sql)
        names = params_used(body)
        missing = [n for n in names if n not in params]
        if missing:
            raise ProbeError(f"unbound parameters {missing}")
        body = PARAM.sub(lambda m: f":'{m.group(1)}'", body)
        cmd = ["env", "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=15000"]
        if p.password:
            cmd.append(f"PGPASSWORD={self._secret(p.password)}")
        cmd += ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-A", "-t", "-F", SEP, "-P", f"null={NULL}", "-U", p.user, "-d", p.database]  # type: ignore[list-item]
        for n in names:
            cmd += ["-v", f"{n}={params[n]}"]
        # psql interpolates :'name' only in scripts, not in -c strings.
        script = f"BEGIN READ ONLY;\n{body}\n;\nROLLBACK;\n"
        rc, out, err = self.instance.exec(p.service, [*cmd, "-f", "-"], timeout=60, stdin=script)
        if rc != 0:
            raise ProbeError(f"postgres: {err.strip()[-800:]}")
        return _rows(out)

    def _mysql(self, p: StateProbe, sql: str, params: dict[str, Any]) -> list[tuple]:
        body = single_statement(sql)
        names = params_used(body)
        missing = [n for n in names if n not in params]
        if missing:
            raise ProbeError(f"unbound parameters {missing}")
        body = PARAM.sub(lambda m: f"@{m.group(1)}", body)
        sets = "".join(f"SET @{n}={_mysql_literal(params[n])}; " for n in names)
        script = f"{sets}START TRANSACTION READ ONLY; {body}; ROLLBACK;"
        cmd = ["env"]
        if p.password:
            cmd.append(f"MYSQL_PWD={self._secret(p.password)}")
        # MariaDB 11+ images ship the client only as `mariadb`.
        cmd += ["sh", "-c", 'exec "$(command -v mariadb || command -v mysql)" "$@"', "client", "-u", p.user, "-D", p.database, "-N", "-B", "--raw", "-e", script]  # type: ignore[list-item]
        rc, out, err = self.instance.exec(p.service, cmd, timeout=60)
        if rc != 0:
            raise ProbeError(f"mysql: {err.strip()[-800:]}")
        return [tuple(None if c == "NULL" else c for c in line.split("\t")) for line in out.splitlines() if line]

    # ------------------------------------------------------------------ canonical state

    def fingerprint(self) -> dict[str, str]:
        """Per-table content hashes across all probes, for reset determinism checks."""
        result: dict[str, str] = {}
        for p in self.probes.values():
            if p.kind == "sqlite":
                self.invalidate()
                conn = self._sqlite(p)
                tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                for t in tables:
                    rows = sorted(repr(r) for r in conn.execute(f'SELECT * FROM "{t}"'))
                    result[f"{p.name}:{t}"] = hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]
            elif p.kind == "postgres":
                tables = self._postgres(
                    p,
                    "SELECT quote_ident(schemaname) || '.' || quote_ident(tablename) FROM pg_tables "
                    "WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1",
                    {},
                )
                names = [t[0] for t in tables]
                for i in range(0, len(names), 40):
                    chunk = names[i : i + 40]
                    union = " UNION ALL ".join(
                        f"SELECT '{t}', (SELECT md5(coalesce(string_agg(x::text, chr(10) ORDER BY x::text), '')) FROM {t} x)"
                        for t in chunk
                    )
                    for name, digest in self._postgres(p, union, {}):
                        result[f"{p.name}:{name}"] = (digest or "")[:16]
            else:
                tables = [t[0] for t in self._mysql(p, f"SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_type='BASE TABLE' ORDER BY 1", {})]
                if tables:
                    rows = self._mysql(p, "CHECKSUM TABLE " + ", ".join(f"`{t}`" for t in tables), {})
                    for name, digest in rows:
                        result[f"{p.name}:{name}"] = str(digest)
        return result


def _mysql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def _rows(out: str) -> list[tuple]:
    rows = []
    for line in out.splitlines():
        if not line:
            continue
        rows.append(tuple(None if c == NULL else c for c in line.split(SEP)))
    return rows


def effects_connection(journal: list[dict[str, Any]]) -> sqlite3.Connection:
    """Loads the provider journal into an in-memory SQLite table ``effects``."""
    conn = sqlite3.connect(":memory:")
    cols = ["id", "provider", "operation", "idempotency_key", "reference", "amount", "status", "request_json", "response_json", "created_at"]
    conn.execute(f"CREATE TABLE effects ({', '.join(cols)})")
    conn.executemany(f"INSERT INTO effects VALUES ({','.join('?' * len(cols))})", [[e.get(c) for c in cols] for e in journal])
    return conn


def coerce_equal(actual: Any, expected: Any) -> Any:
    """Converts a textual database value to the type of the expected value."""
    if actual is None or expected is None:
        return actual
    if isinstance(expected, bool):
        return str(actual).lower() in ("1", "t", "true", "yes")
    if isinstance(expected, int) and not isinstance(expected, bool):
        try:
            if isinstance(actual, int) or (
                isinstance(actual, str) and re.fullmatch(r"[+-]?\d+", actual.strip())
            ):
                return int(actual)
            number = Decimal(str(actual))
            if not number.is_finite():
                return float(number)
            return int(number) if number == number.to_integral_value() else number
        except (TypeError, ValueError, InvalidOperation):
            return actual
    if isinstance(expected, float):
        try:
            return float(actual)
        except (TypeError, ValueError):
            return actual
    return str(actual) if not isinstance(actual, str) else actual
