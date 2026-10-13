"""Admin panel: permissions, user management, order access, audit log, settings, backups, setup."""
from __future__ import annotations

import io
import logging
import sqlite3
import zipfile

import pytest

from app.config import settings
from app.database import SessionLocal, configure_database
from app.models import Order, User

from .conftest import ADMIN_PASSWORD, REAL_PO, SALES_PASSWORD, login, make_live, make_user, save, upload

ADMIN_GETS = ["/api/admin/dashboard", "/api/admin/orders", "/api/admin/users", "/api/admin/activity",
              "/api/admin/settings", "/api/admin/backups", "/api/admin/backups/orderflow_backup_20260101_000000.zip"]
ADMIN_WRITES = [
    ("POST", "/api/admin/users", {"username": "x1x", "role": "sales", "password": "Strong-Pass-1"}),
    ("PATCH", "/api/admin/users/1", {"is_active": False}),
    ("POST", "/api/admin/users/1/reset-password", {"new_password": "Strong-Pass-1"}),
    ("PUT", "/api/admin/settings", {"max_upload_mb": 20}),
    ("POST", "/api/admin/backups", {}),
]


# ---------------------------------------------------------------- permissions
@pytest.mark.parametrize("who", ["anonymous", "sales", "printing", "bad-token"])
def test_admin_endpoints_reject_non_admins(client, who):
    fixed = {"anonymous": {}, "bad-token": {"Authorization": "Bearer nope"}}
    headers = fixed[who] if who in fixed else login(client, who)
    expected = 403 if who in ("sales", "printing") else 401
    for path in ADMIN_GETS:
        assert client.get(path, headers=headers).status_code == expected, path
    for method, path, body in ADMIN_WRITES:
        assert client.request(method, path, headers=headers, json=body).status_code == expected, path
    with SessionLocal() as db:  # nothing changed
        assert db.get(User, 1).is_active and not db.query(User).filter_by(username="x1x").count()


def test_every_admin_route_is_protected(client):
    """Guard against future admin routes added without the Admin dependency."""
    sales = login(client, "sales")
    paths = [p for p in client.app.openapi()["paths"] if p.startswith("/api/admin")]
    assert len(paths) >= 9
    for path, methods in client.app.openapi()["paths"].items():
        if not path.startswith("/api/admin"):
            continue
        concrete = path.replace("{user_id}", "1").replace("{name}", "orderflow_backup_20260101_000000.zip")
        for method in methods:
            assert client.request(method.upper(), concrete, headers=sales, json={}).status_code == 403, (method, path)


def test_admin_can_use_admin_endpoints(client, admin):
    for path in ADMIN_GETS[:-1]:
        assert client.get(path, headers=admin).status_code == 200, path
    assert client.get(ADMIN_GETS[-1], headers=admin).status_code == 404  # no such backup


def test_admin_can_do_sales_actions_but_not_printing_actions(client, admin):
    """Admin can do everything Sales can (see test_permissions.py); printing-status changes stay with Printing."""
    sales = login(client, "sales")
    live = make_live(client, sales)
    with open(REAL_PO, "rb") as fh:
        assert client.post("/api/orders/upload", headers=admin, files={"file": ("po.pdf", fh)}).status_code == 201
    assert client.post(f"/api/orders/{live['id']}/printing-status", headers=admin, json={"status": "Processing"}).status_code == 403
    assert client.post(f"/api/orders/{live['id']}/comment", headers=admin, json={"text": "hi"}).status_code == 201


# ---------------------------------------------------------------- order access
def test_admin_reads_all_orders_including_drafts_and_archived(client, admin):
    sales = login(client, "sales")
    draft = upload(client, sales)
    live = make_live(client, sales)
    gone = upload(client, sales)
    client.post(f"/api/orders/{gone['id']}/archive", headers=sales, json={"version": gone["version"]})

    data = client.get("/api/admin/orders", headers=admin).json()
    assert {o["id"] for o in data["items"]} == {draft["id"], live["id"]} and data["total"] == 2
    archived = client.get("/api/admin/orders", headers=admin, params={"status": "Archived"}).json()
    assert [o["id"] for o in archived["items"]] == [gone["id"]]

    detail = client.get(f"/api/orders/{draft['id']}", headers=admin).json()
    assert detail["status"] == "Draft"
    assert detail["permissions"] == {"can_edit": True, "can_publish": True, "can_comment": True,
                                     "next_printing_statuses": [], "can_upload_photos": False,
                                     "can_delete": True, "can_restore": False}
    assert client.get(f"/api/orders/{gone['id']}", headers=admin).status_code == 200
    assert client.get(f"/api/orders/{live['id']}/source-pdf", headers=admin).content == REAL_PO.read_bytes()
    assert client.get(f"/api/orders/{live['id']}/print", headers=admin).status_code == 200
    # Admin can also use the Sales order list
    assert client.get("/api/orders", headers=admin).status_code == 200


