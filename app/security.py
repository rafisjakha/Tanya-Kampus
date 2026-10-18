"""Autentikasi admin (bcrypt + JWT) dan kunci API untuk bot."""
from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import DEFAULT_SECRET, Settings, get_settings

_bearer = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"


# --- password ---------------------------------------------------------------------------------

def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("Password maksimal 72 byte (batas bcrypt).")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except ValueError:
        return False


# --- token ------------------------------------------------------------------------------------

def create_token(username: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.token_expire_minutes)
    return jwt.encode({"sub": username, "exp": expire}, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    return str(payload["sub"])


def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    """Dependency: wajib login admin. Mengembalikan username."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Belum login.")
    try:
        return decode_token(creds.credentials, settings)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid atau kedaluwarsa.")


# --- kunci API bot ----------------------------------------------------------------------------

def _key_matches(provided: str | None, expected: str) -> bool:
    return provided is not None and hmac.compare_digest(provided, expected)


def bot_or_open(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Untuk /api/ask. Kalau BOT_API_KEY diset, header X-API-Key wajib cocok."""
    if settings.bot_api_key and not _key_matches(x_api_key, settings.bot_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key salah.")


def bot_required(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Untuk endpoint bot yang menulis data. BOT_API_KEY wajib diset dan cocok."""
    if not settings.bot_api_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Endpoint ini nonaktif: BOT_API_KEY belum diset.")
    if not _key_matches(x_api_key, settings.bot_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key salah.")


# --- pembatas percobaan login (in-memory, cukup untuk satu instance) ------------------------

class LoginLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_attempts:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Terlalu banyak percobaan login. Coba lagi sebentar.")

    def record_failure(self, key: str) -> None:
        self._hits[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


login_limiter = LoginLimiter()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def warn_if_insecure(settings: Settings) -> list[str]:
    warnings = []
    if settings.secret_key == DEFAULT_SECRET:
        warnings.append("SECRET_KEY masih nilai default. Ganti di .env sebelum dipakai di luar laptop sendiri.")
    elif len(settings.secret_key) < 32:
        warnings.append("SECRET_KEY terlalu pendek (disarankan 32 karakter atau lebih).")
    if not settings.bot_api_key:
        warnings.append("BOT_API_KEY belum diset: endpoint /api/ask terbuka untuk siapa saja yang bisa menjangkau server.")
    return warnings
