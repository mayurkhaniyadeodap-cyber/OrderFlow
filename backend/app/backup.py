"""Database + uploads backups (ZIP files in BACKUP_DIR).

A backup contains a consistent SQLite snapshot (taken with the SQLite backup API, safe while the portal runs),
the uploads folder (PO PDFs, logos, photos) and a manifest. Restoring is deliberately a manual, offline step
(see README): stop the backend, replace order_portal.db and uploads/, start the backend.
"""
from __future__ import annotations

import json
import re
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from .config import settings
from .database import snapshot_database

NAME_RE = re.compile(r"^orderflow_backup_\d{8}_\d{6}(?:_\d+)?\.zip$")
_lock = threading.Lock()  # one backup at a time: names and files can never collide


def create_backup(created_by: str, include_uploads: bool = True) -> dict:
    with _lock:
        return _create_backup(created_by, include_uploads)


def _create_backup(created_by: str, include_uploads: bool) -> dict:
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(settings.timezone).strftime("%Y%m%d_%H%M%S")
    target = settings.backup_dir / f"orderflow_backup_{stamp}.zip"
    n = 1
    while target.exists():
        target = settings.backup_dir / f"orderflow_backup_{stamp}_{n}.zip"
        n += 1
    upload_files = 0
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = snapshot_database(settings.database_path, Path(tmp) / "order_portal.db")
        partial = settings.backup_dir / f".{target.stem}.{uuid.uuid4().hex}.partial"
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(snapshot, "order_portal.db")
                if include_uploads and settings.upload_dir.is_dir():
                    for f in sorted(settings.upload_dir.rglob("*")):
                        if f.is_file():
                            zf.write(f, f"uploads/{f.relative_to(settings.upload_dir).as_posix()}")
                            upload_files += 1
                zf.writestr("manifest.json", json.dumps({
                    "created_at": datetime.now(settings.timezone).isoformat(timespec="seconds"),
                    "created_by": created_by,
                    "database": "order_portal.db",
                    "upload_files": upload_files,
                    "includes_uploads": include_uploads,
                }, indent=2))
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    return describe(target) | {"upload_files": upload_files}


def describe(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, settings.timezone).isoformat(timespec="seconds"),
    }


def list_backups() -> list[dict]:
    if not settings.backup_dir.is_dir():
        return []
    files = [p for p in settings.backup_dir.iterdir() if p.is_file() and NAME_RE.match(p.name)]
    return [describe(p) for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]


def resolve_backup(name: str) -> Path | None:
    """Return the backup path for a listed name, or None. Only exact generated names are accepted."""
    if not NAME_RE.match(name):
        return None
    path = (settings.backup_dir / name).resolve()
    if path.parent != settings.backup_dir.resolve() or not path.is_file():
        return None
    return path
