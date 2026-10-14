"""Admin panel API. Every route requires the Admin role (enforced by the router dependency)."""
from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from .. import backup as backups
from .. import contacts
from .. import runtime_settings
from .. import services as svc
from ..config import settings
from ..database import get_db
from ..models import (
    PRINT_DONE,
    PRINT_NEW,
    PRINT_PROCESSING,
    PRINTING_FLOW,
    ROLE_ADMIN,
    SalesContact,
    ROLES,
    STATUS_DRAFT,
    STATUS_LIVE,
    AdminEvent,
    Order,
    OrderEvent,
    OrderItem,
    User,
    utcnow,
)
from ..security import hash_password, require_admin, validate_new_password
from ..security_seed import USERNAME_RE, USERNAME_RULE, normalize_username

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
# Serialises role/active changes so two concurrent requests cannot both pass the "last active Admin" check.
_user_change_lock = threading.Lock()

ORDER_EVENT_LABELS = {
    "pdf_uploaded": "Created (PDF uploaded)", "extracted": "Data extracted", "re_extracted": "Re-extracted",
    "draft_saved": "Draft saved", "item_saved": "Product saved", "global_saved": "Global customization saved",
    "logo_uploaded": "Logo added", "logo_removed": "Logo removed", "published": "Published Live",
    "printing_status_changed": "Printing status changed", "photo_uploaded": "Photo uploaded",
    "comment": "Comment", "archived": "Deleted (archived)", "restored": "Restored", "live_edited": "Live order edited",
}
ADMIN_EVENT_LABELS = {
    "login": "Signed in", "login_failed": "Sign-in failed", "user_created": "User created",
    "user_updated": "User updated", "password_reset": "Password reset", "settings_updated": "Settings changed",
    "backup_created": "Backup created", "backup_downloaded": "Backup downloaded",
    "contact_created": "Contact added", "contact_updated": "Contact renamed", "contact_deleted": "Contact deleted",
    "contacts_backfilled": "Contacts imported from orders",
}


def _local_day_bounds(d_from: date | None, d_to: date | None) -> tuple[datetime | None, datetime | None]:
    tz = settings.timezone
    start = datetime.combine(d_from, time.min, tz) if d_from else None
    end = datetime.combine(d_to, time.max, tz) if d_to else None
    return start, end


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- dashboard
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    active = Order.is_archived.is_(False)
    by_status = dict(db.execute(select(Order.status, func.count()).where(active).group_by(Order.status)).all())
    by_printing = dict(db.execute(select(Order.printing_status, func.count())
                                  .where(active, Order.status == STATUS_LIVE).group_by(Order.printing_status)).all())
    archived = db.scalar(select(func.count(Order.id)).where(Order.is_archived.is_(True))) or 0

    users = {r: {"active": 0, "inactive": 0} for r in ROLES}
    for role, is_active, n in db.execute(select(User.role, User.is_active, func.count()).group_by(User.role, User.is_active)):
        users.setdefault(role, {"active": 0, "inactive": 0})["active" if is_active else "inactive"] += n

    # orders created / published per local day for the last 14 days
    tz = settings.timezone
    today = datetime.now(tz).date()
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    since = datetime.combine(days[0], time.min, tz)
    trend = {d.isoformat(): {"date": d.isoformat(), "created": 0, "published": 0} for d in days}
    for (created,) in db.execute(select(Order.created_at).where(Order.created_at >= since)):
        key = created.astimezone(tz).date().isoformat()
        if key in trend:
            trend[key]["created"] += 1
    for (live,) in db.execute(select(Order.live_at).where(Order.live_at >= since)):
        key = live.astimezone(tz).date().isoformat()
        if key in trend:
            trend[key]["published"] += 1

    waiting = db.scalars(
        select(Order).where(active, Order.status == STATUS_LIVE, Order.printing_status.in_([PRINT_NEW, PRINT_PROCESSING]))
        .options(selectinload(Order.items), selectinload(Order.attachments)).order_by(Order.live_at.asc()).limit(5)
    ).all()
    return {
        "orders": {
            "total": sum(by_status.values()), "draft": by_status.get(STATUS_DRAFT, 0), "live": by_status.get(STATUS_LIVE, 0),
            "archived": archived, "new": by_printing.get(PRINT_NEW, 0), "processing": by_printing.get(PRINT_PROCESSING, 0),
            "print_done": by_printing.get(PRINT_DONE, 0),
        },
        "users": users,
        "trend": list(trend.values()),
        "oldest_open": [svc.order_summary(o) for o in waiting],
        "recent_activity": _activity(db, limit=10)["items"],
    }


