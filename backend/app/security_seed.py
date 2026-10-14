"""Login accounts from environment variables (backend/.env): one Admin, Sales and Printing account.

No passwords are written in the code. A password from the environment is checked against the password rule and
stored only as a bcrypt hash; it is never logged. An account is created only when NO account with that role exists
yet, so existing accounts are never changed, reset or recreated (change passwords in Admin -> Users).
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ROLE_ADMIN, ROLE_PRINTING, ROLE_SALES, User
from .security import hash_password

# Usernames are stored normalised (see normalize_username): lower-case, single spaces, no leading/trailing spaces.
USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._ -]{2,31}")
USERNAME_RULE = "3-32 characters: letters a-z, numbers, spaces, dot, underscore or hyphen (start with a letter or number)"


def normalize_username(value: str | None) -> str:
    """The one form a username is stored and looked up in: 'Dhruv  Bhojani ' -> 'dhruv bhojani'."""
    return " ".join((value or "").split()).lower()

# role, label, environment prefix (<PREFIX>_USERNAME / <PREFIX>_PASSWORD), full name of a new account
ENV_ACCOUNTS = [
    (ROLE_ADMIN, "Admin", "ADMIN", "Administrator"),
    (ROLE_SALES, "Sales", "SALES", "Sales User"),
    (ROLE_PRINTING, "Printing", "PRINTING", "Printing User"),
]
SKIPPED = "skipped: "


def bootstrap_accounts_from_env(db: Session, environ: Mapping[str, str] | None = None) -> list[str]:
    """Create each configured account whose role has no account yet. Returns one status message per role."""
    environ = os.environ if environ is None else environ
    return [_bootstrap(db, role, label, prefix, full_name,
                       environ.get(f"{prefix}_USERNAME"), environ.get(f"{prefix}_PASSWORD"))
            for role, label, prefix, full_name in ENV_ACCOUNTS]


def bootstrap_admin(db: Session, username: str | None, password: str | None) -> str:
    """Create the first Admin (same rules as bootstrap_accounts_from_env)."""
    return _bootstrap(db, ROLE_ADMIN, "Admin", "ADMIN", "Administrator", username, password)


def _bootstrap(db: Session, role: str, label: str, prefix: str, full_name: str,
               username: str | None, password: str | None) -> str:
    from . import audit
    from .security import validate_new_password

    variables = f"{prefix}_USERNAME/{prefix}_PASSWORD"
    username = normalize_username(username)
    if not username or not password:
        return f"{SKIPPED}{variables} not set"
    if db.scalar(select(func.count(User.id)).where(User.role == role)):
        article = "an" if label[0] in "AEIOU" else "a"
        return (f"{SKIPPED}{article} {label} account already exists; {variables} are only used to create the first one "
                f"(change passwords in Admin -> Users)")
    if not USERNAME_RE.fullmatch(username):
        return f"{prefix}_USERNAME is not a valid username ({USERNAME_RULE}); no {label} account created"
    if db.scalar(select(User).where(User.username == username)):
        return f"user '{username}' already exists with another role; no {label} account created"
    try:
        validate_new_password(password)
    except ValueError as exc:
        return f"{prefix}_PASSWORD rejected ({exc}); no {label} account created"
    db.add(User(username=username, password_hash=hash_password(password), role=role, full_name=full_name))
    audit.record(db, "system", "user_created", username, f"{label} account created from environment variables.")
    db.commit()
    return f"created {label} account '{username}' from {variables}"