def test_admin_order_filters(client, admin):
    sales = login(client, "sales")
    a = make_live(client, sales)
    b = save(client, sales, upload(client, sales), customer_name="Zeta Traders")
    get = lambda **p: [o["id"] for o in client.get("/api/admin/orders", headers=admin, params=p).json()["items"]]  # noqa: E731
    assert get(q=a["internal_order_no"]) == [a["id"]]
    assert get(q="zeta") == [b["id"]]
    assert get(q="creative_lamp") == sorted([a["id"], b["id"]], reverse=True)  # SKU search
    assert get(status="Live") == [a["id"]] and get(status="Draft") == [b["id"]]
    assert get(printing_status="New") == [a["id"]]
    today = a["live_at"][:10]
    assert a["id"] in get(date_field="live", date_from=today, date_to=today)
    assert get(date_field="created", date_from="2000-01-01", date_to="2000-01-02") == []
    assert client.get("/api/admin/orders", headers=admin, params={"printing_status": "Bogus"}).status_code == 400
    assert client.get("/api/admin/orders", headers=admin, params={"date_from": "not-a-date"}).status_code == 422


def test_admin_dashboard_counts(client, admin):
    sales = login(client, "sales")
    make_live(client, sales)
    upload(client, sales)
    d = client.get("/api/admin/dashboard", headers=admin).json()
    assert d["orders"] | {} == {"total": 2, "draft": 1, "live": 1, "archived": 0, "new": 1, "processing": 0, "print_done": 0}
    assert d["users"]["admin"]["active"] == 1 and d["users"]["sales"]["active"] == 1
    assert len(d["trend"]) == 14 and d["trend"][-1]["created"] == 2 and d["trend"][-1]["published"] == 1
    assert len(d["oldest_open"]) == 1 and d["recent_activity"]


# ---------------------------------------------------------------- user management
def test_create_edit_and_list_users(client, admin):
    r = client.post("/api/admin/users", headers=admin, json={
        "username": "  Priya.S ", "full_name": " Priya Shah ", "role": "sales", "password": "Priya-Pass-1"})
    assert r.status_code == 201, r.text
    user = r.json()
    assert user["username"] == "priya.s" and user["full_name"] == "Priya Shah" and user["role"] == "sales"
    assert "password" not in str(user).lower()
    assert client.post("/api/login", json={"username": "priya.s", "password": "Priya-Pass-1"}).status_code == 200

    r = client.patch(f"/api/admin/users/{user['id']}", headers=admin, json={"full_name": "Priya S", "role": "printing"})
    assert r.status_code == 200 and r.json()["role"] == "printing" and r.json()["full_name"] == "Priya S"
    listed = client.get("/api/admin/users", headers=admin).json()["items"]
    assert {u["username"] for u in listed} >= {"admin", "sales", "printing", "priya.s"}
    assert all("password_hash" not in u for u in listed)


@pytest.mark.parametrize("body,code", [
    ({"username": "sales", "role": "sales", "password": "Strong-Pass-1"}, 409),      # duplicate
    ({"username": "ab", "role": "sales", "password": "Strong-Pass-1"}, 422),         # too short
    ({"username": "bad name", "role": "sales", "password": "Strong-Pass-1"}, 422),   # invalid chars
    ({"username": "newuser", "role": "manager", "password": "Strong-Pass-1"}, 422),  # unknown role
    ({"username": "newuser", "role": "sales", "password": "short1"}, 422),           # weak password
    ({"username": "newuser", "role": "sales", "password": "onlyletters"}, 422),
])
def test_create_user_validation(client, admin, body, code):
    assert client.post("/api/admin/users", headers=admin, json=body).status_code == code


