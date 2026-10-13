"""Admin-editable settings.

Only a small whitelist of operational values can be changed from the Admin panel (upload size, session length).
Values saved earlier for settings that no longer exist are ignored. Secrets, paths, the time zone
and the order-number prefix stay in backend/.env on purpose (changing them at runtime is unsafe).
Values saved by an Admin are stored in the app_settings table and override the .env defaults.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AppSetting


class EditableSettings(BaseModel):
    max_upload_mb: int = Field(ge=1, le=50)
    token_expire_minutes: int = Field(ge=15, le=1440)


class SettingsUpdate(BaseModel):
    """Partial update: only the fields provided are changed."""

    max_upload_mb: int | None = Field(default=None, ge=1, le=50)
    token_expire_minutes: int | None = Field(default=None, ge=15, le=1440)


def current() -> EditableSettings:
    """Effective values, shown in the Admin page. .env values outside the UI ranges are clamped for display only;
    they keep their real value until an Admin changes that particular setting."""
    return EditableSettings.model_construct(
        max_upload_mb=min(50, max(1, settings.max_upload_bytes // (1024 * 1024))),
        token_expire_minutes=min(1440, max(15, settings.token_expire_minutes)),
    )


def _apply(values: EditableSettings, keys) -> None:
    """Apply only the given keys (untouched settings keep their .env value)."""
    if "max_upload_mb" in keys:
        settings.max_upload_bytes = values.max_upload_mb * 1024 * 1024
    if "token_expire_minutes" in keys:
        settings.token_expire_minutes = values.token_expire_minutes


def load_overrides(db: Session) -> None:
    """Apply saved Admin settings on startup. Invalid stored values are ignored (the .env value stays)."""
    stored = {row.key: row.value for row in db.scalars(select(AppSetting))}
    if not stored:
        return
    merged = current().model_dump()
    for key in EditableSettings.model_fields:
        if key in stored:
            merged[key] = stored[key]
    try:
        _apply(EditableSettings(**merged), [k for k in EditableSettings.model_fields if k in stored])
    except ValueError:
        pass


def update(db: Session, patch: SettingsUpdate, actor: str) -> dict[str, tuple[Any, Any]]:
    """Validate, store and apply a settings change. Returns {key: (old, new)} for changed keys."""
    before = current()
    after = EditableSettings(**{**before.model_dump(), **patch.model_dump(exclude_none=True)})
    changes = {k: (getattr(before, k), getattr(after, k)) for k in EditableSettings.model_fields
               if getattr(before, k) != getattr(after, k)}
    for key, (_old, new) in changes.items():
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=new, updated_by=actor))
        else:
            row.value, row.updated_by = new, actor
    _apply(after, changes.keys())
    return changes
