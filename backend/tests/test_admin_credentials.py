"""`python -m app.manage set-admin-credentials`: back up, then create or update the single Admin login."""
from __future__ import annotations

import io
import zipfile

from app import manage
from app.config import settings
from app.database import SessionLocal, configure_database
from app.models import Order, User

from .conftest import ADMIN_PASSWORD, SALES_PASSWORD, login, make_live, make_user

NEW_PASSWORD = "Test-Admin-Pass-1"


def run(monkeypatch, capsys, *args, password=NEW_PASSWORD):
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    code = manage.main(["set-admin-credentials", *args, "--password-stdin"])
    out = capsys.readouterr().out
    configure_database(settings.database_path, settings.backup_dir)  # the CLI rebinds the engine; rebind for the app
    return code, out


def admins():
    with SessionLocal() as db:
        return [(u.id, u.username, u.is_active) for u in db.query(User).filter_by(role="admin").order_by(User.id)]


def test_creates_admin_when_none_exists(client, monkeypatch, capsys):
    sales = login(client, "sales")
    live = make_live(client, sales)
    code, out = run(monkeypatch, capsys, "Admin")
    assert code == 0 and "Created Admin account 'admin'" in out
    assert NEW_PASSWORD not in out  # never printed
    backups = list(settings.backup_dir.glob("orderflow_backup_*.zip"))
    assert len(backups) == 1 and "order_portal.db" in zipfile.ZipFile(backups[0]).namelist()

    r = client.post("/api/login", json={"username": "Admin", "password": NEW_PASSWORD})  # case-insensitive username
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for path in ("/api/admin/dashboard", "/api/admin/orders", "/api/admin/users", "/api/admin/activity",
                 "/api/admin/settings", "/api/admin/backups", f"/api/orders/{live['id']}"):
        assert client.get(path, headers=headers).status_code == 200, path
    # existing data untouched
    with SessionLocal() as db:
        assert {u.username for u in db.query(User)} == {"sales", "printing", "admin"}
        assert db.get(Order, live["id"]).internal_order_no == live["internal_order_no"]
    assert client.post("/api/login", json={"username": "sales", "password": SALES_PASSWORD}).status_code == 200


def test_updates_existing_admin_without_duplicates(client, admin, monkeypatch, capsys):
    """An Admin named differently is renamed to 'admin' and gets the new password; old sessions end."""
    with SessionLocal() as db:
        db.query(User).filter_by(username="admin").update({"username": "owner"})
        db.commit()
    old_token = login(client, "owner", ADMIN_PASSWORD)
    [(admin_id, _, _)] = admins()
    code, out = run(monkeypatch, capsys, "Admin")
    assert code == 0 and "renamed from 'owner'" in out
    assert admins() == [(admin_id, "admin", True)]  # same account, no duplicate
    assert client.get("/api/me", headers=old_token).status_code == 401
    assert client.post("/api/login", json={"username": "owner", "password": ADMIN_PASSWORD}).status_code == 401
    assert client.post("/api/login", json={"username": "Admin", "password": NEW_PASSWORD}).status_code == 200


def test_updates_password_of_existing_admin_named_admin(client, admin, monkeypatch, capsys):
    make_user("second", "admin")
    before = admins()
    code, out = run(monkeypatch, capsys, "admin")
    assert code == 0 and "Updated Admin account 'admin'" in out
    assert admins() == before  # nothing created, nothing renamed
    assert client.post("/api/login", json={"username": "admin", "password": NEW_PASSWORD}).status_code == 200
    assert client.post("/api/login", json={"username": "second", "password": ADMIN_PASSWORD}).status_code == 200


def test_refuses_to_take_over_a_non_admin_named_admin(client, monkeypatch, capsys):
    make_user("admin", "sales", password="Sales-Pass-9")
    code, out = run(monkeypatch, capsys, "Admin")
    assert code == 1 and "already exists as a sales user" in out
    assert admins() == []
    assert client.post("/api/login", json={"username": "admin", "password": "Sales-Pass-9"}).status_code == 200


def test_rejects_weak_password_before_changing_anything(client, admin, monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, "Admin", password="admin")
    assert code == 1 and "Password rejected" in out and "admin\n" not in out.split("Password rejected")[0]
    assert not list(settings.backup_dir.glob("orderflow_backup_*.zip"))  # rejected before the backup step
    assert client.post("/api/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200