# ---------------------------------------------------------------- all orders
@router.get("/orders")
def all_orders(
    q: str | None = Query(None, max_length=100),
    status_filter: Literal["Draft", "Live", "Archived"] | None = Query(None, alias="status"),
    printing_status: str | None = None,
    date_field: Literal["created", "live", "updated"] = "created",
    date_from: date | None = None,
    date_to: date | None = None,
    sort: Literal["newest", "oldest"] = "newest",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Order)
    if status_filter == "Archived":
        stmt = stmt.where(Order.is_archived.is_(True))
    else:
        stmt = stmt.where(Order.is_archived.is_(False))
        if status_filter:
            stmt = stmt.where(Order.status == status_filter)
    if printing_status:
        if printing_status not in PRINTING_FLOW:
            raise svc.http_error(status.HTTP_400_BAD_REQUEST, f"Unknown printing status '{printing_status}'.")
        stmt = stmt.where(Order.printing_status == printing_status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        sku_match = select(OrderItem.order_id).where(OrderItem.sku.ilike(like))
        stmt = stmt.where(or_(
            Order.internal_order_no.ilike(like), Order.po_number.ilike(like), Order.customer_name.ilike(like),
            Order.shipping_name.ilike(like), Order.contact.ilike(like), Order.id.in_(sku_match),
        ))
    column = {"created": Order.created_at, "live": Order.live_at, "updated": Order.updated_at}[date_field]
    start, end = _local_day_bounds(date_from, date_to)
    if start:
        stmt = stmt.where(column >= start)
    if end:
        stmt = stmt.where(column <= end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order_by = column.desc() if sort == "newest" else column.asc()
    rows = db.scalars(stmt.options(selectinload(Order.items), selectinload(Order.attachments))
                      .order_by(order_by, Order.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [svc.order_summary(o) | {"created_by": o.created_by, "published_by": o.published_by}
                                      for o in rows]}


# ---------------------------------------------------------------- users
class UserAdminOut(BaseModel):
    id: int
    username: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime | None
    last_login_at: datetime | None


def _user_out(u: User) -> dict:
    return UserAdminOut.model_validate(u, from_attributes=True).model_dump(mode="json")


def _clean_name(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)  # 3-32 after normalising, checked below
    full_name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "sales", "printing"]
    password: str = Field(min_length=1, max_length=200)

    _name = field_validator("full_name", mode="before")(_clean_name)

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        value = normalize_username(value)
        if not USERNAME_RE.fullmatch(value):
            raise ValueError(f"Use {USERNAME_RULE}")
        return value

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        validate_new_password(value)
        return value


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "sales", "printing"] | None = None
    is_active: bool | None = None

    _name = field_validator("full_name", mode="before")(_clean_name)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=200)

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        validate_new_password(value)
        return value


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == ROLE_ADMIN, User.is_active.is_(True))) or 0


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise svc.http_error(status.HTTP_404_NOT_FOUND, "User not found.")
    return user


@router.get("/users")
def list_users(db: Session = Depends(get_db)) -> dict:
    users = db.scalars(select(User).order_by(User.role, User.username)).all()
    return {"items": [_user_out(u) for u in users]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(User).where(User.username == body.username)):
        raise svc.http_error(status.HTTP_409_CONFLICT, f"Username '{body.username}' is already taken.")
    user = User(username=body.username, full_name=body.full_name, role=body.role,
                password_hash=hash_password(body.password), updated_at=utcnow())
    db.add(user)
    audit.record(db, admin, "user_created", user.username, f"Created with role {user.role}.")
    db.commit()
    return _user_out(user)


