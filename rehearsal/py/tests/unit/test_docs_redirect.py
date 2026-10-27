"""/docs leads to the documentation site when one is set, and to the API reference otherwise."""

from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from rehearsal.api import app as api


def test_docs_goes_to_the_documentation_site_or_the_api_reference(monkeypatch):
    client = TestClient(api.app, follow_redirects=False)
    monkeypatch.setattr(api, "settings", lambda: NS(docs_url="https://docs.example.com"))
    for path in ("/docs", "/docs/"):
        r = client.get(path)
        assert r.status_code == 307 and r.headers["location"] == "https://docs.example.com"
    monkeypatch.setattr(api, "settings", lambda: NS(docs_url=""))
    assert client.get("/docs").headers["location"] == "/api/docs"
    assert "swagger" in client.get("/api/docs").text.lower()
