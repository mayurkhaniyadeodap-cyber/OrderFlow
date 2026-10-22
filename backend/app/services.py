"""Order workflow rules: draft editing, publish validation, printing transitions, serialisation."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import ColumnElement, select, true, update
from sqlalchemy.orm import Session, object_session

from . import contacts
from .config import settings
from .models import (
    PHOTO_CONFIRMED,
    PHOTO_PENDING,
    PHOTO_REJECTED,
    PRINT_DONE,
    PRINT_NEW,
    PRINT_PROCESSING,
    ROLE_ADMIN,
    ROLE_PRINTING,
    ROLE_SALES,
    STATUS_DRAFT,
    STATUS_LIVE,
    Counter,
    Order,
    OrderAttachment,
    OrderEvent,
    OrderItem,
    OrderPhoto,
    User,
    utcnow,
)
from .pdf_extract import ExtractionResult
from .schemas import GlobalUpdate, ItemSave, OrderUpdate, PhotoReviewRequest

# Allowed printing transitions: forward one step only. Print Done is terminal.
PRINTING_TRANSITIONS = {PRINT_NEW: (PRINT_PROCESSING,), PRINT_PROCESSING: (PRINT_DONE,), PRINT_DONE: ()}

ORDER_FIELDS = (
    "po_number", "source_status", "source_order_date", "customer_name", "billing_address", "shipping_name",
    "shipping_address", "contact", "email", "gstin", "executive", "subtotal", "packaging_charges",
    "processing_charges", "additional_charges", "tax", "total", "global_customization", "global_names",
    "global_logo_reference", "global_notes",
)
ITEM_FIELDS = (
    "sku", "product_name", "quantity", "rate", "original_rate", "value", "printing_price", "weight", "hsn", "tax",
    "location", "customization_names", "customization_text", "logo_reference", "notes",
)
FIELD_LABELS = {
    "po_number": "PO number", "source_status": "source status", "source_order_date": "order date",
    "customer_name": "customer", "billing_address": "billing address", "shipping_name": "ship-to name",
    "shipping_address": "shipping address", "contact": "contact", "email": "email", "gstin": "GSTIN",
    "executive": "executive", "subtotal": "subtotal", "packaging_charges": "packaging charges",
    "processing_charges": "processing charges", "additional_charges": "additional charges", "tax": "tax",
    "total": "total", "global_customization": "global customization", "global_names": "global names",
    "global_logo_reference": "global logo reference", "global_notes": "global notes",
}

IMAGE_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"%PDF-", "application/pdf", ".pdf"),
]


def http_error(status_code: int, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code, detail={"message": message, **extra})


# ---------------------------------------------------------------- events
def add_event(db: Session, order: Order, user: User | None, event: str, details: str | None = None) -> OrderEvent:
    ev = OrderEvent(
        order=order, actor=user.username if user else "system", actor_role=user.role if user else None,
        event=event, details=details,
    )
    db.add(ev)
    return ev


# ---------------------------------------------------------------- files
async def read_upload(upload: UploadFile, max_bytes: int | None = None) -> bytes:
    limit = max_bytes or settings.max_upload_bytes
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise http_error(status.HTTP_413_CONTENT_TOO_LARGE,
                             f"File is too large. The limit is {limit // (1024 * 1024)} MB.")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise http_error(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    return data


def detect_file_type(data: bytes, allowed: tuple[str, ...]) -> tuple[str, str] | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and "image/webp" in allowed:
        return "image/webp", ".webp"
    head = data[:1024]
    for signature, content_type, ext in IMAGE_SIGNATURES:
        if content_type in allowed and (head.startswith(signature) or (signature == b"%PDF-" and signature in head)):
            return content_type, ext
    return None


def store_file(data: bytes, folder: str, ext: str) -> str:
    """Save bytes under uploads/<folder>/ with a random name. Returns the path relative to UPLOAD_DIR."""
    target_dir = settings.upload_dir / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (target_dir / name).write_bytes(data)
    return f"{folder}/{name}"


def resolve_upload(relative: str | None) -> Path:
    if not relative:
        raise http_error(status.HTTP_404_NOT_FOUND, "File not found.")
    base = settings.upload_dir.resolve()
    path = (base / relative).resolve()
    if base not in path.parents or not path.is_file():
        raise http_error(status.HTTP_404_NOT_FOUND, "The stored file is missing.")
    return path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_display_name(filename: str | None, default: str) -> str:
    name = Path(filename or default).name.replace("\x00", "").strip()
    return name[:200] or default


# ---------------------------------------------------------------- extraction warnings
# Couriers are no longer part of OrderFlow and amounts are not used in the editor: courier warnings stored on
# older orders are hidden, and amount warnings are shown as info only.
_AMOUNT_FIELDS = {"subtotal", "packaging_charges", "processing_charges", "additional_charges", "tax", "total"}


# Informational notes that are not shown in the review panel. The extractor still records them and they stay
# stored on the order; they are only left out of what the editor displays. (field, message prefix)
HIDDEN_INFO_NOTES = (
    ("gstin", "GSTIN is printed as N/A."),
    ("items", "The PO prints only a product code per row"),
    ("tax", "Tax amount is not printed separately."),
)


def _hidden_note(w: dict) -> bool:
    message = w.get("message") or ""
    return w.get("level") == "info" and any(
        w.get("field") == field and message.startswith(prefix) for field, prefix in HIDDEN_INFO_NOTES)


def visible_warnings(order: Order) -> list[dict]:
    out = []
    for w in order.extraction_warnings or []:
        if w.get("field") == "courier" or _hidden_note(w):
            continue
        if w.get("field") in _AMOUNT_FIELDS and w.get("level") == "warning":
            w = {**w, "level": "info"}
        out.append(w)
    return out


def review_warnings(order: Order) -> list[dict]:
    return [w for w in visible_warnings(order) if w.get("level") in ("error", "warning")]


# ---------------------------------------------------------------- extraction → draft
def apply_extraction(order: Order, result: ExtractionResult) -> None:
    for name in ORDER_FIELDS:
        if name in ("global_customization", "global_names", "global_logo_reference", "global_notes"):
            continue
        setattr(order, name, result.order.get(name))
    order.source_meta = result.meta
    order.extraction_warnings = result.warnings
    order.extraction_note = result.note
    order.items.clear()
    for idx, data in enumerate(result.items):
        order.items.append(OrderItem(position=idx, **{k: data.get(k) for k in ITEM_FIELDS if k in data}))


# ---------------------------------------------------------------- draft editing
def ensure_editable(order: Order, user: User) -> None:
    """Drafts can be edited by Sales and Admin; Live orders only by Admin (any printing status)."""
    if order.is_archived:
        raise http_error(status.HTTP_409_CONFLICT, "This order is deleted. An Admin can restore it first.",
                         code="order_deleted")
    if order.status == STATUS_DRAFT or user.role == ROLE_ADMIN:
        return
    ensure_draft(order)  # raises the usual "Live and locked" error


def validate_live_edit(order: Order) -> None:
    """A Live order edited by an Admin must still satisfy the publish rules (customer, rows, customization…)."""
    if order.status != STATUS_LIVE:
        return
    errors = [e for e in publish_check(order)["errors"] if e != "Order is already Live."]
    if errors:
        raise http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "This Live order cannot be saved like this.",
                         errors=errors)


def _edit_event(order: Order, default: str) -> str:
    return "live_edited" if order.status == STATUS_LIVE else default


def can_delete(order: Order, user: User) -> bool:
    """Admin: any order. Sales: Drafts, and Live orders Printing has not started (still New)."""
    if order.is_archived:
        return False
    if user.role == ROLE_ADMIN:
        return True
    return user.role == ROLE_SALES and (order.status == STATUS_DRAFT or order.printing_status == PRINT_NEW)


def ensure_draft(order: Order) -> None:
    if order.status != STATUS_DRAFT:
        raise http_error(status.HTTP_409_CONFLICT,
                         f"Order {order.internal_order_no or order.id} is Live and locked. Only comments can be added.",
                         code="order_locked")


def ensure_version(order: Order, version: int) -> None:
    if order.version != version:
        raise http_error(status.HTTP_409_CONFLICT,
                         "This order was changed by someone else since you opened it. Reload to see the latest "
                         "version (copy any unsaved changes first).", code="version_conflict")


def _fmt(value: Any) -> str:
    if value is None or value == [] or value == "":
        return "—"
    if isinstance(value, list):
        return f"{len(value)} name(s)"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "…"


def update_draft(db: Session, order: Order, payload: OrderUpdate, user: User) -> list[str]:
    ensure_editable(order, user)
    ensure_version(order, payload.version)
    changes: list[str] = []
    for name in ORDER_FIELDS:
        new = getattr(payload, name)
        old = getattr(order, name)
        if new != old:
            changes.append(f"{FIELD_LABELS[name]}: {_fmt(old)} → {_fmt(new)}")
            setattr(order, name, new)

    existing = {item.id: item for item in order.items}
    seen: set[int] = set()
    new_items: list[OrderItem] = []
    for pos, data in enumerate(payload.items):
        if data.id is not None:
            values = _sent_item_values(data)
            item = existing.get(data.id)
            if item is None:
                raise http_error(status.HTTP_400_BAD_REQUEST, f"Product row {data.id} does not belong to this order.")
            seen.add(item.id)
            diff = _apply_item_values(item, values)
            if diff:
                changes.append(f"row {pos + 1} ({item.sku or item.product_name or 'no SKU'}): " + ", ".join(diff))
            item.position = pos
            new_items.append(item)
        else:
            values = {k: getattr(data, k) for k in ITEM_FIELDS}
            new_items.append(OrderItem(position=pos, **values))
            changes.append(f"row {pos + 1} added ({values['sku'] or values['product_name'] or 'no SKU'})")
    for item_id, item in existing.items():
        if item_id not in seen:
            changes.append(f"row removed ({item.sku or item.product_name or 'no SKU'})")
            for att in [a for a in order.attachments if a.item_id == item_id]:
                order.attachments.remove(att)
            for photo in order.photos:  # photos stay on the order, no longer linked to the removed row
                if photo.item_id == item_id:
                    photo.item_id = None
    order.items[:] = new_items
    if order.status == STATUS_LIVE:
        refresh_photo_summary(order)
    order.updated_at = utcnow()
    validate_live_edit(order)
    contacts.remember(db, order.executive, source="manual", actor=user.username)
    add_event(db, order, user, _edit_event(order, "draft_saved"), "; ".join(changes) if changes else "Saved without changes.")
    return changes


def _sent_item_values(data: Any) -> dict[str, Any]:
    """Item fields present in the request. Fields the client leaves out keep their stored value on existing rows
    (the editor no longer shows product name, MRP, weight, HSN/SAC, tax or location, so it does not send them)."""
    return {k: getattr(data, k) for k in ITEM_FIELDS if k in data.model_fields_set}


def _apply_item_values(item: OrderItem, values: dict[str, Any]) -> list[str]:
    """Copy values onto a product row; returns the labels of fields that changed."""
    diff = [k.replace("_", " ") for k, v in values.items() if getattr(item, k) != v]
    for k, v in values.items():
        setattr(item, k, v)
    return diff


def save_item(db: Session, order: Order, item_id: int | None, payload: ItemSave, user: User) -> OrderItem:
    """Save a single product row (existing when item_id is given, otherwise appended). Draft only."""
    ensure_editable(order, user)
    ensure_version(order, payload.version)
    if item_id is None:
        values = {k: getattr(payload, k) for k in ITEM_FIELDS}
        item = OrderItem(position=len(order.items), **values)
        order.items.append(item)
        detail = f"row {item.position + 1} added ({item.sku or item.product_name or 'no SKU'})"
    else:
        item = next((i for i in order.items if i.id == item_id), None)
        if item is None:
            raise http_error(status.HTTP_404_NOT_FOUND, "Product row not found on this order. Reload the order.")
        diff = _apply_item_values(item, _sent_item_values(payload))
        label = f"row {item.position + 1} ({item.sku or item.product_name or 'no SKU'})"
        detail = f"{label}: {', '.join(diff)}" if diff else f"{label} saved without changes"
    order.updated_at = utcnow()  # bumps the order version so stale full-draft saves are rejected
    validate_live_edit(order)
    add_event(db, order, user, _edit_event(order, "item_saved"), detail)
    return item


def save_global(db: Session, order: Order, payload: GlobalUpdate, user: User) -> list[str]:
    """Save only the global customization fields. Draft only."""
    ensure_editable(order, user)
    ensure_version(order, payload.version)
    changes: list[str] = []
    for name in ("global_customization", "global_names", "global_logo_reference", "global_notes"):
        new, old = getattr(payload, name), getattr(order, name)
        if new != old:
            changes.append(f"{FIELD_LABELS[name]}: {_fmt(old)} → {_fmt(new)}")
            setattr(order, name, new)
    order.updated_at = utcnow()
    validate_live_edit(order)
    add_event(db, order, user, _edit_event(order, "global_saved"), "; ".join(changes) if changes else "Saved without changes.")
    return changes


# ---------------------------------------------------------------- publish validation
def _item_has_customization(order: Order, item: OrderItem) -> bool:
    return bool(item.customization_names or item.customization_text or item.logo_reference
                or any(a.item_id == item.id for a in order.attachments if item.id is not None))


def has_global_customization(order: Order) -> bool:
    return bool(order.global_customization or order.global_names or order.global_logo_reference
                or any(a.item_id is None for a in order.attachments))


def publish_check(order: Order) -> dict[str, list[str]]:
    """Return blocking errors and non-blocking warnings for publishing."""
    errors: list[str] = []
    warnings: list[str] = []
    if order.status != STATUS_DRAFT:
        errors.append("Order is already Live.")
    if not order.customer_name:
        errors.append("Customer name is required.")
    if not order.items:
        errors.append("Add at least one product row.")
    for idx, item in enumerate(order.items, start=1):
        label = f"Row {idx} ({item.sku or item.product_name or 'no SKU'})"
        if not item.sku:
            errors.append(f"Row {idx}: SKU is required.")
        if not item.quantity or item.quantity < 1:
            errors.append(f"{label}: quantity must be a whole number of at least 1.")
        if item.customization_names and item.quantity and len(item.customization_names) != item.quantity:
            errors.append(f"{label}: {len(item.customization_names)} individual name(s) entered for quantity "
                          f"{item.quantity}. Enter exactly one name per unit, or use 'same text for every unit'.")
        if item.rate is not None and item.quantity and item.value is not None:
            if abs(round(item.rate * item.quantity, 2) - item.value) > max(0.01, item.value * 0.0005):
                warnings.append(f"{label}: rate × quantity ({item.rate * item.quantity:.2f}) differs from the "
                                f"line value ({item.value:.2f}).")
    if not has_global_customization(order) and not any(_item_has_customization(order, i) for i in order.items):
        errors.append("Customization is required: add SKU-wise names/text/logo for at least one product, or a "
                      "global customization (text, names or logo). Notes alone do not count.")
    review = review_warnings(order)
    if review:
        warnings.append(f"{len(review)} extraction warning(s) were raised for this PDF. Confirm you reviewed them.")
    return {"errors": errors, "warnings": warnings}


def next_internal_number(db: Session, when: datetime) -> str:
    year = when.astimezone(settings.timezone).year
    name = f"order-{year}"
    result = db.execute(update(Counter).where(Counter.name == name).values(value=Counter.value + 1))
    if result.rowcount == 0:  # type: ignore[attr-defined]
        db.add(Counter(name=name, value=1))
        db.flush()
        value = 1
    else:
        value = db.scalar(select(Counter.value).where(Counter.name == name))
    return f"{settings.order_number_prefix}-{year}-{value:05d}"


def publish(db: Session, order: Order, user: User, version: int, reviewed: bool) -> None:
    if order.status == STATUS_LIVE:
        raise http_error(status.HTTP_409_CONFLICT,
                         f"Order is already Live as {order.internal_order_no}. It was not published again.",
                         code="already_live", internal_order_no=order.internal_order_no)
    ensure_version(order, version)
    if not reviewed:
        raise http_error(status.HTTP_422_UNPROCESSABLE_CONTENT,
                         "Confirm that you reviewed the extracted data against the source PDF.",
                         errors=["Review confirmation is required."])
    check = publish_check(order)
    if check["errors"]:
        raise http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "The order cannot be published yet.",
                         errors=check["errors"], warnings=check["warnings"])
    now = utcnow()
    order.internal_order_no = next_internal_number(db, now)
    order.status = STATUS_LIVE
    order.printing_status = PRINT_NEW
    order.live_at = now
    order.published_by = user.username
    order.updated_at = now
    detail = f"Published as {order.internal_order_no}; printing status New."
    if check["warnings"]:
        detail += " Acknowledged warnings: " + " | ".join(check["warnings"])
    add_event(db, order, user, "published", detail)


def change_printing_status(db: Session, order: Order, user: User, new_status: str) -> None:
    if order.status != STATUS_LIVE or order.printing_status is None:
        raise http_error(status.HTTP_409_CONFLICT, "Only Live orders have a printing status.")
    current = order.printing_status
    if current == PRINT_DONE:
        raise http_error(status.HTTP_409_CONFLICT, "Print Done is final. The printing status is locked.",
                         code="print_done_locked")
    allowed = PRINTING_TRANSITIONS[current]
    if new_status not in allowed:
        raise http_error(status.HTTP_409_CONFLICT,
                         f"Cannot change printing status from {current} to {new_status}. "
                         f"Allowed next step: {', '.join(allowed)}.", code="invalid_transition")
    if new_status == PRINT_DONE:
        waiting = [i for i in order.items if i.photo_status != PHOTO_CONFIRMED]
        if waiting:
            raise http_error(status.HTTP_409_CONFLICT,
                             f"Sales has not confirmed the print preview of {len(waiting)} product(s) yet. Upload a "
                             "preview photo for each product and wait for Sales to confirm it before Print Done.",
                             code="previews_not_confirmed",
                             errors=[f"{item_label(i)}: {i.photo_status or 'no preview uploaded'}" for i in waiting])
    now = utcnow()
    order.printing_status = new_status
    if new_status == PRINT_PROCESSING:
        order.processing_at = now
    if new_status == PRINT_DONE:
        order.print_done_at = now
    order.updated_at = now
    add_event(db, order, user, "printing_status_changed", f"{current} → {new_status}")


# ---------------------------------------------------------------- print preview photo review (per product row)
def item_label(item: OrderItem) -> str:
    return f"row {item.position + 1} ({item.sku or item.product_name or 'no SKU'})"


def find_item(order: Order, item_id: int) -> OrderItem:
    item = next((i for i in order.items if i.id == item_id), None)
    if item is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "Product row not found on this order. Reload the order.")
    return item


def photo_upload_open(order: Order) -> bool:
    """Print previews are uploaded while the order is Live and not yet printed (New or Processing)."""
    return order.status == STATUS_LIVE and not order.is_archived and order.printing_status in (PRINT_NEW, PRINT_PROCESSING)


def ensure_photo_upload_allowed(order: Order, item: OrderItem) -> None:
    if not photo_upload_open(order):
        raise http_error(status.HTTP_409_CONFLICT,
                         "Preview photos can be uploaded while the order is New or Processing (not after Print Done).")
    if item.photo_status == PHOTO_CONFIRMED:
        raise http_error(status.HTTP_409_CONFLICT, f"Sales already confirmed the preview for {item_label(item)}.",
                         code="photos_confirmed")


def refresh_photo_summary(order: Order) -> None:
    """Order-level summary used by lists: Pending if any product photo waits for Sales, else Rejected if any was
    rejected, else Confirmed once every product is confirmed; otherwise null (photos still to upload)."""
    statuses = [i.photo_status for i in order.items]
    if PHOTO_PENDING in statuses:
        order.photo_status = PHOTO_PENDING
    elif PHOTO_REJECTED in statuses:
        order.photo_status = PHOTO_REJECTED
    elif statuses and all(s == PHOTO_CONFIRMED for s in statuses):
        order.photo_status = PHOTO_CONFIRMED
    else:
        order.photo_status = None


def mark_photo_pending(order: Order, item: OrderItem) -> None:
    """A new photo for a product (first one, or after a rejection) goes back to Sales for confirmation."""
    item.photo_status = PHOTO_PENDING
    refresh_photo_summary(order)
    order.updated_at = utcnow()


def can_review_photos(order: Order, user: User) -> bool:
    """Sales (own orders) and Admin review the product preview photos of Live orders."""
    return user.role in (ROLE_SALES, ROLE_ADMIN) and not order.is_archived and order.status == STATUS_LIVE


def review_item_photo(db: Session, order: Order, item: OrderItem, user: User, payload: PhotoReviewRequest) -> None:
    """Sales/Admin confirm a product's preview photo (final) or reject it with a reason."""
    ensure_version(order, payload.version)
    has_photo = any(p.item_id == item.id for p in order.photos)
    if not can_review_photos(order, user) or item.photo_status != PHOTO_PENDING or not has_photo:
        current = item.photo_status or "no photo uploaded"
        raise http_error(status.HTTP_409_CONFLICT,
                         f"There is no preview waiting for confirmation on {item_label(item)} ({current}).",
                         code="photos_not_pending")
    if payload.action == "reject" and not payload.note:
        raise http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the reason for rejecting the preview.",
                         errors=["A reason is required to reject the preview."])
    now = utcnow()
    item.photo_status = PHOTO_CONFIRMED if payload.action == "confirm" else PHOTO_REJECTED
    item.photo_reviewed_by = user.username
    item.photo_reviewed_at = now
    item.photo_review_note = payload.note
    refresh_photo_summary(order)
    order.updated_at = now
    if payload.action == "confirm":
        add_event(db, order, user, "photos_confirmed",
                  f"Preview confirmed for {item_label(item)}." + (f" Note: {payload.note}" if payload.note else ""))
    else:
        add_event(db, order, user, "photos_rejected", f"Preview rejected for {item_label(item)}: {payload.note}")


