"""Bounded SQLite checks and worker networking, without Docker or network calls."""

import json
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import httpx
import pytest
import yaml

from rehearsal.core.contracts import CheckSpec, ServiceSpec, WorldManifest
from rehearsal.evaluator import probes
from rehearsal.evaluator.oracle import run_check
from rehearsal.runner import runtime


@pytest.fixture
def db():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE items (n INTEGER)")
        conn.executemany("INSERT INTO items VALUES (?)", ((n,) for n in range(probes.SQLITE_MAX_ROWS + 1)))
        yield conn


@pytest.mark.parametrize("projection", ["sum(n)", "n"])
def test_sqlite_deadline_interrupts_execution_and_fetching(db, monkeypatch, projection):
    clock = Mock(side_effect=[0, probes.SQLITE_TIMEOUT_S])
    monkeypatch.setattr(probes, "monotonic", clock)
    sql = (
        "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n < 1000000) "
        f"SELECT {projection} FROM seq"
    )
    with pytest.raises(probes.ProbeError, match="sqlite: interrupted"):
        probes.query_sqlite_conn(db, sql, {})
    assert clock.call_count == 2
    # An expired handler or lingering authorizer would break these ordinary operations.
    monkeypatch.setattr(probes, "monotonic", lambda: probes.SQLITE_TIMEOUT_S + 1)
    db.execute("INSERT INTO items VALUES (-1)")
    assert db.execute("SELECT sum(a.n) FROM items a CROSS JOIN items b").fetchone()[0] > 0


def test_sqlite_result_collection_stops_at_row_bound(db, monkeypatch):
    monkeypatch.setattr(probes, "monotonic", lambda: 0)
    seen = []
    db.create_function("seen", 1, lambda n: seen.append(n) or n)
    sql = (
        "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n < :total) "
        "SELECT seen(n) FROM seq"
    )
    with pytest.raises(probes.ProbeError, match=f"result exceeds {probes.SQLITE_MAX_ROWS} rows"):
        probes.query_sqlite_conn(db, sql, {"total": probes.SQLITE_MAX_ROWS * 10})
    assert probes.SQLITE_MAX_ROWS < len(seen) <= probes.SQLITE_MAX_ROWS + 2
    db.execute("INSERT INTO items VALUES (-1)")


def test_sqlite_accepts_exact_row_bound(db):
    rows = probes.query_sqlite_conn(db, "SELECT n FROM items WHERE n < :limit ORDER BY n", {"limit": probes.SQLITE_MAX_ROWS})
    assert rows == [(n,) for n in range(probes.SQLITE_MAX_ROWS)]


def test_sqlite_rejects_oversized_generated_value_and_restores_limit(db):
    previous = db.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    with pytest.raises(probes.ProbeError, match="string or blob too big"):
        probes.query_sqlite_conn(db, "SELECT zeroblob(:size)", {"size": probes.SQLITE_MAX_VALUE_BYTES + 1})
    assert db.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == previous
    assert probes.query_sqlite_conn(db, "SELECT count(*) FROM items", {}) == [(probes.SQLITE_MAX_ROWS + 1,)]


def test_sqlite_stops_large_result_before_collecting_all_rows(db, monkeypatch):
    monkeypatch.setattr(probes, "SQLITE_MAX_RESULT_BYTES", 1024)
    with pytest.raises(probes.ProbeError, match="result exceeds 1024 bytes"):
        probes.query_sqlite_conn(db, "SELECT zeroblob(600) FROM items", {})
    assert probes.query_sqlite_conn(db, "SELECT count(*) FROM items", {}) == [(probes.SQLITE_MAX_ROWS + 1,)]


