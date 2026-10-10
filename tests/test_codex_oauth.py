from __future__ import annotations

import base64
import hashlib
import json
import time

import numpy as np

from roll_qr_scale import codex_oauth
from roll_qr_scale.codex_oauth import CodexOAuthClient, EncryptedCodexTokenStore
from roll_qr_scale.codex_oauth_weight import CodexOAuthWeightReader


def _jwt(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class MemoryStore:
    configured = True
    config_error = ""

    def __init__(self, value=None):
        self.value = value

    def read(self):
        return dict(self.value) if self.value else None

    def write(self, value):
        self.value = dict(value)


def test_encrypted_store_never_sends_plain_access_token(monkeypatch) -> None:
    requests = []

    def fake_http(url, **kwargs):
        requests.append((url, kwargs))
        if kwargs.get("method") == "POST":
            assert kwargs["payload"]["action"] == "codex-auth"
            return {"ok": True}
        encrypted = requests[0][1]["payload"]["encrypted_value"]
        return {"ok": True, "found": True, "encrypted_value": encrypted}

    monkeypatch.setattr(codex_oauth, "_http_json", fake_http)
    store = EncryptedCodexTokenStore(
        "https://example.supabase.co/functions/v1/ingest-measurement",
        "device-secret",
        secret_name="codex-oauth:gateway-01",
    )
    store.write({"access_token": "sensitive-access-token", "refresh_token": "refresh"})
    encoded_request = json.dumps(requests[0][1]["payload"])
    assert "sensitive-access-token" not in encoded_request
    assert store.read()["access_token"] == "sensitive-access-token"
    assert all(kwargs["attempts"] == 3 and kwargs["retry_dns_only"] for _, kwargs in requests)


def test_device_flow_verifies_server_pkce_and_saves_tokens(monkeypatch) -> None:
    store = MemoryStore()
    client = CodexOAuthClient(store)
    calls = []

    def fake_http(url, **kwargs):
        calls.append((url, kwargs))
        if url == codex_oauth.DEVICE_CODE_URL:
            return {"device_auth_id": "device-1", "user_code": "ABCD-EFGH", "interval": 1}
        if url == codex_oauth.DEVICE_TOKEN_URL:
            verifier = "server-verifier"
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            ).decode().rstrip("=")
            return {
                "authorization_code": "authorization-code",
                "code_verifier": verifier,
                "code_challenge": challenge,
            }
        if url == codex_oauth.OAUTH_TOKEN_URL:
            return {
                "access_token": _jwt({
                    "exp": int(time.time()) + 3600,
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"},
                }),
                "refresh_token": "refresh-1",
            }
        raise AssertionError(url)

    monkeypatch.setattr(codex_oauth, "_http_json", fake_http)
    started = client.start_device_login()
    client._sessions[str(started["session_id"])].next_poll_at = 0
    result = client.poll_device_login(str(started["session_id"]))
    assert started["user_code"] == "ABCD-EFGH"
    assert result["authenticated"] is True
    assert store.value["account_id"] == "acct-1"
    token_payload = calls[-1][1]["payload"]
    assert token_payload["redirect_uri"] == codex_oauth.DEVICE_REDIRECT_URI
    assert token_payload["code_verifier"] == "server-verifier"


def test_device_start_accepts_cli_usercode_alias(monkeypatch) -> None:
    store = MemoryStore()
    client = CodexOAuthClient(store)

    def fake_http(url, **kwargs):
        assert kwargs["attempts"] == 3
        return {"device_auth_id": "device-2", "usercode": "WXYZ-12345", "interval": "5"}

    monkeypatch.setattr(codex_oauth, "_http_json", fake_http)
    started = client.start_device_login()
    assert started["user_code"] == "WXYZ-12345"
    assert started["interval"] == 5.0


