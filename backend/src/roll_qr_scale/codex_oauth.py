from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .api_client import normalize_remote_url


CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEVICE_CODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
DEVICE_VERIFICATION_URL = "https://auth.openai.com/codex/device"
DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
OAUTH_SCOPE = "openid profile email offline_access"


class CodexOAuthError(RuntimeError):
    pass


class CodexOAuthHTTPError(CodexOAuthError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    attempts: int = 1,
    retry_dns_only: bool = False,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {
        "accept": "application/json",
        "user-agent": "codex_cli_rs/0.147.0",
        **(headers or {}),
    }
    if body is not None:
        request_headers["content-type"] = "application/json"
    total_attempts = max(1, min(int(attempts), 4))
    raw = ""
    for attempt in range(total_attempts):
        request = urllib.request.Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if not retry_dns_only and 500 <= exc.code <= 599 and attempt + 1 < total_attempts:
                time.sleep(0.35 * (2**attempt))
                continue
            try:
                parsed = json.loads(detail)
                error = parsed.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("code") or detail)
                else:
                    message = str(parsed.get("message") or error or detail)
            except (ValueError, AttributeError):
                message = detail or str(exc)
            raise CodexOAuthHTTPError(exc.code, message[:500]) from exc
        except urllib.error.URLError as exc:
            dns_error = isinstance(exc.reason, socket.gaierror) or "getaddrinfo" in str(exc.reason)
            if (not retry_dns_only or dns_error) and attempt + 1 < total_attempts:
                time.sleep(0.35 * (2**attempt))
                continue
            host = urllib.parse.urlsplit(url).hostname or "máy chủ"
            if dns_error:
                raise CodexOAuthError(
                    f"Không phân giải được tên miền {host} sau {total_attempts} lần thử: {exc.reason}"
                ) from exc
            raise CodexOAuthError(f"Không kết nối được máy chủ {host}: {exc.reason}") from exc
    host = urllib.parse.urlsplit(url).hostname or "máy chủ"
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise CodexOAuthError(f"Máy chủ {host} trả về dữ liệu không hợp lệ") from exc
    if not isinstance(parsed, dict):
        raise CodexOAuthError(f"Máy chủ {host} trả về dữ liệu không hợp lệ")
    return parsed


def _jwt_claims(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeError):
        return {}


def _account_id(tokens: dict[str, Any]) -> str:
    for token_name in ("id_token", "access_token"):
        claims = _jwt_claims(str(tokens.get(token_name) or ""))
        auth = claims.get("https://api.openai.com/auth")
        if isinstance(auth, dict) and auth.get("chatgpt_account_id"):
            return str(auth["chatgpt_account_id"])
        if claims.get("chatgpt_account_id"):
            return str(claims["chatgpt_account_id"])
    return str(tokens.get("account_id") or "")


def _expires_at(tokens: dict[str, Any]) -> int:
    access_claims = _jwt_claims(str(tokens.get("access_token") or ""))
    try:
        if access_claims.get("exp"):
            return int(access_claims["exp"])
        if tokens.get("expires_at"):
            return int(tokens["expires_at"])
    except (TypeError, ValueError):
        return 0
    return 0


