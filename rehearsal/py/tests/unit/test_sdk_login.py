"""`rehearsal login` storage and the order the SDK and MCP server read credentials in."""

import stat

import pytest

from rehearsal.sdk import client as sdk


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("REHEARSAL_CONFIG", str(tmp_path / "rehearsal" / "config.json"))
    monkeypatch.delenv("REHEARSAL_API_KEY", raising=False)
    monkeypatch.delenv("REHEARSAL_URL", raising=False)
    return tmp_path / "rehearsal" / "config.json"


def test_login_is_saved_for_this_user_only(config):
    sdk.save_login("https://rh.example.test/", "rh_abcd1234_secret")
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    c = sdk.Rehearsal()
    assert (c.api_key, c.base_url) == ("rh_abcd1234_secret", "https://rh.example.test")


def test_environment_wins_but_unexpanded_placeholders_do_not(config, monkeypatch):
    sdk.save_login("https://saved.example.test", "rh_saved000_key")
    monkeypatch.setenv("REHEARSAL_API_KEY", "rh_env00000_key")
    assert sdk.Rehearsal().api_key == "rh_env00000_key"
    monkeypatch.setenv("REHEARSAL_API_KEY", "${user_config.api_key}")  # a client that does not expand plugin options
    monkeypatch.setenv("REHEARSAL_URL", "")
    c = sdk.Rehearsal()
    assert (c.api_key, c.base_url) == ("rh_saved000_key", "https://saved.example.test")


def test_without_any_key_the_error_says_how_to_sign_in(config):
    with pytest.raises(ValueError, match="rehearsal login"):
        sdk.Rehearsal()


def test_mcp_server_starts_without_a_key_and_explains(config):
    pytest.importorskip("mcp")
    from rehearsal.sdk.mcp import _Client

    with pytest.raises(RuntimeError, match="rehearsal login"):
        _Client().get("/v1/me")
