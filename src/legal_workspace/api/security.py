"""Authentication (JWT), roles and a small in-memory rate limiter."""

from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Request

from ..config import Settings, get_settings
from ..errors import Forbidden, RateLimited, Unauthorized

ROLES = ("viewer", "analyst", "admin")
_RANK = {r: i for i, r in enumerate(ROLES)}


@dataclass(frozen=True)
class User:
    username: str
    role: str

    def can(self, minimum: str) -> bool:
        return _RANK.get(self.role, -1) >= _RANK[minimum]


LOCAL_USER = User("local", "admin")


def parse_users(spec: str) -> dict[str, tuple[str, str]]:
    """'alice:pw:analyst,bob:pw2' -> {'alice': ('pw', 'analyst'), 'bob': ('pw2', 'admin')}; the role defaults to admin."""
    out: dict[str, tuple[str, str]] = {}
    for part in spec.split(","):
        bits = [b.strip() for b in part.split(":")]
        if len(bits) >= 2 and bits[0] and bits[1]:
            role = bits[2] if len(bits) > 2 and bits[2] in ROLES else "admin"
            out[bits[0]] = (bits[1], role)
    return out


def authenticate(username: str, password: str, s: Settings) -> User | None:
    users = parse_users(s.auth_users)
    entry = users.get(username)
    expected = entry[0] if entry else "x" * 16  # constant-time comparison even for unknown users
    ok = hmac.compare_digest(password.encode(), expected.encode())
    return User(username, entry[1]) if entry and ok else None


def issue_token(user: User, s: Settings) -> tuple[str, int]:
    ttl = s.jwt_ttl_minutes * 60
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": user.username, "role": user.role, "iat": now, "exp": now + timedelta(seconds=ttl)},
        s.jwt_secret,
        algorithm="HS256",
    )
    return token, ttl


def decode_token(token: str, s: Settings) -> User:
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("the session has expired; sign in again") from e
    except jwt.PyJWTError as e:
        raise Unauthorized("invalid credentials") from e
    role = claims.get("role")
    if role not in ROLES:
        raise Unauthorized("invalid credentials")
    return User(str(claims["sub"]), role)


def current_user(request: Request) -> User:
    s = get_settings()
    if not s.auth_enabled:
        return LOCAL_USER
    header = request.headers.get("authorization", "")
    token = (
        header[7:] if header.lower().startswith("bearer ") else request.query_params.get("access_token")
    )  # query token: image/PDF links
    if not token:
        raise Unauthorized()
    return decode_token(token, s)


def require(minimum: str):  # noqa: ANN201
    def dep(user: User = Depends(current_user)) -> User:  # noqa: B008
        if not user.can(minimum):
            raise Forbidden(f"this action needs the {minimum!r} role; you are {user.role!r}")
        return user

    return dep


class RateLimiter:
    """Sliding window per key. `limit <= 0` disables it."""

    def __init__(self, limit: int, window_s: float = 60.0, clock=time.monotonic) -> None:  # noqa: ANN001
        self.limit, self.window, self.clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        if self.limit <= 0:
            return
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise RateLimited(
                    f"more than {self.limit} requests per {int(self.window)} seconds",
                    retry_after=int(self.window - (now - q[0])) + 1,
                )
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
