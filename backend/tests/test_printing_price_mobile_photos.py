"""Printing price per product row, executive mobile numbers, Sales confirmation of print previews per product."""
from __future__ import annotations

import sqlite3

from app.database import configure_database

from .conftest import MEET_PAPERS, login, make_live, payload, save, upload

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _item_save(client, headers, order, item, **changes):
    body = {k: item[k] for k in ("sku", "quantity", "rate", "value", "printing_price")} | changes
    r = client.put(f"/api/orders/{order['id']}/items/{item['id']}", headers=headers,
                   json={"version": order["version"], **body})
    assert r.status_code == 200, r.text
    return r.json()["order"]


# ---------------------------------------------------------------- printing price
def test_printing_price_saved_per_row(client, sales):
    order = upload(client, sales, MEET_PAPERS)
    assert all(i["printing_price"] is None for i in order["items"])
    order = _item_save(client, sales, order, order["items"][0], printing_price=12.345)
    assert order["items"][0]["printing_price"] == 12.35  # rounded like other amounts

    body = payload(order)
    body["items"][0]["printing_price"] = 4
    r = client.put(f"/api/orders/{order['id']}", headers=sales, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["printing_price"] == 4
    assert "printing price" in r.json()["activity"][-1]["details"]


def test_printing_price_kept_when_not_sent_and_rejects_negative(client, sales):
    order = upload(client, sales, MEET_PAPERS)
    order = _item_save(client, sales, order, order["items"][0], printing_price=7)
    item = order["items"][0]
    r = client.put(f"/api/orders/{order['id']}/items/{item['id']}", headers=sales,
                   json={"version": order["version"], "sku": item["sku"], "quantity": item["quantity"]})
    assert r.json()["order"]["items"][0]["printing_price"] == 7  # left out: stored value kept
    bad = client.put(f"/api/orders/{order['id']}/items/{item['id']}", headers=sales,
                     json={"version": r.json()["order"]["version"], "printing_price": -1})
    assert bad.status_code == 422


# ---------------------------------------------------------------- executive mobile
def test_admin_sets_contact_mobile_and_order_shows_it(client, sales, admin):
    r = client.post("/api/admin/contacts", headers=admin, json={"name": "Priya Shah", "mobile": " 98765 43210 "})
    assert r.status_code == 201 and r.json()["mobile"] == "98765 43210"
    order = save(client, sales, upload(client, sales, MEET_PAPERS), executive="priya  SHAH")
    assert order["executive_mobile"] == "98765 43210"  # matched ignoring case and spaces

    contact_id = r.json()["id"]
    r = client.patch(f"/api/admin/contacts/{contact_id}", headers=admin, json={"name": "Priya Shah", "mobile": ""})
    assert r.status_code == 200 and r.json()["mobile"] is None
    assert client.get(f"/api/orders/{order['id']}", headers=sales).json()["executive_mobile"] is None


def test_mobile_taken_from_name_and_validated(client, sales, admin):
    order = upload(client, sales, MEET_PAPERS)  # executive "Harsha Prajapati-JD (7283912175)"
    assert order["executive_mobile"] == "7283912175"
    rows = client.get("/api/admin/contacts", headers=admin).json()["items"]
    contact = next(c for c in rows if c["name"].startswith("Harsha"))
    r = client.patch(f"/api/admin/contacts/{contact['id']}", headers=admin, json={"name": contact["name"]})
    assert r.json()["mobile"] == "7283912175"  # mobile not sent: unchanged
    for bad in ("12345", "call me", "9" * 16):
        r = client.patch(f"/api/admin/contacts/{contact['id']}", headers=admin, json={"name": contact["name"], "mobile": bad})
        assert r.status_code == 422, bad


def test_printing_sees_executive_mobile(client, sales, printing):
    live = make_live(client, sales, MEET_PAPERS)
    assert client.get(f"/api/orders/{live['id']}", headers=printing).json()["executive_mobile"] == "7283912175"


# ---------------------------------------------------------------- photo confirmation
def _in_printing(client, sales, printing):
    """A Live order that Printing has started (Processing): previews are uploaded and reviewed now."""
    live = make_live(client, sales, MEET_PAPERS)
    r = client.post(f"/api/orders/{live['id']}/printing-status", headers=printing, json={"status": "Processing"})
    assert r.status_code == 200, r.text
    return r.json()


def _mark_print_done(client, printing, order):
    return client.post(f"/api/orders/{order['id']}/printing-status", headers=printing, json={"status": "Print Done"})


def _upload_photo(client, printing, order, item_id):
    return client.post(f"/api/orders/{order['id']}/photos", headers=printing, data={"item_id": str(item_id)},
                       files={"file": ("done.png", PNG, "image/png")})


def _review(client, headers, order, item_id, action, note=None):
    return client.post(f"/api/orders/{order['id']}/items/{item_id}/photo-review", headers=headers,
                       json={"version": order["version"], "action": action, "note": note})


def _get(client, headers, order):
    return client.get(f"/api/orders/{order['id']}", headers=headers).json()


def _item(order, item_id):
    return next(i for i in order["items"] if i["id"] == item_id)


def test_photo_is_uploaded_and_confirmed_per_product(client, sales, printing):
    order = _in_printing(client, sales, printing)
    first, second = (i["id"] for i in order["items"])
    assert order["photo_status"] is None and _item(order, first)["photo_status"] is None
    assert _review(client, sales, _get(client, sales, order), first, "confirm").status_code == 409  # no photo yet
    assert client.post(f"/api/orders/{order['id']}/photos", headers=printing,
                       files={"file": ("done.png", PNG, "image/png")}).status_code == 422  # product is required

    r = _upload_photo(client, printing, order, first)
    assert r.status_code == 201, r.text
    order = r.json()
    assert _item(order, first)["photo_status"] == "Pending" and len(_item(order, first)["photos"]) == 1
    assert _item(order, second)["photo_status"] is None and _item(order, second)["photos"] == []
    assert order["photo_status"] == "Pending"

    order = _get(client, sales, order)
    assert order["permissions"]["can_review_photos"] is True
    assert _review(client, printing, order, first, "confirm").status_code == 403  # Printing cannot confirm
    assert _review(client, sales, order, second, "confirm").status_code == 409  # second product has no photo

    r = _review(client, sales, order, first, "confirm")
    assert r.status_code == 200, r.text
    order = r.json()
    one = _item(order, first)
    assert one["photo_status"] == "Confirmed" and one["photo_reviewed_by"] == "sales" and one["photo_reviewed_at"]
    assert order["photo_status"] is None  # second product still needs a photo
    assert order["activity"][-1]["event"] == "photos_confirmed" and "row 1" in order["activity"][-1]["details"]
    # Confirmed is final for that product only
    assert _upload_photo(client, printing, order, first).status_code == 409
    assert _review(client, sales, order, first, "reject", "late").status_code == 409

    order = _upload_photo(client, printing, order, second).json()
    order = _review(client, sales, _get(client, sales, order), second, "confirm").json()
    assert order["photo_status"] == "Confirmed"  # every product confirmed


def test_print_done_blocked_until_every_preview_is_confirmed(client, sales, printing):
    order = _in_printing(client, sales, printing)
    first, second = (i["id"] for i in order["items"])
    r = _mark_print_done(client, printing, order)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "previews_not_confirmed"
    assert any("no preview uploaded" in e for e in r.json()["detail"]["errors"])

    _upload_photo(client, printing, order, first)
    order = _review(client, sales, _get(client, sales, order), first, "confirm").json()
    assert _mark_print_done(client, printing, order).status_code == 409  # second product still missing

    _upload_photo(client, printing, order, second)
    order = _review(client, sales, _get(client, sales, order), second, "reject", "Wrong colour").json()
    assert _mark_print_done(client, printing, order).status_code == 409  # rejected is not confirmed

    _upload_photo(client, printing, order, second)
    order = _review(client, sales, _get(client, sales, order), second, "confirm").json()
    r = _mark_print_done(client, printing, order)
    assert r.status_code == 200 and r.json()["printing_status"] == "Print Done"
    assert r.json()["permissions"]["can_upload_photos"] is False
    assert _upload_photo(client, printing, order, second).status_code == 409  # no previews after Print Done


def test_preview_upload_allowed_while_new(client, sales, printing):
    live = make_live(client, sales, MEET_PAPERS)
    assert _get(client, printing, live)["permissions"]["can_upload_photos"] is True
    r = _upload_photo(client, printing, live, live["items"][0]["id"])
    assert r.status_code == 201 and r.json()["printing_status"] == "New"


def test_reject_needs_reason_then_printing_uploads_again(client, sales, printing):
    order = _in_printing(client, sales, printing)
    first = order["items"][0]["id"]
    _upload_photo(client, printing, order, first)
    order = _get(client, sales, order)
    assert _review(client, sales, order, first, "reject", "  ").status_code == 422
    r = _review(client, sales, order, first, "reject", "Logo is blurred, please retake")
    assert r.status_code == 200, r.text
    item = _item(r.json(), first)
    assert item["photo_status"] == "Rejected" and item["photo_review_note"] == "Logo is blurred, please retake"
    assert r.json()["photo_status"] == "Rejected"

    again = _upload_photo(client, printing, r.json(), first).json()
    assert _item(again, first)["photo_status"] == "Pending" and len(_item(again, first)["photos"]) == 2


def test_stale_version_and_other_sales_user_cannot_review(client, sales, printing, admin):
    order = _in_printing(client, sales, printing)
    first = order["items"][0]["id"]
    _upload_photo(client, printing, order, first)
    assert _review(client, sales, order, first, "confirm").status_code == 409  # version from before the upload

    client.post("/api/admin/users", headers=admin,
                json={"username": "sales2", "role": "sales", "password": "Other-Sales-1"})
    other = login(client, "sales2", "Other-Sales-1")
    fresh = _get(client, admin, order)
    assert _review(client, other, fresh, first, "confirm").status_code == 404  # not their order
    assert _review(client, admin, fresh, first, "confirm").status_code == 200  # Admin can confirm any order


def test_admin_sees_photo_status_of_every_product(client, sales, printing, admin):
    order = _in_printing(client, sales, printing)
    first, second = (i["id"] for i in order["items"])
    order = _upload_photo(client, printing, order, first).json()
    _review(client, sales, _get(client, sales, order), first, "reject", "Wrong colour")

    data = client.get("/api/admin/photo-reviews", headers=admin).json()
    assert data["counts"] == {"Pending": 0, "Confirmed": 0, "Rejected": 1, "Missing": 1}
    rows = {r["item_id"]: r for r in data["items"]}
    assert rows[first]["photo_status"] == "Rejected" and rows[first]["photo_review_note"] == "Wrong colour"
    assert rows[first]["photo_reviewed_by"] == "sales" and rows[first]["photo_count"] == 1
    assert rows[second]["photo_status"] is None and rows[second]["photo_count"] == 0
    assert rows[first]["internal_order_no"] == order["internal_order_no"]

    only = client.get("/api/admin/photo-reviews", headers=admin, params={"status": "Missing"}).json()
    assert [r["item_id"] for r in only["items"]] == [second]
    assert client.get("/api/admin/photo-reviews", headers=sales).status_code == 403


def test_removing_a_product_row_keeps_its_photos(client, sales, printing, admin):
    order = _in_printing(client, sales, printing)
    first = order["items"][0]["id"]
    order = _upload_photo(client, printing, order, first).json()
    order = _get(client, admin, order)
    body = payload(order)
    body["items"] = body["items"][1:]
    r = client.put(f"/api/orders/{order['id']}", headers=admin, json=body)  # Admin edits the Live order
    assert r.status_code == 200, r.text
    assert len(r.json()["photos"]) == 1 and r.json()["photos"][0]["item_id"] is None
    assert r.json()["photo_status"] is None


# ---------------------------------------------------------------- database upgrade
def test_existing_database_gets_new_columns_with_backup(tmp_path):
    db_path, backups = tmp_path / "old.db", tmp_path / "backups"
    configure_database(db_path)
    con = sqlite3.connect(db_path)
    for col in ("printing_price", "photo_status", "photo_reviewed_by", "photo_reviewed_at", "photo_review_note"):
        con.execute(f"ALTER TABLE order_items DROP COLUMN {col}")
    con.execute("ALTER TABLE sales_contacts DROP COLUMN mobile")
    con.execute("ALTER TABLE orders DROP COLUMN photo_status")
    # order_photos as created before photos were linked to products (a foreign-key column cannot be dropped)
    con.execute("DROP TABLE order_photos")
    con.execute("CREATE TABLE order_photos (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), "
                "file_path VARCHAR(500), original_filename VARCHAR(255), content_type VARCHAR(100), "
                "uploaded_by VARCHAR(64), uploaded_at DATETIME)")
    con.execute("INSERT INTO sales_contacts (name, name_key, source, created_at) VALUES ('A (9876543210)', 'a', 'admin', '2026-01-01')")
    con.commit()
    con.close()

    configure_database(db_path, backups)
    con = sqlite3.connect(db_path)
    try:
        assert {"printing_price", "photo_status", "photo_review_note"} <= {r[1] for r in con.execute("PRAGMA table_info(order_items)")}
        assert "mobile" in {r[1] for r in con.execute("PRAGMA table_info(sales_contacts)")}
        assert "photo_status" in {r[1] for r in con.execute("PRAGMA table_info(orders)")}
        assert "item_id" in {r[1] for r in con.execute("PRAGMA table_info(order_photos)")}
        assert con.execute("SELECT name, mobile FROM sales_contacts").fetchall() == [("A (9876543210)", None)]
    finally:
        con.close()
    assert [p.name.startswith("pre_column_update_") for p in backups.iterdir()] == [True]
    configure_database(db_path, backups)  # second start: nothing to add, no extra backup
    assert len(list(backups.iterdir())) == 1
