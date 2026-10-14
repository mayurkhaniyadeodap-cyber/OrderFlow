"""Usernames may contain spaces ("Dhruv Bhojani"); they are stored lower-case with single spaces and stay unique."""
from __future__ import annotations

import pytest

from app import manage
from app.config import settings
from app.database import SessionLocal, configure_database
from app.models import User
from app.security_seed import bootstrap_accounts_from_env, normalize_username

from .conftest import login, upload

PASSWORD = "Dhruv-Pass-2026"


def create(client, admin, username: str, role: str = "sales"):
    return client.post("/api/admin/users", headers=admin, json={"username": username, "role": role, "password": PASSWORD})


def sign_in(client, username: str, password: str = PASSWORD):
    return client.post("/api/login", json={"username": username, "password": password})


def test_normalize_username():
    assert normalize_username("Dhruv Bhojani") == "dhruv bhojani"
    assert normalize_username("  Dhruv \t  Bhojani  ") == "dhruv bhojani"
    assert normalize_username("sales") == "sales"  # existing names are unchanged


def test_admin_creates_user_with_space_and_they_sign_in(client, admin):
    r = create(client, admin, "Dhruv Bhojani")
    assert r.status_code == 201, r.text
    assert r.json()["username"] == "dhruv bhojani" and r.json()["role"] == "sales"
    for typed in ("Dhruv Bhojani", "dhruv bhojani", "  DHRUV   BHOJANI "):
        res = sign_in(client, typed)
        assert res.status_code == 200, typed
        assert res.json()["user"]["username"] == "dhruv bhojani" and res.json()["user"]["role"] == "sales"
    assert sign_in(client, "dhruvbhojani").status_code == 401  # spaces are part of the name
    assert sign_in(client, "Dhruv Bhojani", "wrong-pass-1").status_code == 401


def test_usernames_with_spaces_stay_unique(client, admin):
    assert create(client, admin, "Dhruv Bhojani").status_code == 201
    for duplicate in ("dhruv bhojani", "DHRUV  BHOJANI", " Dhruv Bhojani "):
        r = create(client, admin, duplicate, role="printing")
        assert r.status_code == 409, duplicate
    with SessionLocal() as db:
        assert db.query(User).filter_by(username="dhruv bhojani").count() == 1


@pytest.mark.parametrize("username", ["ab", " a  ", "-dhruv", " dhruv@bhojani", "dhruv/bhojani", "x" * 33, "   "])
def test_other_invalid_usernames_still_rejected(client, admin, username):
    assert create(client, admin, username).status_code == 422


def test_user_with_space_owns_their_orders(client, admin):
    """Order ownership (created_by) works with a spaced username: they see their own order, other Sales do not."""
    assert create(client, admin, "Dhruv Bhojani").status_code == 201
    dhruv = {"Authorization": f"Bearer {sign_in(client, 'Dhruv Bhojani').json()['access_token']}"}
    order = upload(client, dhruv)
    assert order["created_by"] == "dhruv bhojani"
    listed = client.get("/api/orders", headers=dhruv).json()["items"]
    assert [o["id"] for o in listed] == [order["id"]]
    assert client.get(f"/api/orders/{order['id']}", headers=login(client, "sales")).status_code == 404
    r = client.get("/api/admin/activity", headers=admin, params={"actor": "dhruv bhojani"})
    assert r.status_code == 200 and r.json()["items"]


def test_account_setup_from_env_accepts_spaces(client):
    env = {"ADMIN_USERNAME": "Dhruv Bhojani", "ADMIN_PASSWORD": PASSWORD}
    with SessionLocal() as db:
        messages = bootstrap_accounts_from_env(db, env)
    assert any("created Admin account 'dhruv bhojani'" in m for m in messages)
    assert sign_in(client, "Dhruv Bhojani").json()["user"]["role"] == "admin"


def test_command_line_accepts_spaces(client, monkeypatch, capsys):
    monkeypatch.setattr(manage, "_ask_password", lambda: PASSWORD)
    assert manage.main(["create-user", "Dhruv Bhojani", "printing"]) == 0
    assert "Created printing user 'dhruv bhojani'" in capsys.readouterr().out
    configure_database(settings.database_path, settings.backup_dir)  # the CLI rebinds the engine; rebind for the app
    assert sign_in(client, "dhruv bhojani").json()["user"]["role"] == "printing"
