"""Testing any agent by its URL: the address check, the sealed key, and one turn against a stand-in endpoint."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from rehearsal.agents import endpoint
from rehearsal.config import settings


@pytest.fixture
def private_allowed(monkeypatch):
    monkeypatch.setenv("REHEARSAL_ALLOW_PRIVATE_AGENT_URLS", "on")
    settings.cache_clear() if hasattr(settings, "cache_clear") else None
    yield
    monkeypatch.delenv("REHEARSAL_ALLOW_PRIVATE_AGENT_URLS")
    settings.cache_clear() if hasattr(settings, "cache_clear") else None


def test_internal_addresses_are_refused(monkeypatch):
    monkeypatch.delenv("REHEARSAL_ALLOW_PRIVATE_AGENT_URLS", raising=False)
    for url in ("https://127.0.0.1/v1", "https://169.254.169.254/latest", "https://10.0.0.5/v1", "https://localhost/v1", "https://[::1]/v1"):
        assert "private or internal" in (endpoint.url_problem(url) or ""), url
    assert endpoint.url_problem("http://example.com/v1") == "the agent's URL must use https"
    assert endpoint.url_problem("ftp://example.com") and endpoint.url_problem("https://user:pw@example.com/v1")


def test_a_private_address_is_allowed_only_on_a_server_that_says_so(private_allowed):
    assert endpoint.url_problem("http://127.0.0.1:9/v1") is None


def test_keys_are_sealed():
    token = endpoint.seal("sk-test-123")
    assert "sk-test-123" not in token and endpoint.unseal(token) == "sk-test-123"


def test_one_turn_goes_to_the_agent_and_costs_nothing(private_allowed):
    seen = {}

    class Agent(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = {"id": "x", "object": "chat.completion", "created": 0, "model": "mine", "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
                     "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
                         {"id": "c1", "type": "function", "function": {"name": "close_issue", "arguments": "{\"number\": 4}"}}]}}]}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Agent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        tools = [{"type": "function", "function": {"name": "close_issue", "parameters": {"type": "object", "properties": {"number": {"type": "integer"}}}}}]
        reply = endpoint.chat_endpoint(f"http://127.0.0.1:{server.server_port}/v1", "mine", "sk-test", [{"role": "user", "content": "close #4"}],
                                       tools=tools, temperature=0.2, max_tokens=100)
    finally:
        server.shutdown()
    assert seen["auth"] == "Bearer sk-test" and seen["body"]["tools"][0]["function"]["name"] == "close_issue" and seen["body"]["model"] == "mine"
    assert [(c.name, c.arguments) for c in reply.tool_calls] == [("close_issue", {"number": 4})]
    assert reply.cost_usd == 0.0 and reply.provider == "endpoint" and reply.prompt_tokens == 11


def test_an_unreachable_agent_is_an_endpoint_error(private_allowed):
    with pytest.raises(endpoint.EndpointError):
        endpoint.chat_endpoint("http://127.0.0.1:9/v1", "", None, [{"role": "user", "content": "hi"}], tools=None, temperature=0, max_tokens=10)
