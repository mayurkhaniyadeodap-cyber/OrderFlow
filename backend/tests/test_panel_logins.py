"""Admin / Sales / Printing logins configured through environment variables (backend/.env), and role access.

The values here are test-only; the real credentials live only in backend/.env.
"""
from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import AdminEvent, User
from app.security import login_throttle

from .conftest import make_live, upload

CONFIGURED = {  # role: (username as typed on the login page, password)
    "admin": ("Admin", "Test-Admin-Pass-1"),
    "sales": ("sales", "Test-Sales-Pass-1"),
    "printing": ("printing", "Test-Print-Pass-1"),
}
ROOT = Path(__file__).resolve().parents[2]


def set_env(monkeypatch, accounts: dict[str, tuple[str, str]]) -> None:
    for role in ("admin", "sales", "printing"):
        for suffix in ("USERNAME", "PASSWORD"):
            monkeypatch.delenv(f"{role.upper()}_{suffix}", raising=False)
    for role, (username, password) in accounts.items():
        monkeypatch.setenv(f"{role.upper()}_USERNAME", username)
        monkeypatch.setenv(f"{role.upper()}_PASSWORD", password)


@pytest.fixture()
def start(tmp_path, monkeypatch):
    """Start (and restart) the app on one fresh database, like starting the backend again."""
    monkeypatch.setattr(settings, "database_path", tmp_path / "accounts.db")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups")
    login_throttle._fails.clear()

    @contextmanager
    def _start(accounts=CONFIGURED):
        set_env(monkeypatch, accounts)
        with TestClient(app) as c:
            yield c
    return _start


def sign_in(c: TestClient, username: str, password: str) -> dict:
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, (username, r.text)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def users() -> dict[str, User]:
    with SessionLocal() as db:
        return {u.username: u for u in db.query(User)}


def test_accounts_created_from_environment_and_sign_in(start, caplog):
    with caplog.at_level(logging.DEBUG), start() as c:
        for role, (username, password) in CONFIGURED.items():
            me = c.get("/api/me", headers=sign_in(c, username, password)).json()["user"]
            assert me["role"] == role and me["username"] == username.lower()
        with SessionLocal() as db:
            created = {e.target for e in db.query(AdminEvent).filter_by(action="user_created", actor="system")}
    assert created == {"admin", "sales", "printing"}
    for _, password in CONFIGURED.values():
        assert password not in caplog.text  # never logged


def test_passwords_stored_only_as_bcrypt_hashes(start):
    with start():
        accounts = users()
    assert set(accounts) == {"admin", "sales", "printing"}  # one account per panel
    for role, (username, password) in CONFIGURED.items():
        user = accounts[username.lower()]
        assert user.role == role and user.is_active
        assert user.password_hash.startswith("$2") and password not in user.password_hash
        assert bcrypt.checkpw(password.encode(), user.password_hash.encode())


def test_restart_never_resets_passwords_or_duplicates_accounts(start):
    with start():
        before = {name: (u.id, u.role, u.password_hash) for name, u in users().items()}
    changed = {role: (username, "Changed-Pass-99") for role, (username, _) in CONFIGURED.items()}
    with start(changed) as c:
        assert {name: (u.id, u.role, u.password_hash) for name, u in users().items()} == before
        for role, (username, password) in CONFIGURED.items():
            sign_in(c, username, password)  # the original passwords still work
            assert c.post("/api/login", json={"username": username, "password": "Changed-Pass-99"}).status_code == 401


def test_renamed_or_deactivated_account_is_not_recreated(start):
    with start():
        with SessionLocal() as db:
            db.query(User).filter_by(username="sales").update({"username": "priya"})
            db.query(User).filter_by(username="printing").update({"is_active": False})
            db.commit()
    with start():
        accounts = users()
    assert "sales" not in accounts and accounts["priya"].role == "sales"
    assert not accounts["printing"].is_active and len(accounts) == 3


@pytest.mark.parametrize("password", ["", "weak", "onlyletters"])
def test_missing_or_weak_password_creates_nothing(start, password):
    accounts = dict(CONFIGURED, sales=("sales", password))
    with start(accounts) as c:
        assert "sales" not in users()
        sign_in(c, "printing", CONFIGURED["printing"][1])  # the other accounts are unaffected


@pytest.mark.parametrize("username,password", [
    ("Admin", "test-admin-pass-1"),         # passwords are case-sensitive
    ("sales", "Test-Print-Pass-1"),         # another panel's password
    ("printing", "Test-Sales-Pass-1"),
])
def test_wrong_passwords_rejected(start, username, password):
    with start() as c:
        assert c.post("/api/login", json={"username": username, "password": password}).status_code == 401


def test_role_based_access(start):
    with start() as c:
        admin, sales, printing = (sign_in(c, *CONFIGURED[r]) for r in ("admin", "sales", "printing"))
        for path in ("/api/admin/dashboard", "/api/admin/users", "/api/admin/activity", "/api/admin/settings"):
            assert c.get(path, headers=admin).status_code == 200, path
            assert c.get(path, headers=sales).status_code == 403, path
            assert c.get(path, headers=printing).status_code == 403, path
        upload(c, admin)  # Sales and Admin manage orders, Printing does not
        live = make_live(c, sales)
        assert c.post("/api/orders/upload", headers=printing,
                      files={"file": ("po.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 403
        for headers in (sales, admin):  # printing status: Printing only
            r = c.post(f"/api/orders/{live['id']}/printing-status", headers=headers, json={"status": "Processing"})
            assert r.status_code == 403
        r = c.post(f"/api/orders/{live['id']}/printing-status", headers=printing, json={"status": "Processing"})
        assert r.status_code == 200 and r.json()["printing_status"] == "Processing"
        for headers in (admin, sales, printing):
            assert c.get(f"/api/orders/{live['id']}", headers=headers).status_code == 200


def test_env_example_has_only_placeholder_passwords():
    text = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    values = dict(re.findall(r"^(\w+_PASSWORD)=(.*)$", text, re.M))
    assert set(values) >= {"ADMIN_PASSWORD", "SALES_PASSWORD", "PRINTING_PASSWORD"}
    assert all(v.strip() == "" for v in values.values()), values


def test_docs_contain_no_password_values():
    """Documentation may name the variables but never give them a value."""
    for doc in ("README.md", "DEPLOYMENT.md", "PROJECT.md"):
        path = ROOT / doc
        if path.exists():
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"_PASSWORD=(?!\s|$|<|…)\S", text, re.M), doc


def test_env_files_are_git_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored and "!.env.example" in ignored
