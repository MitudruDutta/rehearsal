"""Probe SQL safety and exact numeric coercion regressions."""

import sqlite3
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rehearsal.evaluator.probes import (
    SEP,
    ProbeError,
    Prober,
    coerce_equal,
    query_sqlite_conn,
    single_statement,
)


@pytest.mark.parametrize("sql", [
    r"SELECT 1 \gexec",
    r"SELECT 1 \! echo probe",
    r"SELECT 1\g /tmp/probe-output",
    r"SELECT 1 \o /tmp/probe-output",
    r"SELECT 1 \system echo probe",
    r"SELECT 1 \source /tmp/probe-input",
    "SELECT 1\n  \\! echo probe",
    r"SELECT '\! echo probe'",
    r"SELECT 1 /* \! echo probe */",
])
def test_rejects_backslashes_anywhere(sql):
    with pytest.raises(ProbeError, match="client meta-commands"):
        single_statement(sql)


@pytest.mark.parametrize("kind", ["postgres", "mysql"])
def test_inline_meta_command_rejected_before_client_execution(kind):
    probe = SimpleNamespace(
        name="db", kind=kind, service="db", password=None,
        user="reader", database="app",
    )
    instance = SimpleNamespace(
        manifest=SimpleNamespace(state_probes=[probe]), exec=Mock()
    )
    with pytest.raises(ProbeError, match="client meta-commands"):
        Prober(instance).query(r"SELECT 1 \! echo probe")
    instance.exec.assert_not_called()


@pytest.mark.parametrize("sql, body", [
    (" SELECT 1; ", "SELECT 1"),
    ("SELECT 1.25", "SELECT 1.25"),
    ("SELECT * FROM orders WHERE id = :order_id", "SELECT * FROM orders WHERE id = :order_id"),
    ("SELECT 'it''s safe'", "SELECT 'it''s safe'"),
    ("SELECT 1\nFROM orders", "SELECT 1\nFROM orders"),
])
def test_accepts_normal_sql(sql, body):
    assert single_statement(sql) == body


def test_bound_backslash_value_is_not_sql():
    with sqlite3.connect(":memory:") as conn:
        value = r"\! echo probe"
        assert query_sqlite_conn(conn, "SELECT :value;", {"value": value}) == [(value,)]


def test_postgres_fingerprint_sql_passes_guard():
    probe = SimpleNamespace(
        name="db", kind="postgres", service="db", password=None,
        user="reader", database="app",
    )
    instance = SimpleNamespace(
        manifest=SimpleNamespace(state_probes=[probe]),
        exec=Mock(side_effect=[
            (0, "public.orders\n", ""),
            (0, f"public.orders{SEP}0123456789abcdef0123456789abcdef\n", ""),
        ]),
    )
    assert Prober(instance).fingerprint() == {"db:public.orders": "0123456789abcdef"}
    script = instance.exec.call_args.kwargs["stdin"]
    assert "\\" not in script
    assert "chr(10)" in script


@pytest.mark.parametrize("actual", [
    9007199254740993,
    "9007199254740993",
    "9007199254740993.0",
    "9.007199254740993e15",
    Decimal("9007199254740993"),
])
def test_large_integer_keeps_precision(actual):
    coerced = coerce_equal(actual, 9007199254740993)
    assert coerced == 9007199254740993
    assert coerced != 9007199254740992
    assert coerced != 9007199254740994
    assert coerce_equal(actual, 9007199254740992) > 9007199254740992


@pytest.mark.parametrize("actual, expected", [
    ("9007199254740993.1", 9007199254740993),
    (Decimal("9007199254740993.1"), 9007199254740993),
    ("1.00000000000000000001", 1),
    ("0.99999999999999999999", 1),
])
def test_fractional_values_do_not_round_to_integer(actual, expected):
    coerced = coerce_equal(actual, expected)
    assert coerced == Decimal(str(actual))
    assert coerced != expected


@pytest.mark.parametrize("actual, expected, result", [
    ("42", 42, 42),
    (" +42 ", 42, 42),
    ("-42", -42, -42),
    ("42.0", 42, 42),
    ("4.2e1", 42, 42),
    (42.0, 42, 42),
    ("1.25", 1, Decimal("1.25")),
    (Decimal("1.25"), 1, Decimal("1.25")),
    ("1.25", 1.25, 1.25),
    ("TRUE", True, True),
    ("t", True, True),
    ("yes", True, True),
    (1, True, True),
    ("false", False, False),
    (0, False, False),
    (True, 1, True),
    (None, 1, None),
    ("unchanged", None, "unchanged"),
    ("invalid", 1, "invalid"),
])
def test_normal_coercions(actual, expected, result):
    assert coerce_equal(actual, expected) == result
