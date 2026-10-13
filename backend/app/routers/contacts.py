"""Read-only list of executive / sales contact names for the Sales Order form (management is Admin-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ROLE_ADMIN, ROLE_SALES, SalesContact
from ..security import require_role

router = APIRouter(tags=["contacts"])


@router.get("/contacts")
def list_contact_names(_user=Depends(require_role(ROLE_SALES, ROLE_ADMIN)), db: Session = Depends(get_db)) -> dict:
    names = db.scalars(select(SalesContact.name).order_by(SalesContact.name_key)).all()
    return {"items": list(names)}
