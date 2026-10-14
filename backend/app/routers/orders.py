"""Order endpoints for Sales and Printing."""
from __future__ import annotations

import html
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import contacts
from .. import services as svc
from ..config import settings
from ..database import get_db
from ..models import (
    PRINT_DONE,
    PRINTING_FLOW,
    ROLE_PRINTING,
    STATUS_DRAFT,
    STATUS_LIVE,
    Order,
    OrderAttachment,
    OrderItem,
    OrderPhoto,
    User,
)
from ..pdf_extract import extract_po
from ..schemas import CommentRequest, GlobalUpdate, ItemSave, OrderUpdate, PrintingStatusRequest, PublishRequest
from ..security import require_admin, require_manager, require_printing, require_viewer

router = APIRouter(prefix="/orders", tags=["orders"])

IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
ARTWORK_TYPES = IMAGE_TYPES + ("application/pdf",)


class VersionBody(BaseModel):
    version: int


# ---------------------------------------------------------------- list / detail
@router.get("")
def list_orders(
    q: str | None = Query(None, max_length=100),
    status_filter: Literal["Draft", "Live"] | None = Query(None, alias="status"),
    printing_status: str | None = Query(None),
    sort: Literal["updated", "live_oldest", "live_newest", "created"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_archived: bool = False,
    user: User = Depends(require_viewer),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Order).where(svc.visible_to(user))
    if user.role == ROLE_PRINTING:
        stmt = stmt.where(Order.status == STATUS_LIVE, Order.is_archived.is_(False))
        sort = sort or "live_oldest"
    else:
        if not include_archived:
            stmt = stmt.where(Order.is_archived.is_(False))
        sort = sort or "updated"
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
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order_by = {
        "updated": [Order.updated_at.desc()],
        "created": [Order.created_at.desc()],
        "live_oldest": [Order.live_at.asc(), Order.id.asc()],
        "live_newest": [Order.live_at.desc(), Order.id.desc()],
    }[sort]
    rows = db.scalars(
        stmt.options(selectinload(Order.items), selectinload(Order.attachments))
        .order_by(*order_by).limit(limit).offset(offset)
    ).all()
    return {"total": total, "items": [svc.order_summary(o) for o in rows]}


@router.get("/{order_id}")
def get_order(order_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)) -> dict:
    return svc.order_detail(svc.get_order_for(db, order_id, user), user)


# ---------------------------------------------------------------- upload + extraction (Sales)
@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_po(file: UploadFile = File(...), owner: str | None = Form(None, max_length=64),
                    user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    # Sales own their uploads; an Admin must choose the Sales user the order belongs to (`owner`).
    owner_user = svc.upload_owner(db, user, owner)
    filename = svc.safe_display_name(file.filename, "purchase-order.pdf")
    data = await svc.read_upload(file)
    if not filename.lower().endswith(".pdf") or svc.detect_file_type(data, ("application/pdf",)) is None:
        raise svc.http_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                             f"'{filename}' is not a PDF. Only PDF purchase orders can be uploaded.")
    digest = svc.sha256(data)
    relative = svc.store_file(data, "po", ".pdf")
    result = await run_in_threadpool(extract_po, settings.upload_dir / relative)

    order = Order(status=STATUS_DRAFT, source_filename=filename, source_pdf_path=relative, source_sha256=digest,
                  created_by=owner_user.username)
    svc.apply_extraction(order, result)
    duplicates = db.scalars(select(Order).where(Order.is_archived.is_(False), or_(
        Order.source_sha256 == digest,
        (Order.po_number == order.po_number) if order.po_number else false(),
    ))).all()
    if duplicates:
        same_file = any(d.source_sha256 == digest for d in duplicates)
        # Name only orders the owner may open; another Sales user's orders are mentioned without any details.
        own = [d for d in duplicates if svc.can_see(d, owner_user)]
        refs = ", ".join(d.internal_order_no or f"Draft #{d.id}" for d in own[:5])
        more = f" and {len(own) - 5} more" if len(own) > 5 else ""
        others = len(duplicates) - len(own)
        where = f"as {refs}{more}" if own else ""
        if others:
            where += (" and " if own else "") + f"in {others} order(s) uploaded by another user"
        reason = "The same PDF file" if same_file else f"PO {order.po_number}"
        order.extraction_warnings = [*order.extraction_warnings, {
            "field": "po_number", "level": "warning",
            "message": f"Possible duplicate: {reason} already exists {where}.",
        }]
    db.add(order)
    contacts.remember(db, order.executive, source="extracted", actor=user.username)
    for_owner = f" for {owner_user.username}" if owner_user is not user else ""
    svc.add_event(db, order, user, "pdf_uploaded", f"Uploaded {filename} ({len(data) // 1024} KB){for_owner}.")
    svc.add_event(db, order, user, "extracted", order.extraction_note)
    db.commit()
    return svc.order_detail(order, user)


