"""Application settings loaded from environment variables / backend/.env."""
from __future__ import annotations

import os
import secrets
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

_INSECURE_SECRETS = {"", "change-me-to-a-long-random-string"}


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else BACKEND_DIR / p


@dataclass
class Settings:
    secret_key: str = ""
    secret_is_ephemeral: bool = False
    token_expire_minutes: int = 480
    database_path: Path = field(default_factory=lambda: BACKEND_DIR / "order_portal.db")
    upload_dir: Path = field(default_factory=lambda: BACKEND_DIR / "uploads")
    backup_dir: Path = field(default_factory=lambda: BACKEND_DIR / "backups")
    max_upload_bytes: int = 15 * 1024 * 1024
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Kolkata"))
    order_number_prefix: str = "OF"
    cors_origins: list[str] = field(default_factory=list)
    enable_api_docs: bool = True


def load_settings() -> Settings:
    secret = os.getenv("SECRET_KEY", "").strip()
    ephemeral = False
    if secret in _INSECURE_SECRETS:
        # A random per-process secret keeps tokens unforgeable; users simply sign in again after a restart.
        secret = secrets.token_urlsafe(48)
        ephemeral = True
        warnings.warn("SECRET_KEY is not set in backend/.env; using a temporary secret (sessions end on restart).")
    return Settings(
        secret_key=secret,
        secret_is_ephemeral=ephemeral,
        token_expire_minutes=int(os.getenv("TOKEN_EXPIRE_MINUTES", "480")),
        database_path=_path("DATABASE_PATH", "order_portal.db"),
        upload_dir=_path("UPLOAD_DIR", "uploads"),
        backup_dir=_path("BACKUP_DIR", "backups"),
        max_upload_bytes=int(float(os.getenv("MAX_UPLOAD_MB", "15")) * 1024 * 1024),
        timezone=ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata")),
        order_number_prefix=os.getenv("ORDER_NUMBER_PREFIX", "OF").strip() or "OF",
        cors_origins=_list("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"),
        enable_api_docs=_bool("ENABLE_API_DOCS", True),
    )


settings = load_settings()
