"""Live-server switches: API docs can be turned off, and `python -m app.manage backup` for scheduled backups."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from app import manage
from app.config import settings
from app.database import SessionLocal, configure_database
from app.models import AdminEvent

from .conftest import login, make_live

BACKEND_DIR = Path(__file__).resolve().parents[1]
DOCS_PROBE = ("import json; from app.main import app; "
              "print(json.dumps([app.docs_url, app.redoc_url, app.openapi_url, len(app.openapi()['paths'])]))")


def probe_docs(value: str | None) -> list:
    """Import the app in a fresh interpreter (the setting is read at import time). The app is not started."""
    env = {k: v for k, v in os.environ.items() if k != "ENABLE_API_DOCS"}
    if value is not None:
        env["ENABLE_API_DOCS"] = value
    out = subprocess.run([sys.executable, "-c", DOCS_PROBE], cwd=BACKEND_DIR, env=env,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_api_docs_on_by_default():
    docs, redoc, openapi, paths = probe_docs(None)
    assert (docs, redoc, openapi) == ("/docs", "/redoc", "/openapi.json") and paths > 30


def test_api_docs_can_be_switched_off():
    docs, redoc, openapi, paths = probe_docs("false")
    assert (docs, redoc, openapi) == (None, None, None)
    assert paths > 30  # only the documentation pages go away, not the API


def test_docs_pages_served_in_tests(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def run_backup(capsys, *args):
    code = manage.main(["backup", *args])
    out = capsys.readouterr().out
    configure_database(settings.database_path, settings.backup_dir)  # the CLI rebinds the engine; rebind for the app
    return code, out


def test_backup_command_creates_zip_and_audit_row(client, capsys):
    sales = login(client, "sales")
    live = make_live(client, sales)
    code, out = run_backup(capsys)
    assert code == 0 and "Backup saved:" in out
    [zip_path] = settings.backup_dir.glob("orderflow_backup_*.zip")
    names = zipfile.ZipFile(zip_path).namelist()
    assert "order_portal.db" in names and "manifest.json" in names
    assert any(n.startswith("uploads/") for n in names)  # the uploaded PO is included
    with SessionLocal() as db:
        [event] = db.query(AdminEvent).filter_by(action="backup_created").all()
        assert event.actor == "command-line" and event.target == zip_path.name
    # the portal keeps working with its data after the command
    assert client.get(f"/api/orders/{live['id']}", headers=sales).status_code == 200


def test_backup_command_database_only(client, capsys):
    sales = login(client, "sales")
    make_live(client, sales)
    code, _ = run_backup(capsys, "--no-uploads")
    assert code == 0
    [zip_path] = settings.backup_dir.glob("orderflow_backup_*.zip")
    names = zipfile.ZipFile(zip_path).namelist()
    assert "order_portal.db" in names and not any(n.startswith("uploads/") for n in names)