@pytest.mark.parametrize("source", ["app", "effects"])
def test_oracle_counts_all_input_rows_above_result_bound(db, monkeypatch, source):
    probe = SimpleNamespace(name="db", kind="sqlite")
    prober = probes.Prober(SimpleNamespace(manifest=SimpleNamespace(state_probes=[probe])))
    monkeypatch.setattr(prober, "_sqlite", lambda p: db)
    check = CheckSpec(
        id="count", description="full count", source=source,
        query="SELECT count(*) FROM items WHERE n >= :minimum", value=probes.SQLITE_MAX_ROWS + 1,
    )
    result = run_check(check, prober, db, {"minimum": 0})
    assert result["passed"] is True
    assert result["actual"] == probes.SQLITE_MAX_ROWS + 1


@pytest.mark.parametrize("sql", ["DELETE FROM items", "SELECT nonexistent FROM items", "PRAGMA user_version"])
def test_sqlite_error_keeps_data_and_clears_authorizer(db, sql):
    with pytest.raises(probes.ProbeError, match="sqlite:"):
        probes.query_sqlite_conn(db, sql, {})
    assert db.execute("SELECT count(*) FROM items").fetchone() == (probes.SQLITE_MAX_ROWS + 1,)
    db.execute("CREATE TABLE after_probe (n INTEGER)")


def test_oracle_still_rejects_multiple_rows(db):
    check = CheckSpec(id="rows", description="invalid shape", source="effects", query="SELECT n FROM items LIMIT 2")
    result = run_check(check, None, db, {})
    assert result["passed"] is False
    assert "exactly one row and column" in result["error"]


@pytest.fixture
def instance(monkeypatch):
    monkeypatch.delenv("REHEARSAL_WORKER_CONTAINER", raising=False)
    monkeypatch.setattr(runtime, "_run", Mock(side_effect=AssertionError("unexpected Docker command")))
    manifest = WorldManifest(name="test", services=[ServiceSpec(name="app", image="test", port=8080)])
    return runtime.WorldInstance(runtime.InstanceRecord(
        "test", manifest.model_dump(mode="json", by_alias=True), {}, "test-admin-token",
        images={"app": "test"}, volumes={"app": [], "providers": [("rh-test-providers-0", "/data")]},
    ))


def test_host_worker_edge_uses_loopback_and_caches(instance, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "127.0.0.1:32789\n", ""))
    monkeypatch.setattr(runtime, "_run", run)
    assert instance.edge_url() == instance.edge_url() == "http://127.0.0.1:32789"
    run.assert_called_once_with(["docker", "port", "rh-test-providers", "9000"])