def photo_dict(order: Order, p: OrderPhoto) -> dict[str, Any]:
    return {"id": p.id, "item_id": p.item_id, "filename": p.original_filename, "content_type": p.content_type,
            "uploaded_by": p.uploaded_by, "uploaded_at": _iso(p.uploaded_at),
            "url": f"/api/orders/{order.id}/photos/{p.id}"}


# ---------------------------------------------------------------- access + serialisation
def can_see(order: Order, user: User) -> bool:
    """Order visibility: a Sales user sees only the orders they uploaded (`created_by`); Printing and Admin see
    every user's orders (Printing: Live only, checked separately)."""
    return user.role != ROLE_SALES or order.created_by == user.username


def visible_to(user: User) -> ColumnElement[bool]:
    """The same rule as `can_see`, as a filter for Order queries (lists, search, counts)."""
    return Order.created_by == user.username if user.role == ROLE_SALES else true()


def upload_owner(db: Session, user: User, owner: str | None) -> User:
    """Who a newly uploaded PO belongs to (`created_by`): a Sales user always owns their own uploads; an Admin
    must choose an active Sales user, who then sees and manages the order as if they had uploaded it."""
    from .security_seed import normalize_username

    wanted = normalize_username(owner)
    if user.role != ROLE_ADMIN:
        if wanted and wanted != user.username:
            raise http_error(status.HTTP_403_FORBIDDEN, "Sales users can only upload orders for themselves.")
        return user
    if not wanted:
        raise http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose the Sales user this order belongs to.")
    target = db.scalar(select(User).where(User.username == wanted))
    if target is None or target.role != ROLE_SALES or not target.is_active:
        raise http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{wanted}' is not an active Sales user.")
    return target


