"""Regression tests for issues found by the adversarial security review of the Admin panel."""
from __future__ import annotations

import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import database
from app.config import settings
from app.database import SessionLocal, configure_database
from app.models import AdminEvent, User

from .conftest import login, make_user


def _legacy_db(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL, full_name VARCHAR(120),
            password_hash VARCHAR(200) NOT NULL, role VARCHAR(16) NOT NULL, is_active BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL, CONSTRAINT ck_users_role CHECK (role in ('sales','printing')));
        CREATE UNIQUE INDEX ix_users_username ON users (username);
        INSERT INTO users VALUES (7, 'sales', 'S', 'hash-s', 'sales', 1, '2026-10-01 10:00:00');
        INSERT INTO users VALUES (9, 'printing', 'P', 'hash-p', 'printing', 1, '2026-10-01 10:00:00');
    """)
    con.commit()
    con.close()


def _users(path):
    con = sqlite3.connect(path)
    try:
        sql = con.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
        rows = con.execute("SELECT id, username, password_hash, role FROM users ORDER BY id").fetchall()
        leftovers = con.execute("SELECT count(*) FROM sqlite_master WHERE name='users_pre_admin'").fetchone()[0]
        return sql, rows, leftovers
    finally:
        con.close()


# ---------------------------------------------------------------- 1. atomic schema upgrade
def test_failed_upgrade_leaves_users_untouched(tmp_path, monkeypatch):
    db = tmp_path / "legacy.db"
    _legacy_db(db)

    def boom(cur, cols):
        raise RuntimeError("disk full (simulated)")

    monkeypatch.setattr(database, "_copy_user_rows", boom)
    with pytest.raises(RuntimeError):
        configure_database(db, tmp_path / "bk")
    sql, rows, leftovers = _users(db)
    assert "'admin'" not in sql and leftovers == 0  # rolled back completely
    assert rows == [(7, "sales", "hash-s", "sales"), (9, "printing", "hash-p", "printing")]

    monkeypatch.undo()
    configure_database(db, tmp_path / "bk")  # next start upgrades normally
    sql, rows, _ = _users(db)
    assert "'admin'" in sql and [r[0] for r in rows] == [7, 9]


def test_interrupted_upgrade_from_older_build_is_repaired(tmp_path):
    db = tmp_path / "half.db"
    _legacy_db(db)
    con = sqlite3.connect(db)  # state an older non-atomic build could leave behind
    con.executescript("ALTER TABLE users RENAME TO users_pre_admin; DROP INDEX IF EXISTS ix_users_username;"
                      "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64), password_hash VARCHAR(200),"
                      " role VARCHAR(16), is_active BOOLEAN, created_at DATETIME);")
    con.commit()
    con.close()
    configure_database(db, tmp_path / "bk")
    sql, rows, leftovers = _users(db)
    assert "'admin'" in sql and leftovers == 0
    assert rows == [(7, "sales", "hash-s", "sales"), (9, "printing", "hash-p", "printing")]


# ---------------------------------------------------------------- 2. last active Admin under concurrency
def test_two_admins_demoting_each_other_concurrently_keep_one_admin(client, admin, monkeypatch):
    import time

    from app.routers import admin as admin_routes

    real_count = admin_routes._active_admins

    def slow_count(db):  # widen the check-then-write window so the race reliably happens without the fix
        n = real_count(db)
        time.sleep(0.3)
        return n

    monkeypatch.setattr(admin_routes, "_active_admins", slow_count)
    make_user("admin2", "admin")
    other = login(client, "admin2", "Admin-Pass-2026")
    ids = {u["username"]: u["id"] for u in client.get("/api/admin/users", headers=admin).json()["items"]}

    def demote(headers, target):
        return client.patch(f"/api/admin/users/{ids[target]}", headers=headers, json={"is_active": False}).status_code

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(lambda a: demote(*a), [(admin, "admin2"), (other, "admin")]))
    assert codes in ([200, 401], [200, 409])  # one wins; the other is refused (or its token already ended)
    with SessionLocal() as db:
        assert db.query(User).filter_by(role="admin", is_active=True).count() == 1


# ---------------------------------------------------------------- 3. session version increments in SQL
def test_each_reset_increments_session_version(client, admin):
    sales_id = next(u["id"] for u in client.get("/api/admin/users", headers=admin).json()["items"] if u["username"] == "sales")
    for _ in range(3):
        assert client.post(f"/api/admin/users/{sales_id}/reset-password", headers=admin,
                           json={"new_password": "Another-Pass-1"}).status_code == 200
    with SessionLocal() as db:
        assert db.get(User, sales_id).session_version == 3


# ---------------------------------------------------------------- 4. audit log cannot be flooded anonymously
def test_unknown_username_failures_are_capped_in_the_audit_log(client):
    from app.routers import auth

    monkey_cap = auth._WindowCap(limit=3, window=600)
    original, auth._unknown_failures = auth._unknown_failures, monkey_cap
    try:
        for n in range(8):
            assert client.post("/api/login", json={"username": f"nobody{n}", "password": "x"}).status_code == 401
        with SessionLocal() as db:
            assert db.query(AdminEvent).filter_by(action="login_failed").count() == 3
        monkey_cap.started = -1e9  # next window
        client.post("/api/login", json={"username": "nobody-next", "password": "x"})
        with SessionLocal() as db:
            last = db.query(AdminEvent).filter_by(action="login_failed").order_by(AdminEvent.id.desc()).first()
            assert "5 earlier attempt(s)" in last.details
    finally:
        auth._unknown_failures = original


# ---------------------------------------------------------------- 5. settings with out-of-range .env values
def test_settings_page_works_with_out_of_range_env_values(client, admin):
    settings.max_upload_bytes = 100 * 1024 * 1024  # e.g. MAX_UPLOAD_MB=100 in .env
    settings.token_expire_minutes = 5
    r = client.get("/api/admin/settings", headers=admin)
    assert r.status_code == 200
    assert r.json()["editable"]["max_upload_mb"] == 50 and r.json()["editable"]["token_expire_minutes"] == 15
    assert client.put("/api/admin/settings", headers=admin, json={"token_expire_minutes": 60}).status_code == 200
    assert settings.max_upload_bytes == 100 * 1024 * 1024 and settings.token_expire_minutes == 60  # upload size untouched


# ---------------------------------------------------------------- 6. concurrent backups
def test_concurrent_backups_are_all_valid(client, admin):
    login(client, "sales")
    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(lambda _: client.post("/api/admin/backups", headers=admin, json={}), range(3)))
    assert all(r.status_code == 201 for r in results)
    names = {r.json()["name"] for r in results}
    assert len(names) == 3
    for name in names:
        with zipfile.ZipFile(settings.backup_dir / name) as zf:
            assert zf.testzip() is None and "order_portal.db" in zf.namelist()
    assert not list(settings.backup_dir.glob("*.partial"))


# ---------------------------------------------------------------- 7. bcrypt 72-byte limit
def test_overlong_passwords_are_rejected_cleanly(client, admin):
    long_pw = "Ab1-" + "x" * 80
    assert client.post("/api/admin/users", headers=admin, json={"username": "longpw", "role": "sales", "password": long_pw}).status_code == 422
    sales_id = next(u["id"] for u in client.get("/api/admin/users", headers=admin).json()["items"] if u["username"] == "sales")
    r = client.post(f"/api/admin/users/{sales_id}/reset-password", headers=admin, json={"new_password": long_pw})
    assert r.status_code == 422 and long_pw not in r.text
    assert client.post("/api/login", json={"username": "sales", "password": long_pw}).status_code == 401  # no 500
    from app.security_seed import bootstrap_admin

    with SessionLocal() as db:
        db.query(User).filter_by(role="admin").delete()
        db.commit()
        assert "rejected" in bootstrap_admin(db, "boss", long_pw)


# ---------------------------------------------------------------- 8. login throttle under a parallel burst
def test_parallel_login_burst_gets_at_most_five_guesses(client):
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(lambda _: client.post("/api/login", json={"username": "sales", "password": "wrong-1"}).status_code, range(12)))
    assert codes.count(401) <= 5 and codes.count(401) + codes.count(429) == 12