class EncryptedCodexTokenStore:
    """Persist one encrypted backend secret through the protected ingest function."""

    def __init__(
        self,
        api_url: str | None,
        device_token: str | None,
        *,
        secret_name: str,
        secret_action: str = "codex-auth",
        encryption_key: str = "",
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_url = (api_url or "").strip()
        self.device_token = (device_token or "").strip()
        self.secret_name = secret_name.strip()
        self.secret_action = secret_action.strip()
        self.timeout_seconds = float(timeout_seconds)
        self._config_error = ""
        self._fernet: Fernet | None = None
        if not self.api_url or not self.device_token:
            self._config_error = "Thiếu ROLL_SCALE_API_URL hoặc ROLL_SCALE_DEVICE_TOKEN"
            return
        try:
            self.api_url = normalize_remote_url(self.api_url)
        except ValueError as exc:
            self._config_error = str(exc)
            return
        try:
            key = encryption_key.strip().encode("ascii") if encryption_key.strip() else self._derived_key()
            self._fernet = Fernet(key)
        except (ValueError, UnicodeError) as exc:
            self._config_error = f"ROLL_SCALE_CODEX_TOKEN_KEY không hợp lệ: {exc}"

    def _derived_key(self) -> bytes:
        material = f"roll-scale-codex-oauth-v1:{self.device_token}".encode("utf-8")
        return base64.urlsafe_b64encode(hashlib.sha256(material).digest())

    @property
    def configured(self) -> bool:
        return self._fernet is not None and not self._config_error

    @property
    def config_error(self) -> str:
        return self._config_error

    def _headers(self) -> dict[str, str]:
        return {"x-device-token": self.device_token}

    def read(self) -> dict[str, Any] | None:
        if not self.configured or self._fernet is None:
            raise CodexOAuthError(self.config_error or "Kho bí mật mã hóa chưa cấu hình")
        query = urllib.parse.urlencode({"action": self.secret_action, "name": self.secret_name})
        result = _http_json(
            f"{self.api_url}{'&' if '?' in self.api_url else '?'}{query}",
            headers=self._headers(),
            timeout=self.timeout_seconds,
            attempts=3,
            retry_dns_only=True,
        )
        if not result.get("found"):
            return None
        encrypted = str(result.get("encrypted_value") or "")
        try:
            plaintext = self._fernet.decrypt(encrypted.encode("ascii"))
            value = json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise CodexOAuthError(
                "Không giải mã được bí mật backend; token thiết bị hoặc khóa mã hóa đã thay đổi"
            ) from exc
        if not isinstance(value, dict):
            raise CodexOAuthError("Dữ liệu bí mật backend không hợp lệ")
        return value

    def write(self, value: dict[str, Any]) -> None:
        if not self.configured or self._fernet is None:
            raise CodexOAuthError(self.config_error or "Kho bí mật mã hóa chưa cấu hình")
        encrypted = self._fernet.encrypt(
            json.dumps(value, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        result = _http_json(
            self.api_url,
            method="POST",
            payload={
                "action": self.secret_action,
                "name": self.secret_name,
                "encrypted_value": encrypted,
            },
            headers=self._headers(),
            timeout=self.timeout_seconds,
            attempts=3,
            retry_dns_only=True,
        )
        if not result.get("ok"):
            raise CodexOAuthError("Supabase không lưu được bí mật đã mã hóa")


@dataclass
class _DeviceSession:
    device_auth_id: str
    user_code: str
    interval_seconds: float
    expires_at: float
    next_poll_at: float = 0.0


class CodexOAuthClient:
    def __init__(
        self,
        store: EncryptedCodexTokenStore,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.store = store
        self.timeout_seconds = float(timeout_seconds)
        self._lock = threading.RLock()
        self._sessions: dict[str, _DeviceSession] = {}
        self._cached_tokens: tuple[float, dict[str, Any] | None] | None = None

    @staticmethod
    def _pkce() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return verifier, challenge

    def _load(self, *, refresh_cache: bool = False) -> dict[str, Any] | None:
        with self._lock:
            if (
                not refresh_cache
                and self._cached_tokens is not None
                and time.monotonic() - self._cached_tokens[0] < 10.0
            ):
                return dict(self._cached_tokens[1]) if self._cached_tokens[1] else None
        tokens = self.store.read()
        with self._lock:
            self._cached_tokens = (time.monotonic(), dict(tokens) if tokens else None)
        return tokens

    def _save(self, tokens: dict[str, Any]) -> None:
        tokens = dict(tokens)
        tokens["account_id"] = _account_id(tokens)
        tokens["expires_at"] = _expires_at(tokens)
        tokens["updated_at"] = int(time.time())
        self.store.write(tokens)
        with self._lock:
            self._cached_tokens = (time.monotonic(), dict(tokens))

    def status(self) -> dict[str, object]:
        if not self.store.configured:
            return {
                "configured": False,
                "authenticated": False,
                "available": False,
                "auth_method": "device_code",
                "message": self.store.config_error,
            }
        try:
            tokens = self._load()
            if not tokens:
                return {
                    "configured": True,
                    "authenticated": False,
                    "available": False,
                    "auth_method": "device_code",
                    "message": "Codex chưa đăng nhập bằng ChatGPT",
                }
            expires_at = _expires_at(tokens)
            expired = bool(expires_at and expires_at <= int(time.time()) + 30)
            renewable = bool(tokens.get("refresh_token"))
            return {
                "configured": True,
                "authenticated": bool(tokens.get("access_token")) and (not expired or renewable),
                "available": bool(tokens.get("access_token")) and (not expired or renewable),
                "expired": expired,
                "account_id": _account_id(tokens) or None,
                "auth_method": "device_code",
                "message": "Codex đã đăng nhập bằng ChatGPT" if not expired else "Codex sẽ làm mới đăng nhập khi đọc cân",
            }
        except Exception as exc:
            return {
                "configured": True,
                "authenticated": False,
                "available": False,
                "auth_method": "device_code",
                "message": f"{type(exc).__name__}: {str(exc).strip()}"[:300],
            }

    def start_device_login(self, *, force: bool = False) -> dict[str, object]:
        if not self.store.configured:
            raise CodexOAuthError(self.store.config_error or "Kho token Codex chưa cấu hình")
        current = self.status()
        if not force and current.get("authenticated") and not current.get("expired"):
            return {
                "started": False,
                "authenticated": True,
                "message": "Codex đã đăng nhập bằng ChatGPT",
            }
        response = _http_json(
            DEVICE_CODE_URL,
            method="POST",
            payload={"client_id": CODEX_CLIENT_ID},
            timeout=self.timeout_seconds,
            attempts=3,
        )
        device_auth_id = str(response.get("device_auth_id") or "")
        user_code = str(response.get("user_code") or response.get("usercode") or "")
        if not device_auth_id or not user_code:
            raise CodexOAuthError("OpenAI không trả về mã đăng nhập thiết bị")
        interval = max(2.0, min(float(response.get("interval") or 5), 15.0))
        expires_in = max(60, min(int(response.get("expires_in") or 900), 1800))
        session_id = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            self._sessions = {
                key: value for key, value in self._sessions.items() if value.expires_at > now
            }
            self._sessions[session_id] = _DeviceSession(
                device_auth_id=device_auth_id,
                user_code=user_code,
                interval_seconds=interval,
                expires_at=now + expires_in,
            )
        return {
            "started": True,
            "authenticated": False,
            "flow": "device_code",
            "session_id": session_id,
            "user_code": user_code,
            "verification_url": DEVICE_VERIFICATION_URL,
            "interval": interval,
            "expires_in": expires_in,
            "message": "Mở trang OpenAI và nhập mã thiết bị",
        }

    def poll_device_login(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise CodexOAuthError("Phiên đăng nhập không tồn tại hoặc đã hết hạn")
        now = time.monotonic()
        if now >= session.expires_at:
            with self._lock:
                self._sessions.pop(session_id, None)
            raise CodexOAuthError("Mã đăng nhập Codex đã hết hạn")
        if now < session.next_poll_at:
            return {"pending": True, "authenticated": False, "message": "Đang chờ xác nhận OpenAI"}
        session.next_poll_at = now + session.interval_seconds
        try:
            authorization = _http_json(
                DEVICE_TOKEN_URL,
                method="POST",
                payload={
                    "device_auth_id": session.device_auth_id,
                    "user_code": session.user_code,
                },
                timeout=self.timeout_seconds,
            )
        except CodexOAuthHTTPError as exc:
            if exc.status in {403, 404}:
                return {"pending": True, "authenticated": False, "message": "Đang chờ xác nhận OpenAI"}
            raise
        returned_verifier = str(authorization.get("code_verifier") or "")
        returned_challenge = str(authorization.get("code_challenge") or "")
        authorization_code = str(authorization.get("authorization_code") or "")
        if not returned_verifier or not returned_challenge or not authorization_code:
            raise CodexOAuthError("OpenAI trả về xác nhận PKCE không hợp lệ")
        digest = hashlib.sha256(returned_verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        if not secrets.compare_digest(expected_challenge, returned_challenge):
            raise CodexOAuthError("Xác nhận PKCE không khớp; đã hủy đăng nhập")
        tokens = _http_json(
            OAUTH_TOKEN_URL,
            method="POST",
            payload={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": DEVICE_REDIRECT_URI,
                "client_id": CODEX_CLIENT_ID,
                "code_verifier": returned_verifier,
            },
            timeout=self.timeout_seconds,
        )
        if not tokens.get("access_token"):
            raise CodexOAuthError("OpenAI không trả về access token")
        self._save(tokens)
        with self._lock:
            self._sessions.pop(session_id, None)
        return {
            "pending": False,
            "authenticated": True,
            "message": "Đăng nhập ChatGPT/Codex thành công",
        }

    def access(self) -> tuple[str, str]:
        with self._lock:
            tokens = self._load()
            if not tokens or not tokens.get("access_token"):
                raise CodexOAuthError("Codex chưa đăng nhập bằng ChatGPT")
            expires_at = _expires_at(tokens)
            if expires_at and expires_at <= int(time.time()) + 60:
                refresh_token = str(tokens.get("refresh_token") or "")
                if not refresh_token:
                    raise CodexOAuthError("Đăng nhập Codex đã hết hạn; cần đăng nhập lại")
                refreshed = _http_json(
                    OAUTH_TOKEN_URL,
                    method="POST",
                    payload={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": CODEX_CLIENT_ID,
                        "scope": OAUTH_SCOPE,
                    },
                    timeout=self.timeout_seconds,
                )
                if not refreshed.get("refresh_token"):
                    refreshed["refresh_token"] = refresh_token
                self._save(refreshed)
                tokens = refreshed
            account_id = _account_id(tokens)
            if not account_id:
                raise CodexOAuthError("Không tìm thấy ChatGPT account ID trong token")
            return str(tokens["access_token"]), account_id
