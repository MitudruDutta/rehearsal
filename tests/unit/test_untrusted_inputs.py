"""An application's API description and source tree are untrusted: no input may make the compiler hang or explode."""

import json
import time

import pytest

from rehearsal.compiler import apispec, repo as repo_mod
from rehearsal.compiler.repo import Repo, RepoError


def timed(fn, *args):
    started = time.monotonic()
    out = fn(*args)
    return out, time.monotonic() - started


def test_a_yaml_alias_bomb_is_parsed_and_expanded_in_bounded_time():
    # nine levels of ten aliases each: a naive expansion walks a billion nodes
    levels = ["a0: &a0 {type: string}"] + [f"a{i}: &a{i} {{type: object, properties: {{{', '.join(f'p{j}: *a{i - 1}' for j in range(10))}}}}}" for i in range(1, 10)]
    text = "openapi: 3.0.0\ncomponents:\n  schemas:\n" + "\n".join("    " + line for line in levels) + (
        "\npaths:\n  /bomb:\n    post:\n      operationId: bomb\n      requestBody:\n        content:\n          application/json:\n"
        "            schema: {$ref: '#/components/schemas/a9'}\n")
    ops, seconds = timed(lambda: apispec.operations(apispec.parse_spec(text)))
    assert seconds < 2 and len(ops) == 1 and len(json.dumps(ops[0].body)) < 400_000


def test_wide_references_stay_within_the_expansion_budget():
    props = {f"p{i}": {"$ref": "#/components/schemas/Wide"} for i in range(200)}
    spec = {"components": {"schemas": {"Wide": {"type": "object", "properties": props}}},
            "paths": {"/w": {"post": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Wide"}}}}}}}}
    ops, seconds = timed(apispec.operations, spec)
    assert seconds < 2 and len(json.dumps(ops[0].body)) < 400_000


def test_a_huge_description_keeps_a_bounded_number_of_operations_and_never_loops():
    spec = {"paths": {f"/r/{i}": {"get": {"operationId": "AVeryLongOperationNameThatEveryRouteShares" * 2}} for i in range(5000)}}
    ops, seconds = timed(apispec.operations, spec)
    assert len(ops) == apispec.MAX_OPERATIONS and len({o.op_id for o in ops}) == len(ops) and seconds < 5


def test_an_oversized_description_is_refused_before_parsing(monkeypatch):
    monkeypatch.setattr(apispec, "MAX_SPEC_BYTES", 1000)
    with pytest.raises(ValueError, match="larger than"):
        apispec.parse_spec("openapi: 3.0.0\n" + "x: 1\n" * 500)


def test_source_files_and_searches_are_bounded(tmp_path, monkeypatch):
    (tmp_path / "big.js").write_text("a" * 3000 + "NEEDLE\n")  # a minified line: the match is past what is searched
    (tmp_path / "small.py").write_text("def handler():\n    return NEEDLE\n")
    r = Repo(tmp_path)
    assert r.grep("NEEDLE").splitlines() == ["small.py:2: return NEEDLE"]
    monkeypatch.setattr(repo_mod, "MAX_FILE_BYTES", 100)
    with pytest.raises(RepoError, match="grep"):
        r.read_file("big.js")
    monkeypatch.setattr(repo_mod, "SEARCH_SECONDS", -1)  # out of time at once
    assert "search stopped" in r.grep("NEEDLE") and "search stopped" in r.find("*.py")
