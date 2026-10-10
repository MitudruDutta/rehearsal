"""SDK regressions with mocked HTTP and optional imports; no services required."""

import builtins
import json

import httpx
import pytest

from rehearsal.sdk import Rehearsal, RehearsalError
from rehearsal.sdk import cli, client as sdk


@pytest.fixture
def api(monkeypatch):
    responses, requests = [], []

    def respond(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    with httpx.Client(base_url="https://rehearsal.test", transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(sdk.httpx, "Client", lambda **kwargs: http)
        yield Rehearsal(api_key="test", base_url="https://rehearsal.test"), responses, requests


@pytest.mark.parametrize("interruption", [None, httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError])
def test_stream_reconnects_with_cursor_until_explicit_end(api, monkeypatch, interruption):
    client, responses, requests = api
    sleeps = []
    monkeypatch.setattr(sdk.time, "sleep", sleeps.append)
    responses.append(httpx.Response(200, text='data: {"event_id": 5}\n\n'))
    responses.append(interruption("disconnected") if interruption else httpx.Response(200, text=""))
    responses.append(httpx.Response(200, text='data: {"event_id": 9}\n\nevent: stream.end\ndata: {}\n\n'))

    assert list(client.jobs.events("job_1", cursor=3)) == [{"event_id": 5}, {"event_id": 9}]
    assert [r.url.params["cursor"] for r in requests] == ["3", "5", "5"]
    assert sleeps == [1, 1]
    assert not responses


def test_stream_end_stops_without_reconnect(api, monkeypatch):
    client, responses, requests = api
    sleeps = []
    monkeypatch.setattr(sdk.time, "sleep", sleeps.append)
    responses.append(httpx.Response(200, text="event: stream.end\ndata: {}\n\n"))

    assert list(client.runs.events("run_1")) == []
    assert len(requests) == 1
    assert sleeps == []


def test_stream_http_errors_do_not_reconnect(api, monkeypatch):
    client, responses, requests = api
    sleeps = []
    monkeypatch.setattr(sdk.time, "sleep", sleeps.append)
    responses.append(httpx.Response(403, text="forbidden"))

    with pytest.raises(RehearsalError) as error:
        list(client.jobs.events("job_1"))
    assert (error.value.status, error.value.detail) == (403, "forbidden")
    assert len(requests) == 1
    assert sleeps == []


@pytest.mark.parametrize("body", [{"detail": ["invalid"]}, ["invalid"], "invalid", 42, False, None])
def test_request_preserves_json_error_detail(api, body):
    client, responses, _ = api
    responses.append(httpx.Response(422, content=json.dumps(body)))

    with pytest.raises(RehearsalError) as error:
        client.get("/v1/jobs/job_1")
    assert error.value.status == 422
    assert error.value.detail == (body["detail"] if isinstance(body, dict) else body)


def test_request_non_json_error_is_bounded(api):
    client, responses, _ = api
    responses.append(httpx.Response(502, text="<html>" + "x" * 500))

    with pytest.raises(RehearsalError) as error:
        client.get("/v1/jobs/job_1")
    assert error.value.status == 502
    assert error.value.detail == "<html>" + "x" * 294


def test_request_success_still_returns_json(api):
    client, responses, _ = api
    responses.append(httpx.Response(200, json=[{"id": "job_1"}]))
    assert client.get("/v1/jobs") == [{"id": "job_1"}]


@pytest.mark.parametrize("timeout", [0, -1, 0.1])
def test_jobs_wait_expired_deadline_raises_timeout_without_request(api, monkeypatch, timeout):
    client, _, requests = api
    clock = iter([10, 11])
    monkeypatch.setattr(sdk.time, "monotonic", lambda: next(clock))

    with pytest.raises(TimeoutError, match="job_1"):
        client.jobs.wait("job_1", timeout_s=timeout)
    assert requests == []


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_jobs_wait_returns_terminal_job(api, monkeypatch, status):
    client, responses, _ = api
    monkeypatch.setattr(sdk.time, "monotonic", lambda: 0)
    responses.append(httpx.Response(200, json={"id": "job_1", "status": status}))
    assert client.jobs.wait("job_1") == {"id": "job_1", "status": status}


def test_jobs_wait_polls_then_times_out(api, monkeypatch):
    client, responses, requests = api
    clock = iter([0, 0, 2])
    sleeps = []
    monkeypatch.setattr(sdk.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(sdk.time, "sleep", sleeps.append)
    responses.append(httpx.Response(200, json={"status": "running"}))

    with pytest.raises(TimeoutError, match="job_1"):
        client.jobs.wait("job_1", timeout_s=1, poll_s=0.25)
    assert len(requests) == 1
    assert sleeps == [0.25]


def test_mcp_missing_optional_dependency_shows_install_hint(monkeypatch):
    original_import = builtins.__import__

    def without_mcp(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and (name == "mcp" or name.startswith("mcp.")):
            raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", without_mcp)
    with pytest.raises(SystemExit, match=r"pip install 'rehearsal-kit\[mcp\]'") as error:
        cli.main(["mcp"])
    assert "missing module: mcp" in str(error.value)