def test_deactivate_and_role_change_end_sessions(client, admin):
    sales = login(client, "sales")
    sales_id = next(u["id"] for u in client.get("/api/admin/users", headers=admin).json()["items"] if u["username"] == "sales")
    assert client.patch(f"/api/admin/users/{sales_id}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.get("/api/me", headers=sales).status_code == 401
    assert client.post("/api/login", json={"username": "sales", "password": SALES_PASSWORD}).status_code == 401
    assert client.patch(f"/api/admin/users/{sales_id}", headers=admin, json={"is_active": True}).status_code == 200
    sales = login(client, "sales")
    assert client.patch(f"/api/admin/users/{sales_id}", headers=admin, json={"role": "printing"}).status_code == 200
    assert client.get("/api/me", headers=sales).status_code == 401  # old token carries the old role
    me = client.get("/api/me", headers=login(client, "sales")).json()["user"]
    assert me["role"] == "printing"


def test_reset_password(client, admin, caplog):
    sales = login(client, "sales")
    sales_id = next(u["id"] for u in client.get("/api/admin/users", headers=admin).json()["items"] if u["username"] == "sales")
    with caplog.at_level(logging.DEBUG):
        r = client.post(f"/api/admin/users/{sales_id}/reset-password", headers=admin, json={"new_password": "New-Sales-Pass-9"})
    assert r.status_code == 200
    assert "New-Sales-Pass-9" not in caplog.text  # never logged
    assert client.get("/api/me", headers=sales).status_code == 401  # signed out everywhere
    assert client.post("/api/login", json={"username": "sales", "password": SALES_PASSWORD}).status_code == 401
    assert client.post("/api/login", json={"username": "sales", "password": "New-Sales-Pass-9"}).status_code == 200
    assert client.post(f"/api/admin/users/{sales_id}/reset-password", headers=admin, json={"new_password": "weak"}).status_code == 422
    assert client.post("/api/admin/users/9999/reset-password", headers=admin, json={"new_password": "New-Sales-Pass-9"}).status_code == 404
    log = client.get("/api/admin/activity", headers=admin, params={"action": "password_reset"}).json()["items"]
    assert log and "New-Sales-Pass-9" not in str(log)


def test_admin_cannot_lock_out_admins(client, admin):
    me = next(u for u in client.get("/api/admin/users", headers=admin).json()["items"] if u["username"] == "admin")
    assert client.patch(f"/api/admin/users/{me['id']}", headers=admin, json={"is_active": False}).status_code == 409
    assert client.patch(f"/api/admin/users/{me['id']}", headers=admin, json={"role": "sales"}).status_code == 409
    # a second admin can be managed, but the last active admin is protected
    second = client.post("/api/admin/users", headers=admin, json={"username": "admin2", "role": "admin", "password": "Second-Admin-1"}).json()
    assert client.patch(f"/api/admin/users/{second['id']}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.post("/api/login", json={"username": "admin2", "password": "Second-Admin-1"}).status_code == 401
    assert client.patch("/api/admin/users/9999", headers=admin, json={"is_active": False}).status_code == 404


def test_last_admin_protected_even_by_another_admin(client, admin):
    second = client.post("/api/admin/users", headers=admin, json={"username": "admin2", "role": "admin", "password": "Second-Admin-1"}).json()
    other = login(client, "admin2", "Second-Admin-1")
    first_id = next(u["id"] for u in client.get("/api/admin/users", headers=other).json()["items"] if u["username"] == "admin")
    assert client.patch(f"/api/admin/users/{first_id}", headers=other, json={"role": "sales"}).status_code == 200
    # now admin2 is the only active admin; nobody may remove that
    assert client.patch(f"/api/admin/users/{second['id']}", headers=other, json={"is_active": False}).status_code == 409


# ---------------------------------------------------------------- audit log
def test_activity_log_shows_who_did_what(client, admin):
    sales, printing = login(client, "sales"), login(client, "printing")
    live = make_live(client, sales)
    client.post(f"/api/orders/{live['id']}/printing-status", headers=printing, json={"status": "Processing"})
    client.post("/api/admin/users", headers=admin, json={"username": "newbie", "role": "sales", "password": "Newbie-Pass-1"})
    client.post("/api/login", json={"username": "sales", "password": "wrong-pass"})
    client.post("/api/login", json={"username": "Secret-Pass-Typed-In-Username", "password": "x"})

    items = client.get("/api/admin/activity", headers=admin, params={"limit": 200}).json()["items"]
    seen = {(i["actor"], i["action"]) for i in items}
    for expected in [("sales", "pdf_uploaded"), ("sales", "draft_saved"), ("sales", "published"),
                     ("printing", "printing_status_changed"), ("admin", "user_created"), ("sales", "login_failed"),
                     ("(unknown user)", "login_failed"), ("admin", "login")]:
        assert expected in seen, expected
    assert "Secret-Pass-Typed-In-Username".lower() not in str(items).lower()  # never stored
    published = next(i for i in items if i["action"] == "published")
    assert published["target"] == live["internal_order_no"] and published["order_id"] == live["id"]
    times = [i["created_at"] for i in items]
    assert times == sorted(times, reverse=True)

    get = lambda **p: client.get("/api/admin/activity", headers=admin, params=p).json()  # noqa: E731
    assert {i["actor"] for i in get(actor="printing", source="order")["items"]} == {"printing"}
    assert {i["action"] for i in get(action="published")["items"]} == {"published"}
    assert all(i["source"] == "admin" for i in get(source="admin")["items"])
    assert {i["order_id"] for i in get(q=live["internal_order_no"])["items"]} == {live["id"]}
    assert get(date_from="2000-01-01", date_to="2000-01-02")["total"] == 0
    page1, page2 = get(limit=3, offset=0), get(limit=3, offset=3)
    assert page1["total"] == page2["total"] and not {i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]}


# ---------------------------------------------------------------- settings
def test_settings_update_applies_persists_and_is_audited(client, admin):
    r = client.put("/api/admin/settings", headers=admin, json={"max_upload_mb": 20, "token_expire_minutes": 600})
    assert r.status_code == 200, r.text
    assert r.json()["editable"] == {"max_upload_mb": 20, "token_expire_minutes": 600}
    assert settings.max_upload_bytes == 20 * 1024 * 1024 and settings.token_expire_minutes == 600  # applied immediately

    settings.max_upload_bytes, settings.token_expire_minutes = 15 * 1024 * 1024, 480  # simulate a restart with .env defaults
    with SessionLocal() as db:
        from app import runtime_settings
        runtime_settings.load_overrides(db)
    assert settings.max_upload_bytes == 20 * 1024 * 1024 and settings.token_expire_minutes == 600
    log = client.get("/api/admin/activity", headers=admin, params={"action": "settings_updated"}).json()["items"]
    assert log and "max upload mb: 15 → 20" in log[0]["details"]


def test_old_removed_settings_are_ignored(client, admin):
    """Values saved for settings that no longer exist (courier suggestions, export permission) do no harm."""
    from app.models import AppSetting

    with SessionLocal() as db:
        db.add(AppSetting(key="courier_options", value=["DTDC"], updated_by="admin"))
        db.add(AppSetting(key="printing_can_export", value=True, updated_by="admin"))
        db.commit()
        from app import runtime_settings
        runtime_settings.load_overrides(db)
    assert client.get("/api/admin/settings", headers=admin).json()["editable"] == {
        "max_upload_mb": settings.max_upload_bytes // (1024 * 1024), "token_expire_minutes": settings.token_expire_minutes}
    assert not hasattr(settings, "courier_options") and not hasattr(settings, "printing_can_export")


@pytest.mark.parametrize("body", [{"max_upload_mb": 0}, {"max_upload_mb": 500}, {"token_expire_minutes": 1},
                                  {"token_expire_minutes": 5000}])
def test_settings_validation(client, admin, body):
    assert client.put("/api/admin/settings", headers=admin, json=body).status_code == 422


def test_secrets_are_not_editable_or_exposed(client, admin):
    data = client.get("/api/admin/settings", headers=admin).json()
    assert settings.secret_key not in str(data)
    client.put("/api/admin/settings", headers=admin, json={"secret_key": "hacked", "database_path": "x.db"})
    assert settings.secret_key != "hacked" and str(settings.database_path).endswith("test.db")


# ---------------------------------------------------------------- backups
def test_backup_create_list_download(client, admin):
    sales = login(client, "sales")
    live = make_live(client, sales)
    r = client.post("/api/admin/backups", headers=admin, json={"include_uploads": True})
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["name"].startswith("orderflow_backup_") and info["upload_files"] >= 1
    assert [b["name"] for b in client.get("/api/admin/backups", headers=admin).json()["items"]] == [info["name"]]

    blob = client.get(f"/api/admin/backups/{info['name']}", headers=admin).content
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = zf.namelist()
    assert "order_portal.db" in names and "manifest.json" in names and any(n.startswith("uploads/po/") for n in names)
    db_copy = settings.backup_dir / "check.db"
    db_copy.write_bytes(zf.read("order_portal.db"))
    con = sqlite3.connect(db_copy)
    assert con.execute("select internal_order_no from orders where id=?", (live["id"],)).fetchone()[0] == live["internal_order_no"]
    con.close()
    acts = {i["action"] for i in client.get("/api/admin/activity", headers=admin, params={"source": "admin"}).json()["items"]}
    assert {"backup_created", "backup_downloaded"} <= acts


@pytest.mark.parametrize("name", ["..%2F..%2Ftest.db", "test.db", "orderflow_backup_x.zip", "..\\order_portal.db",
                                  "orderflow_backup_20260101_000000.zip.partial"])
def test_backup_download_rejects_other_files(client, admin, name):
    assert client.get(f"/api/admin/backups/{name}", headers=admin).status_code == 404


# ---------------------------------------------------------------- first Admin setup + upgrade
def test_bootstrap_admin_from_environment(client, monkeypatch, caplog):
    from app.security_seed import bootstrap_admin

    with SessionLocal() as db, caplog.at_level(logging.DEBUG):
        assert "rejected" in bootstrap_admin(db, "boss", "weak")
        assert "already exists with another role" in bootstrap_admin(db, "sales", "Boss-Pass-2026")
        msg = bootstrap_admin(db, "Boss", "Boss-Pass-2026")
        assert "created Admin account 'boss'" in msg
        assert "already exists" in bootstrap_admin(db, "other", "Other-Pass-2026")  # only when no Admin exists
    assert "Boss-Pass-2026" not in caplog.text
    assert client.post("/api/login", json={"username": "boss", "password": "Boss-Pass-2026"}).json()["user"]["role"] == "admin"


def test_bootstrap_runs_on_startup(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "database_path", tmp_path / "boot.db")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "up")
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "bk")
    monkeypatch.setenv("ADMIN_USERNAME", "owner")
    monkeypatch.setenv("ADMIN_PASSWORD", "Owner-Pass-2026")
    with TestClient(app) as c:
        assert c.post("/api/login", json={"username": "owner", "password": "Owner-Pass-2026"}).status_code == 200


