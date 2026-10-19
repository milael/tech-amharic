"""Token auth, roles and a small per-user write rate limit.

Tokens are random 256-bit strings shown once at creation. Only their SHA-256
hash is stored, so a database leak does not leak usable credentials. A plain
hash (not bcrypt/argon2) is right here because the tokens are high-entropy;
slow hashes exist to protect low-entropy human passwords.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain import Role
from .models import User

TOKEN_PREFIX = "tam_"  # noqa: S105 - a public prefix, not a secret
COOKIE_NAME = "tam_session"


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def find_user(session: Session, token: str | None) -> User | None:
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    digest = hash_token(token)
    user = session.scalar(select(User).where(User.token_hash == digest, User.active.is_(True)))
    # Constant-time compare as defence in depth (the indexed lookup already matched).
    if user and hmac.compare_digest(user.token_hash, digest):
        return user
    return None


def create_user(session: Session, handle: str, role: Role) -> tuple[User, str]:
    token = new_token()
    user = User(handle=handle, role=role, token_hash=hash_token(token))
    session.add(user)
    session.flush()
    return user, token


def is_reviewer(user: User | None) -> bool:
    return user is not None and user.role in {Role.REVIEWER, Role.ADMIN}


class RateLimiter:
    """Sliding-window limiter, in memory and per process.

    Enough for a single container. Behind several replicas, move this to
    Redis or the reverse proxy.
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        window = self._hits[user_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True
