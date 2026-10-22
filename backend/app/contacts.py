"""Executive / sales contact names.

Names are matched by a normalised key (leading/trailing spaces removed, inner runs of spaces collapsed,
case-insensitive), so "  Dhruv Bhojani " and "dhruv bhojani" are the same contact. Saving a contact never
changes any order: orders keep the executive text exactly as printed or entered.

Each contact can have a mobile number (set by Admins). POs often print it in the name, e.g.
"Dhruv Bhojani - Izzat (6358956693)"; new contacts take their mobile from such a name automatically.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AppSetting, Order, SalesContact, utcnow

MAX_NAME = 200
MAX_MOBILE = 20
BACKFILL_FLAG = "sales_contacts_backfilled"
MOBILE_BACKFILL_FLAG = "sales_contact_mobiles_backfilled"


def clean_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("\x00", "")).strip()


def name_key(name: str | None) -> str:
    return clean_name(name).casefold()


def clean_mobile(mobile: str | None) -> str | None:
    """Trim a mobile number; returns None when blank. Raises ValueError unless it has 7-15 digits and only
    digits, spaces, '+', '-' or brackets."""
    text = re.sub(r"\s+", " ", (mobile or "").replace("\x00", "")).strip()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if len(text) > MAX_MOBILE or not re.fullmatch(r"[0-9+\-() ]+", text) or not 7 <= len(digits) <= 15:
        raise ValueError("Enter a valid mobile number (7-15 digits, e.g. 98765 43210 or +91 9876543210)")
    return text


def mobile_from_name(name: str | None) -> str | None:
    """A 10-digit mobile number printed in a contact name, e.g. "Dhruv Bhojani - Izzat (6358956693)"."""
    found = re.findall(r"(?<!\d)(?:\+?91[\s-]?)?([6-9]\d{9})(?!\d)", name or "")
    return found[-1] if found else None


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
    contact = SalesContact(name=cleaned, name_key=name_key(cleaned), mobile=mobile_from_name(cleaned), source=source,
                           created_by=actor)
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


def backfill_mobiles(db: Session) -> int | None:
    """One-time: fill the mobile number of existing contacts whose name contains one. Returns the number
    filled, or None if this already ran (so a mobile an Admin clears later stays cleared)."""
    if db.get(AppSetting, MOBILE_BACKFILL_FLAG) is not None:
        return None
    filled = 0
    for contact in db.scalars(select(SalesContact).where(SalesContact.mobile.is_(None))):
        mobile = mobile_from_name(contact.name)
        if mobile:
            contact.mobile = mobile
            filled += 1
    db.add(AppSetting(key=MOBILE_BACKFILL_FLAG, value={"filled": filled, "at": utcnow().isoformat()},
                      updated_by="system"))
    db.commit()
    return filled
