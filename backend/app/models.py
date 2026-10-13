"""Database tables."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .database import Base

ROLE_ADMIN = "admin"
ROLE_SALES = "sales"
ROLE_PRINTING = "printing"
ROLES = (ROLE_ADMIN, ROLE_SALES, ROLE_PRINTING)

STATUS_DRAFT = "Draft"
STATUS_LIVE = "Live"

PRINT_NEW = "New"
PRINT_PROCESSING = "Processing"
PRINT_DONE = "Print Done"
PRINTING_FLOW = (PRINT_NEW, PRINT_PROCESSING, PRINT_DONE)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores datetimes as naive UTC (SQLite has no tz support) and returns aware UTC values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role in ('admin','sales','printing')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Bumped on password reset, deactivation or role change: tokens issued earlier stop working.
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Counter(Base):
    """Sequence counters (internal order numbers per year)."""

    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("status in ('Draft','Live')", name="ck_orders_status"),
        CheckConstraint(
            "printing_status is null or printing_status in ('New','Processing','Print Done')",
            name="ck_orders_printing_status",
        ),
        Index("ix_orders_status_printing", "status", "printing_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    internal_order_no: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)

    # Source PO data
    po_number: Mapped[str | None] = mapped_column(String(64), index=True)
    source_status: Mapped[str | None] = mapped_column(String(64))
    source_order_date: Mapped[str | None] = mapped_column(String(32))  # ISO "YYYY-MM-DDTHH:MM" as printed
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    billing_address: Mapped[str | None] = mapped_column(Text)
    shipping_name: Mapped[str | None] = mapped_column(String(200))
    shipping_address: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(32))
    executive: Mapped[str | None] = mapped_column(String(200))
    subtotal: Mapped[float | None] = mapped_column(Float)
    packaging_charges: Mapped[float | None] = mapped_column(Float)
    processing_charges: Mapped[float | None] = mapped_column(Float)
    additional_charges: Mapped[float | None] = mapped_column(Float)
    tax: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float | None] = mapped_column(Float)
    source_meta: Mapped[dict] = mapped_column(JSON, default=dict)  # other printed details (agent, type box…)

    # Customization
    global_customization: Mapped[str | None] = mapped_column(Text)  # text/name applied across the order
    global_names: Mapped[list] = mapped_column(JSON, default=list)  # list of names applied across the order
    global_logo_reference: Mapped[str | None] = mapped_column(Text)
    global_notes: Mapped[str | None] = mapped_column(Text)

    # Workflow
    status: Mapped[str] = mapped_column(String(16), default=STATUS_DRAFT, index=True)
    printing_status: Mapped[str | None] = mapped_column(String(16), index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    live_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    processing_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    print_done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # Source file / extraction
    source_filename: Mapped[str | None] = mapped_column(String(255))
    source_pdf_path: Mapped[str | None] = mapped_column(String(500))
    source_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    extraction_note: Mapped[str | None] = mapped_column(Text)
    extraction_warnings: Mapped[list] = mapped_column(JSON, default=list)

    created_by: Mapped[str | None] = mapped_column(String(64))
    published_by: Mapped[str | None] = mapped_column(String(64))

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.position"
    )
    events: Mapped[list[OrderEvent]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderEvent.id"
    )
    attachments: Mapped[list[OrderAttachment]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderAttachment.id"
    )
    photos: Mapped[list[OrderPhoto]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderPhoto.id"
    )

    # Optimistic locking: every UPDATE checks and increments `version`, so concurrent publish /
    # status changes / draft saves cannot silently overwrite each other.
    __mapper_args__ = {"version_id_col": version}


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    sku: Mapped[str | None] = mapped_column(String(200), index=True)
    product_name: Mapped[str | None] = mapped_column(String(300))
    quantity: Mapped[int | None] = mapped_column(Integer)
    rate: Mapped[float | None] = mapped_column(Float)
    original_rate: Mapped[float | None] = mapped_column(Float)  # struck-through price printed on the PO
    value: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[str | None] = mapped_column(String(100))
    hsn: Mapped[str | None] = mapped_column(String(32))
    tax: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(String(64))

    # SKU-wise customization
    customization_names: Mapped[list] = mapped_column(JSON, default=list)  # individual name per unit
    customization_text: Mapped[str | None] = mapped_column(Text)  # same name/text on every unit
    logo_reference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    order: Mapped[Order] = relationship(back_populates="items")


class OrderEvent(Base):
    """Audit trail and comments (event == 'comment')."""

    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    actor_role: Mapped[str | None] = mapped_column(String(16))
    event: Mapped[str] = mapped_column(String(40), index=True)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    order: Mapped[Order] = relationship(back_populates="events")


class OrderAttachment(Base):
    """Logo / artwork files. item_id null means global (order-wide) artwork."""

    __tablename__ = "order_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    uploaded_by: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    order: Mapped[Order] = relationship(back_populates="attachments")


class OrderPhoto(Base):
    """Post-print photos (uploaded by Printing after Print Done)."""

    __tablename__ = "order_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    uploaded_by: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    order: Mapped[Order] = relationship(back_populates="photos")


class AppSetting(Base):
    """Admin-editable runtime settings (a small whitelist; see app/runtime_settings.py)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AdminEvent(Base):
    """Audit trail for non-order actions: sign-ins, user management, settings, backups."""

    __tablename__ = "admin_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class SalesContact(Base):
    """Executive / sales contact names (managed by Admins; added automatically from POs and draft saves)."""

    __tablename__ = "sales_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # normalised name (trimmed, inner spaces collapsed, case-folded): one contact per key
    name_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(16), default="admin")  # extracted | manual | admin | backfill
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
