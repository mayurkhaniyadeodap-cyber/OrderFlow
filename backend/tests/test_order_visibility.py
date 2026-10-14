"""Order visibility: a Sales user sees only their own orders; Printing sees every user's Live orders; Admin sees all.

Enforced by the API (lists, search, counts, details and every order sub-route), not just hidden in the UI.
"""
from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import Order, OrderEvent

from .conftest import ADMIN_PASSWORD, ANNESHA, MEET_PAPERS, REAL_PO, login, make_live, make_user, upload


@pytest.fixture()
def world(client, admin):
    """Sales A (`sales`) and Sales B (`salesb`), each with a Draft and a Live order from different POs."""
    make_user("salesb", "sales")
    a, b = login(client, "sales"), login(client, "salesb", ADMIN_PASSWORD)
    return {
        "a": a, "b": b, "printing": login(client, "printing"), "admin": admin,
        "a_draft": upload(client, a, REAL_PO), "a_live": make_live(client, a, ANNESHA),
        "b_draft": upload(client, b, MEET_PAPERS), "b_live": make_live(client, b, MEET_PAPERS),
    }


def ids(client, headers, **params) -> set[int]:
    r = client.get("/api/orders", headers=headers, params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return {o["id"] for o in r.json()["items"]}


def dashboard(client, headers) -> dict:
    r = client.get("/api/dashboard", headers=headers)
    assert r.status_code == 200
    return r.json()


def test_sales_a_sees_only_own_orders(client, world):
    a_orders = {world["a_draft"]["id"], world["a_live"]["id"]}
    assert ids(client, world["a"]) == a_orders
    assert ids(client, world["a"], include_archived=True) == a_orders
    for order in ("a_draft", "a_live"):
        assert client.get(f"/api/orders/{world[order]['id']}", headers=world["a"]).status_code == 200
    d = dashboard(client, world["a"])
    assert d["counts"]["total"] == 2 and d["counts"]["draft"] == 1 and d["counts"]["live"] == 1
    assert {o["id"] for o in d["recent"]} == a_orders


def test_sales_b_sees_only_own_orders(client, world):
    b_orders = {world["b_draft"]["id"], world["b_live"]["id"]}
    assert ids(client, world["b"]) == b_orders
    d = dashboard(client, world["b"])
    assert d["counts"]["total"] == 2 and {o["id"] for o in d["recent"]} == b_orders
    for order in ("a_draft", "a_live"):
        assert client.get(f"/api/orders/{world[order]['id']}", headers=world["b"]).status_code == 404


def foreign_requests(order: dict) -> list[tuple[str, str, dict]]:
    """Every order route, aimed at an order the caller must not see."""
    oid, body = order["id"], {"version": order["version"]}
    item = order["items"][0]["id"] if order["items"] else 1
    return [
        ("get", f"/api/orders/{oid}", {}),
        ("put", f"/api/orders/{oid}", {"json": {**body, "customer_name": "changed"}}),
        ("post", f"/api/orders/{oid}/items", {"json": {**body, "sku": "X", "quantity": 1}}),
        ("put", f"/api/orders/{oid}/items/{item}", {"json": {**body, "sku": "X"}}),
        ("put", f"/api/orders/{oid}/global", {"json": {**body, "global_customization": "x"}}),
        ("get", f"/api/orders/{oid}/publish-check", {}),
        ("post", f"/api/orders/{oid}/publish", {"json": {**body, "reviewed": True}}),
        ("post", f"/api/orders/{oid}/re-extract", {"json": body}),
        ("post", f"/api/orders/{oid}/archive", {"json": body}),
        ("post", f"/api/orders/{oid}/comment", {"json": {"text": "hello"}}),
        ("get", f"/api/orders/{oid}/source-pdf", {}),
        ("get", f"/api/orders/{oid}/print", {}),
        ("get", f"/api/orders/{oid}/attachments/1", {}),
        ("delete", f"/api/orders/{oid}/attachments/1", {}),
        ("post", f"/api/orders/{oid}/attachments", {"files": {"file": ("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")}}),
    ]


@pytest.mark.parametrize("target", ["b_draft", "b_live"])
def test_sales_a_cannot_reach_sales_b_order_by_id(client, world, target):
    order = world[target]
    with SessionLocal() as db:
        before = db.get(Order, order["id"]).version
    for method, url, kwargs in foreign_requests(order):
        r = getattr(client, method)(url, headers=world["a"], **kwargs)
        assert r.status_code == 404, (method, url, r.status_code, r.text)  # same answer as a missing order
        assert order.get("customer_name") is None or order["customer_name"] not in r.text
    with SessionLocal() as db:  # nothing changed, nothing recorded for A
        o = db.get(Order, order["id"])
        assert o.version == before and not o.is_archived
        assert not db.query(OrderEvent).filter_by(order_id=order["id"], actor="sales").count()


def test_search_and_filters_respect_ownership(client, world):
    b = world["b_live"]
    terms = [t for t in (b["po_number"], b["customer_name"], b["internal_order_no"],
                         (b["items"] or [{}])[0].get("sku")) if t]
    assert terms
    for term in terms:
        assert b["id"] in ids(client, world["b"], q=term)
        assert b["id"] not in ids(client, world["a"], q=term), term
        assert b["id"] in ids(client, world["printing"], q=term)
        assert b["id"] in ids(client, world["admin"], q=term)
    assert ids(client, world["a"], status="Live") == {world["a_live"]["id"]}
    assert ids(client, world["a"], printing_status="New") == {world["a_live"]["id"]}


def test_archived_orders_of_other_sales_users_stay_hidden(client, world):
    b_draft = world["b_draft"]
    r = client.post(f"/api/orders/{b_draft['id']}/archive", headers=world["b"], json={"version": b_draft["version"]})
    assert r.status_code == 200
    assert b_draft["id"] in ids(client, world["b"], include_archived=True)
    assert b_draft["id"] not in ids(client, world["a"], include_archived=True)
    assert client.get(f"/api/orders/{b_draft['id']}", headers=world["a"]).status_code == 404
    assert b_draft["id"] in ids(client, world["admin"], include_archived=True)


def test_printing_sees_live_orders_of_every_sales_user(client, world):
    lives = {world["a_live"]["id"], world["b_live"]["id"]}
    assert ids(client, world["printing"]) == lives  # Drafts are still not printing work
    d = dashboard(client, world["printing"])
    assert d["counts"]["total"] == 2 and {o["id"] for o in d["recent"]} == lives
    for key in ("a_live", "b_live"):
        oid = world[key]["id"]
        assert client.get(f"/api/orders/{oid}", headers=world["printing"]).status_code == 200
        assert client.get(f"/api/orders/{oid}/print", headers=world["printing"]).status_code == 200
        r = client.post(f"/api/orders/{oid}/printing-status", headers=world["printing"], json={"status": "Processing"})
        assert r.status_code == 200 and r.json()["printing_status"] == "Processing"
    assert client.get(f"/api/orders/{world['b_draft']['id']}", headers=world["printing"]).status_code == 404


def test_admin_sees_all_orders(client, world):
    every = {world[k]["id"] for k in ("a_draft", "a_live", "b_draft", "b_live")}
    assert ids(client, world["admin"]) == every
    counts = client.get("/api/admin/dashboard", headers=world["admin"]).json()["orders"]  # Admin's own dashboard
    assert counts["total"] == 4 and counts["draft"] == 2 and counts["live"] == 2
    r = client.get("/api/admin/orders", headers=world["admin"], params={"limit": 200})
    assert {o["id"] for o in r.json()["items"]} == every
    for oid in every:
        assert client.get(f"/api/orders/{oid}", headers=world["admin"]).status_code == 200


def test_sales_still_manage_their_own_orders(client, world):
    a_draft = world["a_draft"]
    r = client.put(f"/api/orders/{a_draft['id']}", headers=world["a"],
                   json={"version": a_draft["version"], "customer_name": "Own Customer"})
    assert r.status_code == 200 and r.json()["customer_name"] == "Own Customer"
    r = client.post(f"/api/orders/{a_draft['id']}/comment", headers=world["a"], json={"text": "mine"})
    assert r.status_code == 201


def test_duplicate_warning_does_not_reveal_another_users_order(client, world):
    """B uploads the PDF A already uploaded: the warning still appears but names none of A's orders."""
    a_draft = world["a_draft"]
    dup = upload(client, world["b"], REAL_PO)
    [warning] = [w for w in dup["extraction_warnings"] if w["message"].startswith("Possible duplicate")]
    assert "another user" in warning["message"]
    assert f"Draft #{a_draft['id']}" not in warning["message"]
    # the uploader's own earlier copy is still named
    again = upload(client, world["b"], REAL_PO)
    [warning] = [w for w in again["extraction_warnings"] if w["message"].startswith("Possible duplicate")]
    assert f"Draft #{dup['id']}" in warning["message"] and "another user" in warning["message"]
