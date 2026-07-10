import math
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt.exceptions import PyJWTError

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    ALGORITHM,
    COOKIE_NAME,
    JWT_AUDIENCE,
    JWT_ISSUER,
    JWT_LEEWAY_SECONDS,
    LOGIN_RATE_LIMIT_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    SECRET_KEY,
    TOKEN_VERSION,
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (TypeError, ValueError):
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


ADMIN_PASSWORD_HASH = get_password_hash(ADMIN_PASSWORD)


def verify_admin_credentials(username: str, password: str) -> bool:
    # 无论用户名是否正确都执行 bcrypt，避免通过响应耗时枚举管理员用户名。
    password_matches = verify_password(password, ADMIN_PASSWORD_HASH)
    username_matches = username == ADMIN_USERNAME
    return username_matches and password_matches


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = data.copy()
    payload.update(
        {
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "iat": now,
            "nbf": now,
            "exp": expire,
            "jti": uuid.uuid4().hex,
            "ver": TOKEN_VERSION,
            "type": "access",
        }
    )
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


_revoked_tokens: dict[str, float] = {}
_revoked_tokens_lock = threading.Lock()


def _prune_revoked_tokens(now: float) -> None:
    expired_jtis = [jti for jti, expires_at in _revoked_tokens.items() if expires_at <= now]
    for jti in expired_jtis:
        _revoked_tokens.pop(jti, None)


def _is_token_revoked(jti: str) -> bool:
    now = time.time()
    with _revoked_tokens_lock:
        _prune_revoked_tokens(now)
        return jti in _revoked_tokens


def decode_access_token(token: str, *, allow_revoked: bool = False) -> dict:
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
        leeway=JWT_LEEWAY_SECONDS,
        options={
            "require": ["sub", "iss", "aud", "iat", "nbf", "exp", "jti", "ver", "type"],
        },
    )

    username = payload.get("sub")
    jti = payload.get("jti")
    if username != ADMIN_USERNAME:
        raise jwt.InvalidTokenError("Unexpected token subject")
    if payload.get("ver") != TOKEN_VERSION:
        raise jwt.InvalidTokenError("Token version is no longer valid")
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Unexpected token type")
    if not isinstance(jti, str) or not jti:
        raise jwt.InvalidTokenError("Token jti is invalid")
    if not allow_revoked and _is_token_revoked(jti):
        raise jwt.InvalidTokenError("Token has been revoked")
    return payload


def revoke_access_token(token: str) -> None:
    try:
        payload = decode_access_token(token, allow_revoked=True)
        jti = payload["jti"]
        expires_at = float(payload["exp"])
    except (PyJWTError, KeyError, TypeError, ValueError):
        return

    with _revoked_tokens_lock:
        _prune_revoked_tokens(time.time())
        _revoked_tokens[jti] = expires_at


def get_request_token(request: Request) -> Optional[str]:
    # 显式 Authorization 头优先，避免失效 Cookie 阻断合法 API 客户端。
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, separator, credentials = auth_header.partition(" ")
        if separator and scheme.lower() == "bearer" and credentials.strip():
            return credentials.strip()
        return None
    return request.cookies.get(COOKIE_NAME)


async def get_current_user_optional(request: Request) -> Optional[str]:
    token = get_request_token(request)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        return payload["sub"]
    except (PyJWTError, KeyError, TypeError, ValueError):
        return None


async def get_current_user(
    username: Optional[str] = Depends(get_current_user_optional),
) -> str:
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


_login_attempts: dict[str, deque[float]] = defaultdict(deque)
_login_attempts_lock = threading.Lock()
_MAX_LOGIN_RATE_LIMIT_KEYS = 10_000


def build_login_rate_limit_key(request: Request, username: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{client_host}:{username.casefold()}"


def _prune_login_attempts(cutoff: float) -> None:
    for existing_key in list(_login_attempts):
        attempts = _login_attempts[existing_key]
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            _login_attempts.pop(existing_key, None)

    while len(_login_attempts) >= _MAX_LOGIN_RATE_LIMIT_KEYS:
        oldest_key = next(iter(_login_attempts))
        _login_attempts.pop(oldest_key, None)


def get_login_retry_after(key: str) -> int:
    now = time.monotonic()
    cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    with _login_attempts_lock:
        _prune_login_attempts(cutoff)
        attempts = _login_attempts[key]
        if len(attempts) < LOGIN_RATE_LIMIT_ATTEMPTS:
            if not attempts:
                _login_attempts.pop(key, None)
            return 0
        return max(1, math.ceil(attempts[0] + LOGIN_RATE_LIMIT_WINDOW_SECONDS - now))


def record_login_failure(key: str) -> None:
    now = time.monotonic()
    cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    with _login_attempts_lock:
        _prune_login_attempts(cutoff)
        attempts = _login_attempts[key]
        attempts.append(now)


def clear_login_failures(key: str) -> None:
    with _login_attempts_lock:
        _login_attempts.pop(key, None)