def _end_sessions(user: User) -> None:
    """Invalidate the user's tokens (incremented in SQL so concurrent changes cannot cancel each other)."""
    user.session_version = User.session_version + 1


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    with _user_change_lock:
        return _update_user(user_id, body, admin, db)


def _update_user(user_id: int, body: UserUpdate, admin: User, db: Session) -> dict:
    user = _get_user(db, user_id)
    sent = body.model_fields_set
    changes: list[str] = []
    if "full_name" in sent and body.full_name != user.full_name:
        changes.append(f"name: {user.full_name or '—'} → {body.full_name or '—'}")
        user.full_name = body.full_name
    access_changed = False
    if "role" in sent and body.role is not None and body.role != user.role:
        if user.id == admin.id:
            raise svc.http_error(status.HTTP_409_CONFLICT, "You cannot change your own role.")
        if user.role == ROLE_ADMIN and user.is_active and _active_admins(db) <= 1:
            raise svc.http_error(status.HTTP_409_CONFLICT, "This is the last active Admin. Create another Admin first.")
        changes.append(f"role: {user.role} → {body.role}")
        user.role = body.role
        access_changed = True
    if "is_active" in sent and body.is_active is not None and body.is_active != user.is_active:
        if user.id == admin.id and not body.is_active:
            raise svc.http_error(status.HTTP_409_CONFLICT, "You cannot deactivate your own account.")
        if not body.is_active and user.role == ROLE_ADMIN and _active_admins(db) <= 1:
            raise svc.http_error(status.HTTP_409_CONFLICT, "This is the last active Admin. Create another Admin first.")
        changes.append("activated" if body.is_active else "deactivated")
        user.is_active = body.is_active
        access_changed = True
    if changes:
        if access_changed:
            _end_sessions(user)  # end the user's current sessions
        user.updated_at = utcnow()
        audit.record(db, admin, "user_updated", user.username, "; ".join(changes))
        db.flush()
        if _active_admins(db) == 0:  # defence in depth: never commit a state without an active Admin
            db.rollback()
            raise svc.http_error(status.HTTP_409_CONFLICT, "This is the last active Admin. Create another Admin first.")
        db.commit()
        db.refresh(user)
    return _user_out(user)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: PasswordReset, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    user = _get_user(db, user_id)
    user.password_hash = hash_password(body.new_password)
    _end_sessions(user)  # sign the user out everywhere
    user.updated_at = utcnow()
    audit.record(db, admin, "password_reset", user.username,
                 "Password reset by an Admin; existing sessions were signed out.")  # never the password itself
    db.commit()
    db.refresh(user)
    return _user_out(user)