def test_cli_create_admin(client, monkeypatch, capsys):
    from app import manage

    answers = iter(["Cli-Admin-Pass-1", "Cli-Admin-Pass-1"])
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt="": next(answers))
    assert manage.main(["create-admin", "cliadmin"]) == 0
    assert "Cli-Admin-Pass-1" not in capsys.readouterr().out
    configure_database(settings.database_path, settings.backup_dir)  # the CLI rebinds the engine; rebind for the app
    r = client.post("/api/login", json={"username": "cliadmin", "password": "Cli-Admin-Pass-1"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"


def test_upgrade_keeps_existing_users_and_orders(tmp_path):
    """A database created before the Admin role existed is upgraded in place without losing anything."""
    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL, full_name VARCHAR(120),
            password_hash VARCHAR(200) NOT NULL, role VARCHAR(16) NOT NULL, is_active BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL, CONSTRAINT ck_users_role CHECK (role in ('sales','printing')));
        CREATE UNIQUE INDEX ix_users_username ON users (username);
        INSERT INTO users VALUES (7, 'sales', 'S', 'hash-s', 'sales', 1, '2026-10-01 10:00:00');
        INSERT INTO users VALUES (9, 'printing', 'P', 'hash-p', 'printing', 0, '2026-10-01 10:00:00');
    """)
    con.commit()
    con.close()
    configure_database(old, tmp_path / "bk")
    snapshots = sorted(p.name.split("_2")[0] for p in (tmp_path / "bk").iterdir())
    assert snapshots == ["pre_admin_upgrade", "pre_schema_update"]  # users rebuild + new tables, each backed up first
    with SessionLocal() as db:
        users = {u.id: (u.username, u.password_hash, u.role, u.is_active, u.session_version) for u in db.query(User)}
        assert users == {7: ("sales", "hash-s", "sales", True, 0), 9: ("printing", "hash-p", "printing", False, 0)}
        db.add(User(username="root", role="admin", password_hash="h"))
        db.commit()
        assert db.query(Order).count() == 0
    configure_database(old, tmp_path / "bk")  # second start: nothing to do, no extra snapshot
    assert len(list((tmp_path / "bk").iterdir())) == 2
