"""Authentication and role permissions (enforced on the server, not just hidden in the UI)."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import User
from app.security import hash_password, validate_new_password, verify_password

from .conftest import PRINTING_PASSWORD, SALES_PASSWORD, login, make_live, payload, upload


def test_both_roles_sign_in_and_get_their_role(client):
    for username, role in (("sales", "sales"), ("printing", "printing")):
        me = client.get("/api/me", headers=login(client, username)).json()
        assert me["user"]["role"] == role


def test_passwords_are_hashed_not_plaintext(client):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "sales"))
        assert user.password_hash.startswith("$2b$") and SALES_PASSWORD not in user.password_hash
    assert verify_password("pw-123456", hash_password("pw-123456"))
    assert not verify_password("wrong", hash_password("pw-123456"))


def test_password_policy():
    with pytest.raises(ValueError):
        validate_new_password("short1")
    with pytest.raises(ValueError):
        validate_new_password("onlyletters")
    validate_new_password("Better-pass-1")


@pytest.mark.parametrize("username,password", [("sales", "wrong"), ("nobody", SALES_PASSWORD), ("SALES ", "bad")])
def test_bad_credentials_rejected(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 401 and r.json()["detail"] == "Incorrect username or password."


def test_username_is_case_insensitive(client):
    assert client.post("/api/login", json={"username": " Sales ", "password": SALES_PASSWORD}).status_code == 200


def test_repeated_failures_are_throttled(client):
    for _ in range(5):
        client.post("/api/login", json={"username": "sales", "password": "nope"})
    r = client.post("/api/login", json={"username": "sales", "password": SALES_PASSWORD})
    assert r.status_code == 429


def test_missing_invalid_and_revoked_tokens(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    headers = login(client)
    assert client.post("/api/logout", headers=headers).status_code == 200
    r = client.get("/api/me", headers=headers)
    assert r.status_code == 401 and "signed out" in r.json()["detail"]


def test_inactive_user_cannot_sign_in(client):
    with SessionLocal() as db:
        db.scalar(select(User).where(User.username == "printing")).is_active = False
        db.commit()
    assert client.post("/api/login", json={"username": "printing", "password": PRINTING_PASSWORD}).status_code == 401


def test_only_admin_sales_and_printing_roles_exist(client):
    with SessionLocal() as db:
        db.add(User(username="boss", password_hash=hash_password("x-123456"), role="admin"))
        db.commit()  # admin is a valid role now
        db.add(User(username="mgr", password_hash=hash_password("x-123456"), role="manager"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_admin_routes_are_forbidden_to_sales(client, sales):
    assert client.get("/api/admin/users", headers=sales).status_code == 403
    for path in ("/api/admin", "/api/users"):
        assert client.get(path, headers=sales).status_code == 404


def test_printing_cannot_use_sales_actions(client, sales, printing):
    draft = upload(client, sales)
    with open(__file__, "rb") as fh:
        assert client.post("/api/orders/upload", headers=printing, files={"file": ("x.pdf", fh)}).status_code == 403
    assert client.put(f"/api/orders/{draft['id']}", headers=printing, json=payload(draft)).status_code == 403
    assert client.post(f"/api/orders/{draft['id']}/publish", headers=printing,
                       json={"version": draft["version"], "reviewed": True}).status_code == 403


def test_printing_cannot_see_drafts(client, sales, printing):
    draft = upload(client, sales)
    assert client.get(f"/api/orders/{draft['id']}", headers=printing).status_code == 404
    assert client.get(f"/api/orders/{draft['id']}/source-pdf", headers=printing).status_code == 404
    assert client.post(f"/api/orders/{draft['id']}/comment", headers=printing, json={"text": "hi"}).status_code == 404
    assert client.get("/api/orders", headers=printing).json()["total"] == 0


def test_sales_cannot_change_printing_status(client, sales):
    live = make_live(client, sales)
    r = client.post(f"/api/orders/{live['id']}/printing-status", headers=sales, json={"status": "Processing"})
    assert r.status_code == 403
