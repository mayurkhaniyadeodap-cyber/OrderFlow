"""Login, logout, current user and client configuration."""
from __future__ import annotations

import secrets
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..database import get_db
from ..models import RevokedToken, User
from ..schemas import LoginRequest, LoginResponse, UserOut
from ..security import create_access_token, hash_password, get_current_user, get_token_payload, login_throttle, verify_password

router = APIRouter(tags=["auth"])


class _WindowCap:
    """Allow at most `limit` audit rows per `window` seconds; count the rest and report them on the next row."""

    def __init__(self, limit: int = 20, window: float = 600):
        self.limit, self.window = limit, window
        self.started, self.used, self.suppressed = 0.0, 0, 0
        self._lock = threading.Lock()

    def allow(self) -> int | None:
        """Returns None if this row should be skipped, else the number of rows suppressed before it."""
        with self._lock:
            now = time.monotonic()
            if now - self.started >= self.window:
                self.started, self.used = now, 0
            if self.used >= self.limit:
                self.suppressed += 1
                return None
            self.used += 1
            suppressed, self.suppressed = self.suppressed, 0
            return suppressed


_unknown_failures = _WindowCap()
# A valid hash so unknown usernames take the same time as wrong passwords.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    username = body.username.strip().lower()
    if not login_throttle.reserve(username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many failed sign-in attempts. Wait 5 minutes and try again.")
    user = db.scalar(select(User).where(User.username == username))
    valid = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not valid or not user.is_active:  # the failure was already counted by reserve()
        # Never record the typed text for unknown accounts: people sometimes type a password into the username box.
        if user is None:
            # Unauthenticated callers must not be able to fill the audit log: individual rows are capped per window.
            suppressed = _unknown_failures.allow()
            if suppressed is not None:
                detail = "Sign-in failed: unknown username."
                if suppressed:
                    detail += f" ({suppressed} earlier attempt(s) with unknown usernames were not recorded individually.)"
                audit.record(db, "(unknown user)", "login_failed", None, detail)
        else:
            reason = "inactive account" if valid else "wrong password"
            audit.record(db, user.username, "login_failed", user.username, f"Sign-in failed: {reason}.")
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password.")
    login_throttle.reset(username)
    user.last_login_at = datetime.now(timezone.utc)
    audit.record(db, user, "login", user.username, "Signed in.")
    db.commit()
    token, expires = create_access_token(user)
    return LoginResponse(access_token=token, expires_at=expires, user=UserOut.model_validate(user))


@router.post("/logout")
def logout(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))  # housekeeping
    jti = payload.get("jti")
    if jti and db.get(RevokedToken, jti) is None:
        db.add(RevokedToken(jti=jti, expires_at=datetime.fromtimestamp(payload["exp"], timezone.utc)))
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "user": UserOut.model_validate(user).model_dump(),
        "config": {
            "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
            "timezone": str(settings.timezone),
        },
    }
