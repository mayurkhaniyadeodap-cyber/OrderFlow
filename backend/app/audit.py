"""Recording non-order audit events (sign-ins, user management, settings, backups)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AdminEvent, User


def record(db: Session, actor: User | str, action: str, target: str | None = None, details: str | None = None) -> None:
    """Add an audit row to the session (committed with the caller's transaction). Never pass secrets in details."""
    name, role = (actor.username, actor.role) if isinstance(actor, User) else (actor, None)
    db.add(AdminEvent(actor=name[:64], actor_role=role, action=action, target=(target or None) and target[:120],
                      details=details))
