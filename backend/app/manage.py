"""Command-line account management (useful before any Admin exists, or if all Admins are locked out).

Usage (from the backend folder):
    .venv\\Scripts\\python -m app.manage create-admin <username> [--name "Full Name"]   # first Admin account
    .venv\\Scripts\\python -m app.manage set-admin-credentials <username> [--password-stdin]
        # backs up, then creates the Admin or updates the existing Admin's username + password (no duplicates)
    .venv\\Scripts\\python -m app.manage list-users
    .venv\\Scripts\\python -m app.manage create-user <username> <admin|sales|printing> [--name "Full Name"]
    .venv\\Scripts\\python -m app.manage set-password <username>
    .venv\\Scripts\\python -m app.manage deactivate <username>
    .venv\\Scripts\\python -m app.manage activate <username>
    .venv\\Scripts\\python -m app.manage backup [--no-uploads]     # database + uploads ZIP into BACKUP_DIR

Passwords are typed at a hidden prompt, or piped on stdin with --password-stdin. They are never accepted as a
command-line argument, never printed and never logged.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from . import audit
from .config import settings
from .database import SessionLocal, configure_database
from .models import ROLE_ADMIN, ROLES, User, utcnow
from .security import hash_password, validate_new_password
from .security_seed import USERNAME_RE, USERNAME_RULE, normalize_username


def _ask_password() -> str:
    while True:
        first = getpass.getpass("New password: ")
        try:
            validate_new_password(first)
        except ValueError as exc:
            print(exc)
            continue
        if getpass.getpass("Repeat password: ") != first:
            print("Passwords do not match.")
            continue
        return first


def _read_password(from_stdin: bool) -> str:
    if not from_stdin:
        return _ask_password()
    password = sys.stdin.readline().rstrip("\r\n")
    validate_new_password(password)  # raises ValueError with a message that never contains the password
    return password


def set_admin_credentials(db, username: str, password: str) -> tuple[User, str]:
    """Create the Admin, or update the existing Admin's username and password, without creating duplicates.

    Picks, in order: the account already named `username` (must be an Admin), otherwise the only Admin
    (or the oldest active one if there are several). Returns (user, description of what was done).
    """
    named = db.scalar(select(User).where(User.username == username))
    if named is not None and named.role != ROLE_ADMIN:
        raise ValueError(f"'{username}' already exists as a {named.role} user; choose another Admin username.")
    target = named
    if target is None:
        admins = db.scalars(select(User).where(User.role == ROLE_ADMIN)
                            .order_by(User.is_active.desc(), User.created_at, User.id)).all()
        target = admins[0] if admins else None
    if target is None:
        user = User(username=username, full_name="Administrator", role=ROLE_ADMIN, password_hash=hash_password(password),
                    is_active=True, updated_at=utcnow())
        db.add(user)
        audit.record(db, "command-line", "user_created", username, "Admin created with set-admin-credentials.")
        return user, f"Created Admin account '{username}'."
    old_name = target.username
    target.username = username
    target.password_hash = hash_password(password)
    target.is_active = True
    target.session_version = User.session_version + 1  # sign out sessions that used the old credentials
    target.updated_at = utcnow()
    renamed = f" (renamed from '{old_name}')" if old_name != username else ""
    audit.record(db, "command-line", "password_reset", username,
                 f"Admin credentials updated with set-admin-credentials{renamed}; existing sessions signed out.")
    return target, f"Updated Admin account '{username}'{renamed}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description="Manage portal user accounts.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-users")
    create = sub.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("role", choices=ROLES)
    create.add_argument("--name", default=None)
    admin = sub.add_parser("create-admin", help="create an Admin account")
    admin.add_argument("username")
    admin.add_argument("--name", default="Administrator")
    creds = sub.add_parser("set-admin-credentials", help="back up, then create or update the Admin login")
    creds.add_argument("username")
    creds.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    for name in ("set-password", "deactivate", "activate"):
        sub.add_parser(name).add_argument("username")
    bk = sub.add_parser("backup", help="create a backup ZIP (database + uploaded files) in BACKUP_DIR")
    bk.add_argument("--no-uploads", action="store_true", help="back up the database only")
    args = parser.parse_args(argv)

    if args.cmd == "backup":
        return _cmd_backup(args)

    if args.cmd == "set-admin-credentials":
        return _cmd_set_admin_credentials(args)

    configure_database(settings.database_path, settings.backup_dir)
    with SessionLocal() as db:
        if args.cmd == "list-users":
            for u in db.scalars(select(User).order_by(User.username)):
                print(f"{u.username:<20} {u.role:<10} {'active' if u.is_active else 'inactive'}")
            return 0

        username = normalize_username(args.username)
        user = db.scalar(select(User).where(User.username == username))
        if args.cmd in ("create-user", "create-admin"):
            role = ROLE_ADMIN if args.cmd == "create-admin" else args.role
            if user:
                print(f"User '{username}' already exists.")
                return 1
            if not USERNAME_RE.fullmatch(username):
                print(f"Username must be {USERNAME_RULE}.")
                return 1
            db.add(User(username=username, full_name=args.name, role=role, password_hash=hash_password(_ask_password())))
            audit.record(db, "command-line", "user_created", username, f"Created with role {role} from the command line.")
            db.commit()
            print(f"Created {role} user '{username}'.")
            return 0

        if user is None:
            print(f"User '{username}' not found.")
            return 1
        if args.cmd == "set-password":
            user.password_hash = hash_password(_ask_password())
            detail = "Password changed from the command line."
        else:
            user.is_active = args.cmd == "activate"
            detail = f"{'Activated' if user.is_active else 'Deactivated'} from the command line."
        user.session_version = User.session_version + 1  # sign the user out everywhere (incremented in SQL)
        user.updated_at = utcnow()
        audit.record(db, "command-line", "password_reset" if args.cmd == "set-password" else "user_updated", username, detail)
        db.commit()
        print(f"Updated '{user.username}'.")
        return 0



def _cmd_set_admin_credentials(args) -> int:
    from . import backup

    username = normalize_username(args.username)
    if not USERNAME_RE.fullmatch(username):
        print(f"Username must be {USERNAME_RULE}.")
        return 1
    try:
        password = _read_password(args.password_stdin)
    except ValueError as exc:
        print(f"Password rejected: {exc}")
        return 1
    configure_database(settings.database_path, settings.backup_dir)
    saved = backup.create_backup("command-line (before set-admin-credentials)")
    print(f"Backup saved: {settings.backup_dir / saved['name']}")
    with SessionLocal() as db:
        try:
            user, message = set_admin_credentials(db, username, password)
        except ValueError as exc:
            db.rollback()
            print(exc)
            return 1
        db.commit()
        print(message)
    return 0



def _cmd_backup(args) -> int:
    """Consistent backup while the portal runs (safe to schedule). Old backups are never deleted."""
    from . import backup

    configure_database(settings.database_path, settings.backup_dir)
    info = backup.create_backup("command-line (scheduled backup)", include_uploads=not args.no_uploads)
    with SessionLocal() as db:
        audit.record(db, "command-line", "backup_created", info["name"],
                     f"{info['size_bytes'] // 1024} KB; {info['upload_files']} uploaded file(s) included.")
        db.commit()
    print(f"Backup saved: {settings.backup_dir / info['name']} ({info['size_bytes'] // 1024} KB, "
          f"{info['upload_files']} uploaded file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