@router.post("/{order_id}/re-extract")
async def re_extract(order_id: int, body: VersionBody, user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    order = svc.get_order_for(db, order_id, user)
    svc.ensure_draft(order)
    svc.ensure_version(order, body.version)
    path = svc.resolve_upload(order.source_pdf_path)
    result = await run_in_threadpool(extract_po, path)
    for att in [a for a in order.attachments if a.item_id is not None]:
        order.attachments.remove(att)
    svc.apply_extraction(order, result)
    order.updated_at = svc.utcnow()
    contacts.remember(db, order.executive, source="extracted", actor=user.username)
    svc.add_event(db, order, user, "re_extracted", "Fields and product rows replaced from the source PDF. " + result.note)
    db.commit()
    return svc.order_detail(order, user)


# ---------------------------------------------------------------- draft editing / publish (Sales)
@router.put("/{order_id}")
def update_order(order_id: int, body: OrderUpdate, user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    order = svc.get_order_for(db, order_id, user)
    svc.update_draft(db, order, body, user)
    db.commit()
    return svc.order_detail(order, user)


@router.post("/{order_id}/items", status_code=status.HTTP_201_CREATED)
def add_item(order_id: int, body: ItemSave, user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    """Save a new product row on its own (product card "Save Changes" before the row exists)."""
    order = svc.get_order_for(db, order_id, user)
    item = svc.save_item(db, order, None, body, user)
    db.commit()
    return {"order": svc.order_detail(order, user), "item_id": item.id}


@router.put("/{order_id}/items/{item_id}")
def update_item(order_id: int, item_id: int, body: ItemSave, user: User = Depends(require_manager),
                db: Session = Depends(get_db)) -> dict:
    """Save one product row without touching the rest of the draft."""
    order = svc.get_order_for(db, order_id, user)
    svc.save_item(db, order, item_id, body, user)
    db.commit()
    return {"order": svc.order_detail(order, user), "item_id": item_id}


@router.put("/{order_id}/global")
def update_global(order_id: int, body: GlobalUpdate, user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    """Save only the global customization section."""
    order = svc.get_order_for(db, order_id, user)
    svc.save_global(db, order, body, user)
    db.commit()
    return svc.order_detail(order, user)


@router.get("/{order_id}/publish-check")
def publish_check(order_id: int, user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    return svc.publish_check(svc.get_order_for(db, order_id, user))


@router.post("/{order_id}/publish")
def publish(order_id: int, body: PublishRequest, user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    order = svc.get_order_for(db, order_id, user)
    if order.is_archived:
        raise svc.http_error(status.HTTP_409_CONFLICT, "Archived drafts cannot be published.")
    svc.publish(db, order, user, body.version, body.reviewed)
    db.commit()
    return svc.order_detail(order, user)


@router.post("/{order_id}/archive")
def archive(order_id: int, body: VersionBody, user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    """Delete an order by archiving it (kept with its history; an Admin can restore it)."""
    order = svc.get_order_for(db, order_id, user)
    if order.is_archived:
        raise svc.http_error(status.HTTP_409_CONFLICT, "This order is already deleted.")
    if not svc.can_delete(order, user):
        raise svc.http_error(status.HTTP_403_FORBIDDEN, f"Printing has already started on this order "
                             f"({order.printing_status}). Only an Admin can delete it.", code="delete_not_allowed")
    svc.ensure_version(order, body.version)
    order.is_archived = True
    order.updated_at = svc.utcnow()
    where = "lists and the Printing queue" if order.status == STATUS_LIVE else "lists"
    svc.add_event(db, order, user, "archived",
                  f"Order deleted (archived): hidden from {where}. History is kept and an Admin can restore it.")
    db.commit()
    return svc.order_detail(order, user)


@router.post("/{order_id}/restore")
def restore(order_id: int, body: VersionBody, user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Admin: bring back a deleted (archived) order exactly as it was."""
    order = svc.get_order_for(db, order_id, user)
    if not order.is_archived:
        raise svc.http_error(status.HTTP_409_CONFLICT, "This order is not deleted.")
    svc.ensure_version(order, body.version)
    order.is_archived = False
    order.updated_at = svc.utcnow()
    state = f"{order.status}" + (f", printing status {order.printing_status}" if order.printing_status else "")
    svc.add_event(db, order, user, "restored", f"Order restored ({state}).")
    db.commit()
    return svc.order_detail(order, user)


# ---------------------------------------------------------------- comments (both roles)
@router.post("/{order_id}/comment", status_code=status.HTTP_201_CREATED)
def add_comment(order_id: int, body: CommentRequest, user: User = Depends(require_viewer), db: Session = Depends(get_db)) -> dict:
    order = svc.get_order_for(db, order_id, user)
    svc.add_event(db, order, user, "comment", body.text)
    db.commit()
    return svc.order_detail(order, user)


# ---------------------------------------------------------------- printing workflow (Printing)
@router.post("/{order_id}/printing-status")
def printing_status(order_id: int, body: PrintingStatusRequest, user: User = Depends(require_printing),
                    db: Session = Depends(get_db)) -> dict:
    order = svc.get_order_for(db, order_id, user)
    svc.change_printing_status(db, order, user, body.status)
    db.commit()
    return svc.order_detail(order, user)


# ---------------------------------------------------------------- files
@router.get("/{order_id}/source-pdf")
def source_pdf(order_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)) -> FileResponse:
    order = svc.get_order_for(db, order_id, user)
    return FileResponse(svc.resolve_upload(order.source_pdf_path), media_type="application/pdf",
                        filename=order.source_filename or "purchase-order.pdf", content_disposition_type="inline")


@router.post("/{order_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(order_id: int, file: UploadFile = File(...), item_id: int | None = Form(None),
                            user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    order = svc.get_order_for(db, order_id, user)
    svc.ensure_editable(order, user)
    if item_id is not None and not any(i.id == item_id for i in order.items):
        raise svc.http_error(status.HTTP_400_BAD_REQUEST, "Save the product row before attaching a logo to it.")
    data = await svc.read_upload(file)
    detected = svc.detect_file_type(data, ARTWORK_TYPES)
    if detected is None:
        raise svc.http_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                             "Logo/artwork must be a PNG, JPG, GIF, WEBP image or a PDF.")
    filename = svc.safe_display_name(file.filename, "logo" + detected[1])
    att = OrderAttachment(order=order, item_id=item_id, file_path=svc.store_file(data, "artwork", detected[1]),
                          original_filename=filename, content_type=detected[0], uploaded_by=user.username)
    db.add(att)
    target = next((f"row {i.position + 1} ({i.sku})" for i in order.items if i.id == item_id), "the whole order")
    svc.add_event(db, order, user, "logo_uploaded", f"{filename} attached to {target}.")
    db.commit()
    return svc.order_detail(order, user)


@router.delete("/{order_id}/attachments/{attachment_id}")
def delete_attachment(order_id: int, attachment_id: int, user: User = Depends(require_manager), db: Session = Depends(get_db)) -> dict:
    order = svc.get_order_for(db, order_id, user)
    svc.ensure_editable(order, user)
    att = next((a for a in order.attachments if a.id == attachment_id), None)
    if att is None:
        raise svc.http_error(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    order.attachments.remove(att)
    svc.validate_live_edit(order)  # a Live order must keep its customization
    svc.add_event(db, order, user, "logo_removed", f"{att.original_filename} removed.")
    db.commit()
    return svc.order_detail(order, user)


@router.get("/{order_id}/attachments/{attachment_id}")
def get_attachment(order_id: int, attachment_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)) -> FileResponse:
    order = svc.get_order_for(db, order_id, user)
    att = next((a for a in order.attachments if a.id == attachment_id), None)
    if att is None:
        raise svc.http_error(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    return FileResponse(svc.resolve_upload(att.file_path), media_type=att.content_type,
                        filename=att.original_filename, content_disposition_type="inline")


@router.post("/{order_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(order_id: int, file: UploadFile = File(...), user: User = Depends(require_printing),
                       db: Session = Depends(get_db)) -> dict:
    order = svc.get_order_for(db, order_id, user)
    if order.printing_status != PRINT_DONE:
        raise svc.http_error(status.HTTP_409_CONFLICT, "Photos can be uploaded after the order is marked Print Done.")
    data = await svc.read_upload(file)
    detected = svc.detect_file_type(data, IMAGE_TYPES)
    if detected is None:
        raise svc.http_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Photos must be PNG, JPG, GIF or WEBP images.")
    filename = svc.safe_display_name(file.filename, "photo" + detected[1])
    db.add(OrderPhoto(order=order, file_path=svc.store_file(data, "photos", detected[1]), original_filename=filename,
                      content_type=detected[0], uploaded_by=user.username))
    svc.add_event(db, order, user, "photo_uploaded", f"{filename} uploaded.")
    db.commit()
    return svc.order_detail(order, user)


@router.get("/{order_id}/photos/{photo_id}")
def get_photo(order_id: int, photo_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)) -> FileResponse:
    order = svc.get_order_for(db, order_id, user)
    photo = next((p for p in order.photos if p.id == photo_id), None)
    if photo is None:
        raise svc.http_error(status.HTTP_404_NOT_FOUND, "Photo not found.")
    return FileResponse(svc.resolve_upload(photo.file_path), media_type=photo.content_type,
                        filename=photo.original_filename, content_disposition_type="inline")


# ---------------------------------------------------------------- print view
@router.get("/{order_id}/print", response_class=HTMLResponse)
def print_view(order_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)) -> HTMLResponse:
    """Standalone print-friendly HTML (the React app also has a print view)."""
    order = svc.get_order_for(db, order_id, user)
    e = lambda v: html.escape("" if v is None else str(v)).replace("\n", "<br>")  # noqa: E731
    live = order.live_at.astimezone(settings.timezone).strftime("%d-%m-%Y %H:%M") if order.live_at else "Not live"
    rows = "".join(
        f"<tr><td>{n}</td><td><b>{e(i.sku)}</b><br>{e(i.product_name)}</td><td>{e(i.quantity)}</td>"
        f"<td>{e(i.location)}</td><td>{e(i.customization_text)}"
        f"{'<br><b>Names:</b> ' + e(', '.join(i.customization_names)) if i.customization_names else ''}"
        f"{'<br><b>Logo:</b> ' + e(i.logo_reference) if i.logo_reference else ''}</td><td>{e(i.notes)}</td></tr>"
        for n, i in enumerate(order.items, 1)
    )
    body = f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(order.internal_order_no or 'Draft')}</title>
<style>body{{font:13px Arial,sans-serif;margin:24px;color:#111}}table{{width:100%;border-collapse:collapse}}
td,th{{border:1px solid #999;padding:6px;vertical-align:top;text-align:left}}h1{{font-size:20px;margin:0 0 4px}}
.meta{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}}</style></head><body>
<h1>{e(order.internal_order_no or 'DRAFT — not live')}</h1>
<div>Live date: <b>{e(live)}</b> · Printing status: <b>{e(order.printing_status or '—')}</b></div>
<div class="meta"><div><b>Customer</b><br>{e(order.customer_name)}<br>PO {e(order.po_number)}</div>
<div><b>Ship to</b><br>{e(order.shipping_name)}<br>{e(order.shipping_address)}<br>{e(order.contact)}</div></div>
<table><thead><tr><th>#</th><th>SKU / Product</th><th>Qty</th><th>Location</th><th>Customization</th><th>Notes</th></tr></thead>
<tbody>{rows}</tbody></table>
<p><b>Global customization:</b> {e(order.global_customization) or '—'}
{'<br><b>Global names:</b> ' + e(', '.join(order.global_names)) if order.global_names else ''}
{'<br><b>Global logo:</b> ' + e(order.global_logo_reference) if order.global_logo_reference else ''}
<br><b>Global notes:</b> {e(order.global_notes) or '—'}</p></body></html>"""
    return HTMLResponse(body)