def get_order_for(db: Session, order_id: int, user: User) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.is_archived and user.role not in (ROLE_SALES, ROLE_ADMIN):
        raise http_error(status.HTTP_404_NOT_FOUND, "Order not found.")
    if not can_see(order, user):
        # Another Sales user's order: answer exactly as if it did not exist.
        raise http_error(status.HTTP_404_NOT_FOUND, "Order not found.")
    if user.role == ROLE_PRINTING and order.status != STATUS_LIVE:
        # Drafts are not printing work items.
        raise http_error(status.HTTP_404_NOT_FOUND, "Order not found.")
    return order


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def attachment_dict(order: Order, att: OrderAttachment) -> dict[str, Any]:
    return {
        "id": att.id, "item_id": att.item_id, "filename": att.original_filename, "content_type": att.content_type,
        "uploaded_by": att.uploaded_by, "uploaded_at": _iso(att.uploaded_at),
        "url": f"/api/orders/{order.id}/attachments/{att.id}",
    }


def order_summary(order: Order) -> dict[str, Any]:
    return {
        "id": order.id, "internal_order_no": order.internal_order_no, "po_number": order.po_number,
        "customer_name": order.customer_name, "status": order.status,
        "printing_status": order.printing_status, "live_at": _iso(order.live_at),
        "created_at": _iso(order.created_at), "updated_at": _iso(order.updated_at),
        "total": order.total, "item_count": len(order.items),
        "total_quantity": sum(i.quantity or 0 for i in order.items),
        "source_filename": order.source_filename, "is_archived": order.is_archived,
        "has_customization": has_global_customization(order) or any(_item_has_customization(order, i) for i in order.items),
        "warning_count": len(review_warnings(order)),
        "photo_status": order.photo_status,
    }