def test_device_start_can_force_login_when_already_authenticated(monkeypatch) -> None:
    store = MemoryStore(
        {
            "access_token": _jwt({"exp": int(time.time()) + 3600}),
            "refresh_token": "refresh-existing",
        }
    )
    client = CodexOAuthClient(store)

    def fake_http(url, **kwargs):
        assert url == codex_oauth.DEVICE_CODE_URL
        return {"device_auth_id": "device-new", "user_code": "NEW-LOGIN", "interval": 5}

    monkeypatch.setattr(codex_oauth, "_http_json", fake_http)
    current = client.start_device_login()
    forced = client.start_device_login(force=True)

    assert current["authenticated"] is True
    assert current["started"] is False
    assert forced["started"] is True
    assert forced["user_code"] == "NEW-LOGIN"


def test_oauth_weight_reader_parses_fixed_two_decimal_result(monkeypatch) -> None:
    reader = CodexOAuthWeightReader(CodexOAuthClient(MemoryStore()), model="test-model")
    monkeypatch.setattr(
        reader,
        "_request",
        lambda frames: '{"weight_readable":true,"weight_digits":"1304","all_frames_agree":true}',
    )
    result = reader.read([np.zeros((40, 80, 3), dtype=np.uint8)], unit="kg")
    assert result.readable is True
    assert result.value == 13.04
    assert result.raw.startswith("CODEX-OAUTH:13.04")


def test_http_json_retries_on_urlerror_and_succeeds(monkeypatch) -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if len(calls) < 2:
            import socket
            import urllib.error
            raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        import io
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(codex_oauth.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(codex_oauth.time, "sleep", lambda s: None)
    res = codex_oauth._http_json("https://example.supabase.co/test", attempts=3)
    assert res == {"ok": True}
    assert len(calls) == 2


def test_http_json_reports_hostname_on_dns_failure(monkeypatch) -> None:
    import pytest
    import socket
    import urllib.error

    def fake_urlopen(request, timeout):
        raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))

    monkeypatch.setattr(codex_oauth.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(codex_oauth.time, "sleep", lambda s: None)
    with pytest.raises(codex_oauth.CodexOAuthError, match=r"Không phân giải được tên miền example\.supabase\.co"):
        codex_oauth._http_json("https://example.supabase.co/test", attempts=2)


def test_encrypted_store_normalizes_pasted_url_and_preserves_query(monkeypatch):
    calls = []
    monkeypatch.setattr(codex_oauth, "_http_json", lambda url, **kwargs: calls.append(url) or {"found": False})
    store = EncryptedCodexTokenStore(
        '[API](https://example.supabase.co/ingest?station=1)', "device-secret", secret_name="gemini-api-key:gateway-01",
    )
    assert store.configured
    assert store.read() is None
    assert calls[0].startswith("https://example.supabase.co/ingest?station=1&action=")


def test_encrypted_store_does_not_retry_http_failure_or_ambiguous_timeout(monkeypatch):
    import io
    import pytest
    import urllib.error

    calls = []
    errors = [
        urllib.error.HTTPError("https://example.supabase.co/ingest", 503, "Unavailable", {}, io.BytesIO(b'{}')),
        urllib.error.URLError(TimeoutError("timed out")),
    ]
    store = EncryptedCodexTokenStore("https://example.supabase.co/ingest", "device-secret", secret_name="gemini-api-key:test")
    for error in errors:
        calls.clear()

        def fail(request, timeout):
            calls.append(request)
            raise error

        monkeypatch.setattr(codex_oauth.urllib.request, "urlopen", fail)
        with pytest.raises(codex_oauth.CodexOAuthError):
            store.write({"api_key": "dummy-test-secret"})
        assert len(calls) == 1


def test_encrypted_store_recovers_dns_failure_without_sending_plain_key(monkeypatch):
    import io
    import socket
    import urllib.error

    calls = []

    def send(request, timeout):
        calls.append(request)
        if len(calls) < 3:
            raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(codex_oauth.urllib.request, "urlopen", send)
    monkeypatch.setattr(codex_oauth.time, "sleep", lambda seconds: None)
    store = EncryptedCodexTokenStore("https://example.supabase.co/ingest", "device-secret", secret_name="gemini-api-key:test")
    store.write({"api_key": "dummy-test-secret"})
    assert len(calls) == 3
    assert all(b"dummy-test-secret" not in request.data for request in calls)
    assert calls[0].data == calls[-1].data
