"""Role-aware dashboard counts (always computed from the database)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import services as svc
from ..config import settings
from ..database import get_db
from ..models import (
    PHOTO_PENDING,
    PHOTO_REJECTED,
    PRINT_DONE,
    PRINT_NEW,
    PRINT_PROCESSING,
    ROLE_ADMIN,
    ROLE_PRINTING,
    STATUS_DRAFT,
    STATUS_LIVE,
    Order,
    User,
)
from ..security import require_any, require_viewer

router = APIRouter(tags=["dashboard"])

TOP_ROWS = 5
ATTENTION_ROWS = 8
AGE_BANDS = (("Under 1 day", 1), ("1 to 3 days", 4), ("4 to 7 days", 8), ("Over 7 days", None))


@router.get("/dashboard")
def dashboard(user: User = Depends(require_any), db: Session = Depends(get_db)) -> dict:
    active = and_(Order.is_archived.is_(False), svc.visible_to(user))  # Sales: only their own orders
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


def _top(totals: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_ROWS]


@router.get("/dashboard/attention")
def attention(user: User = Depends(require_viewer), db: Session = Depends(get_db)) -> dict:
    """Orders waiting on this user: the notification list. Printing gets jobs, everyone else drafts and previews."""
    active = and_(Order.is_archived.is_(False), svc.visible_to(user))
    if user.role == ROLE_PRINTING:
        waiting = and_(Order.status == STATUS_LIVE, or_(
            Order.printing_status == PRINT_NEW,
            and_(Order.printing_status != PRINT_DONE, Order.photo_status == PHOTO_REJECTED)))
        order_by = Order.live_at.asc()
    else:
        waiting = or_(Order.status == STATUS_DRAFT, Order.photo_status == PHOTO_PENDING)
        order_by = Order.updated_at.desc()
    count = db.scalar(select(func.count(Order.id)).where(active, waiting)) or 0
    orders = db.scalars(select(Order).where(active, waiting).order_by(order_by)
                        .options(selectinload(Order.items), selectinload(Order.attachments)).limit(ATTENTION_ROWS)).all()
    return {"count": count, "items": [svc.order_summary(o) for o in orders]}


@router.get("/dashboard/insights")
def insights(
    days: int = Query(14, ge=7, le=90),
    user: User = Depends(require_viewer),
    db: Session = Depends(get_db),
) -> dict:
    """Chart data for the dashboards. Read-only, scoped like every order list, and free of money for Printing."""
    printing = user.role == ROLE_PRINTING
    tz = settings.timezone
    today = datetime.now(tz).date()
    span = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    since = datetime.combine(span[0], time.min, tz)
    local = lambda dt: dt.astimezone(tz).date()  # noqa: E731

    conditions = [Order.is_archived.is_(False), svc.visible_to(user)]
    if printing:
        conditions.append(Order.status == STATUS_LIVE)  # Printing never sees drafts
    orders = db.execute(select(
        Order.created_at, Order.live_at, Order.processing_at, Order.print_done_at, Order.status, Order.printing_status,
        Order.total, Order.customer_name, Order.executive).where(*conditions)).all()

    trend = {d.isoformat(): {"date": d.isoformat(), "created": 0, "published": 0, "finished": 0} for d in span}
    customers: dict[str, float] = defaultdict(float)
    executives: Counter[str] = Counter()
    ages = Counter()

    for o in orders:
        if not printing and o.created_at >= since:
            trend[local(o.created_at).isoformat()]["created"] += 1
            if o.executive:
                executives[o.executive] += 1
        if o.live_at and o.live_at >= since:
            key = local(o.live_at).isoformat()
            trend[key]["published"] += 1
            if not printing:
                customers[o.customer_name or "Not set"] += o.total or 0
        if o.print_done_at and o.print_done_at >= since:
            trend[local(o.print_done_at).isoformat()]["finished"] += 1
        if o.status == STATUS_LIVE and o.printing_status in (PRINT_NEW, PRINT_PROCESSING) and o.live_at:
            age = (today - local(o.live_at)).days
            ages[next(label for label, upper in AGE_BANDS if upper is None or age < upper)] += 1

    data = {
        "role": user.role,
        "days": days,
        "trend": list(trend.values()),
        "job_ages": [{"label": label, "count": ages[label]} for label, _ in AGE_BANDS],
    }
    if not printing:
        data["top_customers"] = [{"name": n, "total": round(v, 2)} for n, v in _top(customers)]
        data["pipeline"] = {
            "uploaded": len(orders),
            "published": sum(1 for o in orders if o.live_at),
            "processing": sum(1 for o in orders if o.processing_at),
            "print_done": sum(1 for o in orders if o.print_done_at),
        }
    if user.role == ROLE_ADMIN:
        data["executives"] = [{"name": n, "orders": int(v)} for n, v in _top(dict(executives))]
    return data
