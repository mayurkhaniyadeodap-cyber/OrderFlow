"""Couriers and courier exports were removed from OrderFlow. Old stored courier values stay untouched in the
database (no migration) but are no longer read, returned or shown."""
from __future__ import annotations

import sqlite3

import pytest

from app.config import settings

from .conftest import login, make_live, payload, upload


@pytest.mark.parametrize("path", ["/api/exports/couriers", "/api/exports/zip", "/api/exports/DTDC"])
def test_export_endpoints_are_gone(client, path):
    for who in ("sales", "printing"):
        r = client.get(path, headers=login(client, who))
        assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_api_route"


def test_no_courier_in_api_responses(client, sales):
    live = make_live(client, sales)
    assert "courier" not in live and "courier" not in client.get("/api/orders", headers=sales).json()["items"][0]
    config = client.get("/api/me", headers=sales).json()["config"]
    assert "courier_options" not in config and "can_export" not in config
    page = client.get(f"/api/orders/{live['id']}/print", headers=sales).text
    assert "courier" not in page.lower()
    assert all(w["field"] != "courier" for w in live["extraction_warnings"])


def test_courier_sent_by_an_old_client_is_ignored(client, sales):
    order = upload(client, sales)
    r = client.put(f"/api/orders/{order['id']}", headers=sales, json=payload(order) | {"courier": "DTDC"})
    assert r.status_code == 200 and "courier" not in r.json()
    r = client.get("/api/orders", headers=sales, params={"courier": "DTDC"})  # old filter parameter: ignored
    assert r.status_code == 200 and r.json()["total"] == 1


def test_existing_courier_values_are_left_in_the_database(client, sales):
    live = make_live(client, sales)
    con = sqlite3.connect(settings.database_path)
    # Databases created by older versions have an orders.courier column (new databases do not); simulate one.
    if "courier" not in {r[1] for r in con.execute("PRAGMA table_info(orders)")}:
        con.execute("ALTER TABLE orders ADD COLUMN courier VARCHAR(100)")
    con.execute("UPDATE orders SET courier='DTDC' WHERE id=?", (live["id"],))  # value saved by an older version
    con.commit()
    con.close()
    client.post(f"/api/orders/{live['id']}/comment", headers=sales, json={"text": "still fine"})
    con = sqlite3.connect(settings.database_path)
    assert con.execute("SELECT courier FROM orders WHERE id=?", (live["id"],)).fetchone()[0] == "DTDC"  # not erased
    con.close()
    detail = client.get(f"/api/orders/{live['id']}", headers=sales).json()
    assert "courier" not in detail and detail["customer_name"] == "Kalpit Pandya - Frn"