@pytest.mark.parametrize("attached", [False, True])
def test_container_worker_reaches_provider_on_outer_bridge(instance, monkeypatch, attached):
    monkeypatch.setenv("REHEARSAL_WORKER_CONTAINER", "worker-id")
    networks = {"compose_default": {}}
    if attached:
        networks["rh-test-ext"] = {}
    run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(networks), ""))
    monkeypatch.setattr(runtime, "_run", run)
    assert instance.edge_url() == instance.edge_url() == "http://rh-test-providers:9000"
    expected = [call(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", "worker-id"])]
    if not attached:
        expected.append(call(["docker", "network", "connect", "rh-test-ext", "worker-id"]))
    assert run.call_args_list == expected


def test_reattached_instance_connects_replacement_worker(instance, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{"compose_default": {}}', ""))
    monkeypatch.setattr(runtime, "_run", run)
    monkeypatch.setenv("REHEARSAL_WORKER_CONTAINER", "first-worker")
    instance.edge_url()
    reattached = runtime.WorldInstance(runtime.InstanceRecord.from_json(instance.record.to_json()))
    monkeypatch.setenv("REHEARSAL_WORKER_CONTAINER", "replacement-worker")
    assert reattached.edge_url() == "http://rh-test-providers:9000"
    run.assert_any_call(["docker", "network", "connect", "rh-test-ext", "first-worker"])
    run.assert_any_call(["docker", "network", "connect", "rh-test-ext", "replacement-worker"])


@pytest.mark.parametrize("container_worker", [False, True])
def test_provider_start_preserves_publishing_isolation_and_admin_auth(instance, monkeypatch, container_worker):
    if container_worker:
        monkeypatch.setenv("REHEARSAL_WORKER_CONTAINER", "worker-id")

    def docker(args, **kwargs):
        if args[:2] == ["docker", "port"]:
            return subprocess.CompletedProcess(args, 0, "127.0.0.1:32789\n", "")
        if args[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(args, 0, '{"compose_default": {}}', "")
        return subprocess.CompletedProcess(args, 0, "", "")

    run = Mock(side_effect=docker)
    monkeypatch.setattr(runtime, "_run", run)
    monkeypatch.setattr(runtime, "providers_image", lambda: "providers:test")
    monkeypatch.setattr(instance, "_hardening", lambda: [])
    monkeypatch.setattr(instance, "_wait", lambda probe, *args: probe() or pytest.fail("health probe failed"))
    requests = []

    def health(request):
        requests.append(request)
        return httpx.Response(200)

    client = httpx.Client
    monkeypatch.setattr(runtime.httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(health), **kwargs))
    try:
        instance._start_providers()
        expected = "http://rh-test-providers:9000" if container_worker else "http://127.0.0.1:32789"
        assert str(requests[0].url) == expected + "/__health"
        assert requests[0].headers["X-Rehearsal-Admin"] == "test-admin-token"
        assert instance.edge_client().trust_env is False
    finally:
        if instance._client:
            instance._client.close()
    args = run.call_args_list[0].args[0]
    assert args[args.index("--network") + 1] == "rh-test-ext"
    assert args[args.index("-p") + 1] == "127.0.0.1::9000"
    run.assert_any_call(["docker", "network", "connect", "--alias", "providers", "rh-test-int", "rh-test-providers"])
    assert instance._service_args(instance.manifest.services[0])[2:4] == ["--network", "rh-test-int"]


@pytest.mark.parametrize("remaining", [{}, None, {"old-worker-id": {"Name": "old-worker"}, "new-worker-id": {"Name": "new-worker"}}])
def test_destroy_detaches_all_workers_before_removing_outer_bridge(instance, monkeypatch, remaining):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(remaining), ""))
    monkeypatch.setattr(runtime, "_run", run)
    instance.destroy()
    disconnects = [call(["docker", "network", "disconnect", "-f", "rh-test-ext", worker], check=False) for worker in remaining or {}]
    assert run.call_args_list[3:-1] == disconnects
    assert run.call_args_list[-1] == call(["docker", "network", "rm", "rh-test-int", "rh-test-ext"], check=False)
    assert run.call_args_list[0] == call(["docker", "rm", "-f", "rh-test-app", "rh-test-providers"], check=False)


def test_destroy_tolerates_missing_outer_bridge(instance, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 1, "", "network not found"))
    monkeypatch.setattr(runtime, "_run", run)
    instance.destroy()
    assert not any(c.args[0][:3] == ["docker", "network", "disconnect"] for c in run.call_args_list)
    run.assert_called_with(["docker", "network", "rm", "rh-test-int", "rh-test-ext"], check=False)


def test_compose_passes_each_workers_container_identity(tmp_path):
    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "infra/compose.full.yaml").read_text())
    worker = compose["services"]["worker"]
    assert worker.get("network_mode") != "host"
    # Run the Compose shell command with a fake executable, never the real worker.
    executable = tmp_path / "rehearsal"
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$1" "$REHEARSAL_WORKER_CONTAINER" "$(umask)"\n')
    executable.chmod(0o755)
    proc = subprocess.run(
        [*worker["entrypoint"], worker["command"][0].replace("$$", "$")],
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "HOSTNAME": "scaled-worker-id"},
        capture_output=True, text=True, check=True,
    )
    assert proc.stdout.splitlines() == ["worker", "scaled-worker-id", "0002"]