# ---------------------------------------------------------------- activity / audit log
def _activity(db: Session, *, q: str | None = None, actor: str | None = None, action: str | None = None,
              source: str | None = None, date_from: date | None = None, date_to: date | None = None,
              limit: int = 50, offset: int = 0) -> dict:
    start, end = _local_day_bounds(date_from, date_to)
    want = offset + limit
    results: list[dict] = []
    total = 0

    if source in (None, "order"):
        stmt = select(OrderEvent, Order).join(Order, Order.id == OrderEvent.order_id)
        if actor:
            stmt = stmt.where(func.lower(OrderEvent.actor) == actor.strip().lower())
        if action:
            stmt = stmt.where(OrderEvent.event == action)
        if start:
            stmt = stmt.where(OrderEvent.created_at >= start)
        if end:
            stmt = stmt.where(OrderEvent.created_at <= end)
        if q and q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(OrderEvent.details.ilike(like), Order.internal_order_no.ilike(like),
                                  Order.po_number.ilike(like), Order.customer_name.ilike(like)))
        total += db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        for ev, order in db.execute(stmt.order_by(OrderEvent.created_at.desc(), OrderEvent.id.desc()).limit(want)):
            results.append({
                "id": f"o{ev.id}", "source": "order", "created_at": ev.created_at, "actor": ev.actor,
                "actor_role": ev.actor_role, "action": ev.event, "label": ORDER_EVENT_LABELS.get(ev.event, ev.event),
                "details": ev.details, "order_id": order.id,
                "target": order.internal_order_no or f"Draft #{order.id}",
                "order_customer": order.customer_name, "order_po": order.po_number,
            })

    if source in (None, "admin"):
        stmt = select(AdminEvent)
        if actor:
            stmt = stmt.where(func.lower(AdminEvent.actor) == actor.strip().lower())
        if action:
            stmt = stmt.where(AdminEvent.action == action)
        if start:
            stmt = stmt.where(AdminEvent.created_at >= start)
        if end:
            stmt = stmt.where(AdminEvent.created_at <= end)
        if q and q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(AdminEvent.details.ilike(like), AdminEvent.target.ilike(like)))
        total += db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        for ev in db.scalars(stmt.order_by(AdminEvent.created_at.desc(), AdminEvent.id.desc()).limit(want)):
            results.append({
                "id": f"a{ev.id}", "source": "admin", "created_at": ev.created_at, "actor": ev.actor,
                "actor_role": ev.actor_role, "action": ev.action, "label": ADMIN_EVENT_LABELS.get(ev.action, ev.action),
                "details": ev.details, "order_id": None, "target": ev.target,
                "order_customer": None, "order_po": None,
            })

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    results.sort(key=lambda r: r["created_at"] or epoch, reverse=True)
    page = results[offset:offset + limit]
    for r in page:
        r["created_at"] = _iso(r["created_at"])
    return {"total": total, "items": page}


@router.get("/activity")
def activity(
    q: str | None = Query(None, max_length=100),
    actor: str | None = Query(None, max_length=64),
    action: str | None = Query(None, max_length=40),
    source: Literal["order", "admin"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
    db: Session = Depends(get_db),
) -> dict:
    data = _activity(db, q=q, actor=actor, action=action, source=source, date_from=date_from, date_to=date_to,
                     limit=limit, offset=offset)
    data["actions"] = [{"value": k, "label": v, "source": "order"} for k, v in ORDER_EVENT_LABELS.items()] + \
                      [{"value": k, "label": v, "source": "admin"} for k, v in ADMIN_EVENT_LABELS.items()]
    return data


# ---------------------------------------------------------------- settings
def _settings_payload() -> dict:
    return {
        "editable": runtime_settings.current().model_dump(),
        "read_only": {
            "timezone": str(settings.timezone),
            "order_number_prefix": settings.order_number_prefix,
            "secret_key_configured": not settings.secret_is_ephemeral,
        },
    }


@router.get("/settings")
def get_settings() -> dict:
    return _settings_payload()


@router.put("/settings")
def update_settings(body: runtime_settings.SettingsUpdate, admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)) -> dict:
    changes = runtime_settings.update(db, body, admin.username)
    if changes:
        audit.record(db, admin, "settings_updated", None,
                     "; ".join(f"{k.replace('_', ' ')}: {old} → {new}" for k, (old, new) in changes.items()))
    db.commit()
    return _settings_payload()


# ---------------------------------------------------------------- backups
class BackupRequest(BaseModel):
    include_uploads: bool = True


@router.get("/backups")
def list_backups() -> dict:
    return {"items": backups.list_backups(), "folder": settings.backup_dir.name}


