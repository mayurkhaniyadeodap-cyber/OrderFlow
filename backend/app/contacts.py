"""Executive / sales contact names.

Names are matched by a normalised key (leading/trailing spaces removed, inner runs of spaces collapsed,
case-insensitive), so "  Dhruv Bhojani " and "dhruv bhojani" are the same contact. Saving a contact never
changes any order: orders keep the executive text exactly as printed or entered.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AppSetting, Order, SalesContact, utcnow

MAX_NAME = 200
BACKFILL_FLAG = "sales_contacts_backfilled"


def clean_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("\x00", "")).strip()


def name_key(name: str | None) -> str:
    return clean_name(name).casefold()


def find(db: Session, name: str | None) -> SalesContact | None:
    key = name_key(name)
    return db.scalar(select(SalesContact).where(SalesContact.name_key == key)) if key else None


def remember(db: Session, name: str | None, *, source: str, actor: str | None) -> SalesContact | None:
    """Return the contact for `name`, creating it if new. Blank names are ignored. Safe under concurrent saves."""
    cleaned = clean_name(name)[:MAX_NAME]
    if not cleaned:
        return None
    existing = find(db, cleaned)
    if existing is not None:
        return existing
    contact = SalesContact(name=cleaned, name_key=name_key(cleaned), source=source, created_by=actor)
    try:
        with db.begin_nested():  # savepoint: a concurrent insert of the same name must not fail the order save
            db.add(contact)
    except IntegrityError:
        return find(db, cleaned)
    return contact


def backfill_from_orders(db: Session) -> int | None:
    """One-time: add executive names already on orders. Orders are only read. Returns the number added,
    or None if the backfill already ran."""
    if db.get(AppSetting, BACKFILL_FLAG) is not None:
        return None
    added = 0
    for (executive,) in db.execute(select(Order.executive).where(Order.executive.is_not(None)).order_by(Order.id)):
        if find(db, executive) is None and remember(db, executive, source="backfill", actor="system"):
            added += 1
    db.add(AppSetting(key=BACKFILL_FLAG, value={"added": added, "at": utcnow().isoformat()}, updated_by="system"))
    db.commit()
    return added