def executive_mobile(order: Order) -> str | None:
    """Mobile number saved for the order's executive / sales contact (Admin → Executive Contacts)."""
    db = object_session(order)
    contact = contacts.find(db, order.executive) if db is not None and order.executive else None
    return contact.mobile if contact else None


def order_detail(order: Order, user: User) -> dict[str, Any]:
    data = order_summary(order)
    data.update({name: getattr(order, name) for name in ORDER_FIELDS})
    data.update({
        "version": order.version, "source_meta": order.source_meta or {},
        "extraction_note": order.extraction_note, "extraction_warnings": visible_warnings(order),
        "created_by": order.created_by, "published_by": order.published_by,
        "processing_at": _iso(order.processing_at), "print_done_at": _iso(order.print_done_at),
        "has_source_pdf": bool(order.source_pdf_path),
        "executive_mobile": executive_mobile(order),
        "items": [
            {"id": i.id, "position": i.position, **{k: getattr(i, k) for k in ITEM_FIELDS},
             "attachments": [attachment_dict(order, a) for a in order.attachments if a.item_id == i.id],
             "photo_status": i.photo_status, "photo_reviewed_by": i.photo_reviewed_by,
             "photo_reviewed_at": _iso(i.photo_reviewed_at), "photo_review_note": i.photo_review_note,
             "photos": [photo_dict(order, p) for p in order.photos if p.item_id == i.id]}
            for i in order.items
        ],
        "global_attachments": [attachment_dict(order, a) for a in order.attachments if a.item_id is None],
        "photos": [photo_dict(order, p) for p in order.photos],
        "comments": [
            {"id": e.id, "actor": e.actor, "actor_role": e.actor_role, "text": e.details, "created_at": _iso(e.created_at)}
            for e in order.events if e.event == "comment"
        ],
        "activity": [
            {"id": e.id, "actor": e.actor, "actor_role": e.actor_role, "event": e.event, "details": e.details,
             "created_at": _iso(e.created_at)}
            for e in order.events
        ],
        "permissions": {
            "can_edit": not order.is_archived and (
                (user.role in (ROLE_SALES, ROLE_ADMIN) and order.status == STATUS_DRAFT)
                or (user.role == ROLE_ADMIN and order.status == STATUS_LIVE)),
            "can_publish": user.role in (ROLE_SALES, ROLE_ADMIN) and order.status == STATUS_DRAFT and not order.is_archived,
            "can_comment": user.role in (ROLE_SALES, ROLE_PRINTING, ROLE_ADMIN),
            "can_delete": can_delete(order, user),
            "can_restore": user.role == ROLE_ADMIN and order.is_archived,
            "next_printing_statuses": list(PRINTING_TRANSITIONS.get(order.printing_status or "", ()))
            if user.role == ROLE_PRINTING and order.status == STATUS_LIVE else [],
            "can_upload_photos": user.role == ROLE_PRINTING and photo_upload_open(order),
            "can_review_photos": can_review_photos(order, user),
        },
    })
    return data