@router.post("/backups", status_code=status.HTTP_201_CREATED)
def create_backup(body: BackupRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    info = backups.create_backup(admin.username, include_uploads=body.include_uploads)
    audit.record(db, admin, "backup_created", info["name"],
                 f"{info['size_bytes'] // 1024} KB; {info['upload_files']} uploaded file(s) included.")
    db.commit()
    return info


@router.get("/backups/{name}")
def download_backup(name: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> FileResponse:
    path = backups.resolve_backup(name)
    if path is None:
        raise svc.http_error(status.HTTP_404_NOT_FOUND, "Backup not found.")
    audit.record(db, admin, "backup_downloaded", name)
    db.commit()
    return FileResponse(path, media_type="application/zip", filename=name)


# ---------------------------------------------------------------- executive / sales contacts
class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=contacts.MAX_NAME)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = contacts.clean_name(value)
        if not value:
            raise ValueError("Enter a name")
        return value


def _contact_out(c: SalesContact, usage: dict[str, int]) -> dict:
    return {"id": c.id, "name": c.name, "source": c.source, "created_by": c.created_by,
            "created_at": _iso(c.created_at), "updated_at": _iso(c.updated_at), "orders": usage.get(c.name_key, 0)}


def _contact_usage(db: Session) -> dict[str, int]:
    """Number of (non-discarded) orders per contact key; orders are only read."""
    usage: dict[str, int] = {}
    for (executive,) in db.execute(select(Order.executive).where(Order.executive.is_not(None), Order.is_archived.is_(False))):
        key = contacts.name_key(executive)
        if key:
            usage[key] = usage.get(key, 0) + 1
    return usage


def _get_contact(db: Session, contact_id: int) -> SalesContact:
    contact = db.get(SalesContact, contact_id)
    if contact is None:
        raise svc.http_error(status.HTTP_404_NOT_FOUND, "Contact not found.")
    return contact


@router.get("/contacts")
def list_contacts(db: Session = Depends(get_db)) -> dict:
    usage = _contact_usage(db)
    rows = db.scalars(select(SalesContact).order_by(SalesContact.name_key)).all()
    return {"items": [_contact_out(c, usage) for c in rows]}


@router.post("/contacts", status_code=status.HTTP_201_CREATED)
def create_contact(body: ContactIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    existing = contacts.find(db, body.name)
    if existing is not None:
        raise svc.http_error(status.HTTP_409_CONFLICT, f"'{existing.name}' already exists.")
    contact = contacts.remember(db, body.name, source="admin", actor=admin.username)
    audit.record(db, admin, "contact_created", contact.name)
    db.commit()
    return _contact_out(contact, _contact_usage(db))


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    contact = _get_contact(db, contact_id)
    clash = contacts.find(db, body.name)
    if clash is not None and clash.id != contact.id:
        raise svc.http_error(status.HTTP_409_CONFLICT, f"'{clash.name}' already exists.")
    if body.name != contact.name:
        old = contact.name
        contact.name, contact.name_key, contact.updated_at = body.name, contacts.name_key(body.name), utcnow()
        audit.record(db, admin, "contact_updated", contact.name, f"{old} → {contact.name} (orders are not changed)")
        db.commit()
    return _contact_out(contact, _contact_usage(db))


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    contact = _get_contact(db, contact_id)
    db.delete(contact)
    audit.record(db, admin, "contact_deleted", contact.name, "Removed from the contact list (orders are not changed).")
    db.commit()
    return {"ok": True}


@router.get("/contacts/{contact_id}/orders")
def contact_orders(contact_id: int, db: Session = Depends(get_db)) -> dict:
    """Orders whose executive matches this contact (ignoring case and extra spaces). Read-only; deleted
    (archived) orders are left out, the same as the Orders count on the contacts list."""
    contact = _get_contact(db, contact_id)
    candidates = db.scalars(
        select(Order).where(Order.executive.is_not(None), Order.is_archived.is_(False))
        .options(selectinload(Order.items), selectinload(Order.attachments))
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    linked = [o for o in candidates if contacts.name_key(o.executive) == contact.name_key]
    return {
        "contact": _contact_out(contact, {contact.name_key: len(linked)}),
        "total": len(linked),
        "items": [svc.order_summary(o) | {"source_order_date": o.source_order_date, "executive": o.executive} for o in linked],
    }
