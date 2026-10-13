"""Password hashing, token issuing and role-based request guards."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import ROLE_ADMIN, ROLE_PRINTING, ROLE_SALES, RevokedToken, User

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


MAX_PASSWORD_BYTES = 72  # bcrypt limit; longer passwords are rejected rather than silently truncated


def validate_new_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long (maximum 72 bytes, about 72 characters).")
    if password.isalpha() or password.isdigit():
        raise ValueError("Password must mix letters with numbers or symbols.")


def create_access_token(user: User) -> tuple[str, datetime]:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.token_expire_minutes)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "sv": user.session_version or 0,
        "jti": uuid.uuid4().hex,
        "exp": expires,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM), expires


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


# ---------------------------------------------------------------- login throttling
class LoginThrottle:
    """Blocks a username for a while after repeated failed logins (in-memory, per process)."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        self.max_failures = max_failures
        self.window = window_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        now = time.monotonic()
        fails = [t for t in self._fails.get(key, []) if now - t < self.window]
        self._fails[key] = fails
        return fails

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.max_failures

    def reserve(self, key: str) -> bool:
        """Atomically check the limit and count this attempt as a failure up front.

        Returns False if the key is blocked. Call reset() after a successful sign-in. Counting before the
        (slow) password check stops a burst of parallel requests from getting extra guesses.
        """
        with self._lock:
            recent = self._recent(key)
            if len(recent) >= self.max_failures:
                return False
            recent.append(time.monotonic())
            return True

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


login_throttle = LoginThrottle()


# ---------------------------------------------------------------- dependencies
def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def get_token_payload(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Not signed in.")
    try:
        return decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Your session has expired. Please sign in again.")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid session. Please sign in again.")


def get_current_user(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)) -> User:
    if db.get(RevokedToken, payload.get("jti", "")) is not None:
        raise _unauthorized("You have signed out. Please sign in again.")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise _unauthorized("Account is not active.")
    if user.role != payload.get("role"):
        raise _unauthorized("Your role has changed. Please sign in again.")
    if payload.get("sv", 0) != (user.session_version or 0):
        raise _unauthorized("Your session has ended because your account was changed. Please sign in again.")
    return user


def require_role(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You do not have permission for this action.")
        return user

    return dependency


require_sales = require_role(ROLE_SALES)
require_printing = require_role(ROLE_PRINTING)
require_any = require_role(ROLE_SALES, ROLE_PRINTING)  # Sales/Printing workflow actions (not Admin)
require_viewer = require_role(ROLE_SALES, ROLE_PRINTING, ROLE_ADMIN)  # read-only order views
require_admin = require_role(ROLE_ADMIN)
require_manager = require_role(ROLE_SALES, ROLE_ADMIN)  # create / edit / publish / delete orders
