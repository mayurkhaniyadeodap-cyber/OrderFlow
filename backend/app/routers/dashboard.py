"""Role-aware dashboard counts (always computed from the database)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import services as svc
from ..database import get_db
from ..models import PRINT_DONE, PRINT_NEW, PRINT_PROCESSING, ROLE_PRINTING, STATUS_DRAFT, STATUS_LIVE, Order, User
from ..security import require_any

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(user: User = Depends(require_any), db: Session = Depends(get_db)) -> dict:
    active = Order.is_archived.is_(False)
    by_status = dict(db.execute(select(Order.status, func.count()).where(active).group_by(Order.status)).all())
    by_printing = dict(db.execute(
        select(Order.printing_status, func.count()).where(active, Order.status == STATUS_LIVE).group_by(Order.printing_status)
    ).all())
    counts = {
        "live": by_status.get(STATUS_LIVE, 0),
        "awaiting_printing": by_printing.get(PRINT_NEW, 0),
        "processing": by_printing.get(PRINT_PROCESSING, 0),
        "print_done": by_printing.get(PRINT_DONE, 0),
    }
    if user.role == ROLE_PRINTING:
        counts["total"] = counts["live"]
        recent_stmt = (select(Order).where(active, Order.status == STATUS_LIVE, Order.printing_status != PRINT_DONE)
                       .order_by(Order.live_at.asc()))
    else:
        counts["total"] = sum(by_status.values())
        counts["draft"] = by_status.get(STATUS_DRAFT, 0)
        recent_stmt = select(Order).where(active).order_by(Order.updated_at.desc())
    recent = db.scalars(recent_stmt.options(selectinload(Order.items), selectinload(Order.attachments)).limit(8)).all()
    return {"role": user.role, "counts": counts, "recent": [svc.order_summary(o) for o in recent]}
