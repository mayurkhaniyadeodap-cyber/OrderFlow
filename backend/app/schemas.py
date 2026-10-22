"""Request/response models."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TEXT = 5000


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.replace("\x00", "").strip()
        return value or None
    return value


def _clean_names(value: Any) -> list[str]:
    """Normalise a list of names: strip blanks; reject non-lists and over-long names."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Names must be a list")
    names = [str(v).replace("\x00", "").strip() for v in value]
    if any(len(n) > 200 for n in names):
        raise ValueError("Each name must be 200 characters or fewer")
    return [n for n in names if n]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    full_name: str | None
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class ItemIn(BaseModel):
    """A product row sent by Sales when saving a Draft. id is omitted for new rows."""

    id: int | None = None
    sku: str | None = Field(default=None, max_length=200)
    product_name: str | None = Field(default=None, max_length=300)
    quantity: int | None = Field(default=None, ge=0, le=1_000_000)
    rate: float | None = Field(default=None, ge=0, le=100_000_000)
    original_rate: float | None = Field(default=None, ge=0, le=100_000_000)
    value: float | None = Field(default=None, ge=0, le=1_000_000_000)
    printing_price: float | None = Field(default=None, ge=0, le=100_000_000)
    weight: str | None = Field(default=None, max_length=100)
    hsn: str | None = Field(default=None, max_length=32)
    tax: str | None = Field(default=None, max_length=32)
    location: str | None = Field(default=None, max_length=64)
    customization_names: list[str] = Field(default_factory=list, max_length=100_000)
    customization_text: str | None = Field(default=None, max_length=MAX_TEXT)
    logo_reference: str | None = Field(default=None, max_length=MAX_TEXT)
    notes: str | None = Field(default=None, max_length=MAX_TEXT)

    _clean_strings = field_validator(
        "sku", "product_name", "weight", "hsn", "tax", "location", "customization_text", "logo_reference", "notes",
        mode="before",
    )(_clean)

    _names = field_validator("customization_names", mode="before")(_clean_names)

    @field_validator("rate", "original_rate", "value", "printing_price")
    @classmethod
    def _money(cls, value: float | None) -> float | None:
        return None if value is None else round(value, 2)


class OrderUpdate(BaseModel):
    """Full Draft save. `version` must match the stored version (protects against overwriting newer edits)."""

    version: int
    po_number: str | None = Field(default=None, max_length=64)
    source_status: str | None = Field(default=None, max_length=64)
    source_order_date: str | None = Field(default=None, max_length=32)
    customer_name: str | None = Field(default=None, max_length=200)
    billing_address: str | None = Field(default=None, max_length=MAX_TEXT)
    shipping_name: str | None = Field(default=None, max_length=200)
    shipping_address: str | None = Field(default=None, max_length=MAX_TEXT)
    contact: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=200)
    gstin: str | None = Field(default=None, max_length=32)
    executive: str | None = Field(default=None, max_length=200)
    subtotal: float | None = Field(default=None, ge=0, le=1_000_000_000)
    packaging_charges: float | None = Field(default=None, ge=0, le=1_000_000_000)
    processing_charges: float | None = Field(default=None, ge=0, le=1_000_000_000)
    additional_charges: float | None = Field(default=None, ge=0, le=1_000_000_000)
    tax: float | None = Field(default=None, ge=0, le=1_000_000_000)
    total: float | None = Field(default=None, ge=0, le=1_000_000_000)
    global_customization: str | None = Field(default=None, max_length=MAX_TEXT)
    global_names: list[str] = Field(default_factory=list, max_length=100_000)
    global_logo_reference: str | None = Field(default=None, max_length=MAX_TEXT)
    global_notes: str | None = Field(default=None, max_length=MAX_TEXT)
    items: list[ItemIn] = Field(default_factory=list, max_length=500)

    _clean_strings = field_validator(
        "po_number", "source_status", "source_order_date", "customer_name", "billing_address", "shipping_name",
        "shipping_address", "contact", "email", "gstin", "executive", "global_customization",
        "global_logo_reference", "global_notes", mode="before",
    )(_clean)
    _names = field_validator("global_names", mode="before")(_clean_names)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("source_order_date")
    @classmethod
    def _date(cls, value: str | None) -> str | None:
        if value:
            try:
                datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Use the format YYYY-MM-DDTHH:MM") from exc
        return value

    @field_validator("subtotal", "packaging_charges", "processing_charges", "additional_charges", "tax", "total")
    @classmethod
    def _money(cls, value: float | None) -> float | None:
        return None if value is None else round(value, 2)


class ItemSave(ItemIn):
    """Save one product row on its own (product card "Save Changes")."""

    version: int


class GlobalUpdate(BaseModel):
    """Save only the global customization section."""

    version: int
    global_customization: str | None = Field(default=None, max_length=MAX_TEXT)
    global_names: list[str] = Field(default_factory=list, max_length=100_000)
    global_logo_reference: str | None = Field(default=None, max_length=MAX_TEXT)
    global_notes: str | None = Field(default=None, max_length=MAX_TEXT)

    _clean_strings = field_validator(
        "global_customization", "global_logo_reference", "global_notes", mode="before"
    )(_clean)
    _names = field_validator("global_names", mode="before")(_clean_names)


class PublishRequest(BaseModel):
    version: int
    reviewed: bool = Field(description="Sales confirms the data was checked against the source PDF")


class CommentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.replace("\x00", "").strip()
        if not value:
            raise ValueError("Comment cannot be empty")
        return value


class PrintingStatusRequest(BaseModel):
    status: str


class PhotoReviewRequest(BaseModel):
    """Sales confirms the post-print photos, or rejects them with a reason (Printing then uploads again)."""

    version: int
    action: Literal["confirm", "reject"]
    note: str | None = Field(default=None, max_length=MAX_TEXT)

    _clean_note = field_validator("note", mode="before")(_clean)
