"""End-to-end order workflow: upload → Draft → Live → New → Processing → Print Done."""
from __future__ import annotations

import io

from app.config import settings
from app.database import SessionLocal, configure_database
from app.models import Order

from .conftest import ANNESHA, LOGO_JPEG, MEET_PAPERS, REAL_PO, login, make_live, payload, publish, save, upload


# ---------------------------------------------------------------- upload
def test_upload_creates_draft_with_extracted_data(client, sales):
    order = upload(client, sales)
    assert order["status"] == "Draft" and order["internal_order_no"] is None and order["live_at"] is None
    assert order["po_number"] == "135-73530274" and order["customer_name"] == "Kalpit Pandya - Frn"
    assert len(order["items"]) == 3 and order["has_source_pdf"]
    assert order["source_filename"] == "order_73530274.pdf"
    assert {a["event"] for a in order["activity"]} == {"pdf_uploaded", "extracted"}
    assert not any(w["field"] == "courier" for w in order["extraction_warnings"])


def test_upload_rejects_non_pdf(client, sales):
    r = client.post("/api/orders/upload", headers=sales, files={"file": ("logo.jpeg", LOGO_JPEG.read_bytes(), "image/jpeg")})
    assert r.status_code == 415 and "Only PDF" in r.json()["detail"]["message"]
    r = client.post("/api/orders/upload", headers=sales, files={"file": ("fake.pdf", b"hello world", "application/pdf")})
    assert r.status_code == 415
    r = client.post("/api/orders/upload", headers=sales, files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code == 400


def test_upload_size_limit(client, sales, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 1024)
    r = client.post("/api/orders/upload", headers=sales, files={"file": ("po.pdf", REAL_PO.read_bytes(), "application/pdf")})
    assert r.status_code == 413


def test_image_only_pdf_still_creates_a_draft_for_manual_entry(client, sales):
    from .conftest import IMAGE_ONLY_PDF

    order = upload(client, sales, IMAGE_ONLY_PDF)
    assert order["status"] == "Draft" and order["items"] == []
    assert order["extraction_warnings"][0]["level"] == "error"


def test_duplicate_upload_is_flagged(client, sales):
    upload(client, sales)
    second = upload(client, sales)
    assert any("Possible duplicate" in w["message"] for w in second["extraction_warnings"])


# ---------------------------------------------------------------- draft editing
def test_sales_edits_and_saves_draft_including_rows(client, sales):
    order = upload(client, sales)
    items = payload(order)["items"]
    items[0]["quantity"] = 61
    items[0]["customization_text"] = "Happy Diwali"
    removed = items.pop(2)
    items.append({"sku": "NEW-SKU-1", "product_name": "Custom mug", "quantity": 2, "rate": 10, "value": 20,
                  "customization_names": ["Asha", "Ravi"]})
    saved = save(client, sales, order, contact="9000000001", customer_name="Kalpit Pandya", items=items)
    assert saved["version"] == order["version"] + 1
    assert saved["contact"] == "9000000001" and saved["customer_name"] == "Kalpit Pandya"
    assert [i["sku"] for i in saved["items"]] == [order["items"][0]["sku"], order["items"][1]["sku"], "NEW-SKU-1"]
    assert saved["items"][0]["quantity"] == 61 and saved["items"][2]["customization_names"] == ["Asha", "Ravi"]
    assert removed["sku"] not in {i["sku"] for i in saved["items"]}
    details = next(a["details"] for a in saved["activity"] if a["event"] == "draft_saved")
    assert "contact: 8619140473 → 9000000001" in details and "row removed" in details and "added" in details


def test_stale_version_is_rejected(client, sales):
    order = upload(client, sales)
    save(client, sales, order, contact="9000000001")
    r = client.put(f"/api/orders/{order['id']}", headers=sales, json=payload(order, contact="9000000002"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_conflict"


def test_numeric_and_field_validation(client, sales):
    order = upload(client, sales)
    body = payload(order)
    body["items"][0]["quantity"] = -1
    r = client.put(f"/api/orders/{order['id']}", headers=sales, json=body)
    assert r.status_code == 422 and any("row 1" in e for e in r.json()["detail"]["errors"])
    body = payload(order)
    body["items"][0]["rate"] = "abc"
    assert client.put(f"/api/orders/{order['id']}", headers=sales, json=body).status_code == 422
    assert client.put(f"/api/orders/{order['id']}", headers=sales, json=payload(order, email="not-an-email")).status_code == 422
    assert client.put(f"/api/orders/{order['id']}", headers=sales,
                      json=payload(order, source_order_date="08/10/2026")).status_code == 422


def test_foreign_item_id_rejected(client, sales):
    a, b = upload(client, sales), upload(client, sales, ANNESHA)
    body = payload(a)
    body["items"][0]["id"] = b["items"][0]["id"]
    assert client.put(f"/api/orders/{a['id']}", headers=sales, json=body).status_code == 400


# ---------------------------------------------------------------- publish rules
def test_publish_without_customization_is_rejected(client, sales):
    order = save(client, sales, upload(client, sales), global_notes="Rush order")
    r = publish(client, sales, order)
    assert r.status_code == 422
    assert any("Customization is required" in e for e in r.json()["detail"]["errors"])
    items = payload(order)["items"]
    items[0]["notes"] = "Notes alone do not count"
    order = save(client, sales, order, items=items)
    assert publish(client, sales, order).status_code == 422


def test_publish_requires_review_but_not_shipping(client, sales):
    order = save(client, sales, upload(client, sales), global_customization="Logo A",
                 shipping_address=None, subtotal=None, total=None)
    check = client.get(f"/api/orders/{order['id']}/publish-check", headers=sales).json()
    assert check["errors"] == []
    r = publish(client, sales, order, reviewed=False)
    assert r.status_code == 422 and "reviewed" in r.json()["detail"]["message"]
    r = publish(client, sales, order)
    assert r.status_code == 200 and r.json()["status"] == "Live" and "courier" not in r.json()


def test_individual_names_must_match_quantity(client, sales):
    order = save(client, sales, upload(client, sales, ANNESHA))
    items = payload(order)["items"]
    items[0]["customization_names"] = ["Asha", "Ravi"]  # quantity is 7
    order = save(client, sales, order, items=items)
    r = publish(client, sales, order)
    assert r.status_code == 422 and any("2 individual name(s) entered for quantity 7" in e for e in r.json()["detail"]["errors"])
    items[0]["customization_names"] = [f"Name {n}" for n in range(1, 8)]
    order = save(client, sales, order, items=items)
    assert publish(client, sales, order).status_code == 200


def test_publish_with_sku_wise_customization(client, sales):
    order = upload(client, sales)
    items = payload(order)["items"]
    items[2]["customization_text"] = "KHODIYAR ENGINEERING"
    order = save(client, sales, order, items=items)
    live = publish(client, sales, order).json()
    assert live["status"] == "Live" and live["printing_status"] == "New"


def test_publish_with_logo_attachment_only(client, sales):
    order = upload(client, sales)
    item_id = order["items"][0]["id"]
    r = client.post(f"/api/orders/{order['id']}/attachments", headers=sales, data={"item_id": str(item_id)},
                    files={"file": ("khodiyar.jpeg", LOGO_JPEG.read_bytes(), "image/jpeg")})
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["items"][0]["attachments"][0]["filename"] == "khodiyar.jpeg"
    assert client.get(order["items"][0]["attachments"][0]["url"], headers=sales).content == LOGO_JPEG.read_bytes()
    assert publish(client, sales, order).status_code == 200


def test_logo_must_be_image_or_pdf(client, sales):
    order = upload(client, sales)
    r = client.post(f"/api/orders/{order['id']}/attachments", headers=sales,
                    files={"file": ("evil.svg", b"<svg onload=alert(1)>", "image/svg+xml")})
    assert r.status_code == 415


def test_publish_generates_unique_number_and_live_timestamp(client, sales):
    first = make_live(client, sales)
    second = make_live(client, sales, MEET_PAPERS)
    year = first["live_at"][:4]
    assert first["internal_order_no"] == f"OF-{year}-00001"
    assert second["internal_order_no"] == f"OF-{year}-00002"
    assert first["live_at"] and first["published_by"] == "sales"
    assert first["live_at"] != first["source_order_date"]  # Live date is the publish time, not the PO date
    published = [a for a in first["activity"] if a["event"] == "published"]
    assert published and first["internal_order_no"] in published[0]["details"]


def test_second_publish_does_not_generate_another_number(client, sales):
    live = make_live(client, sales)
    r = client.post(f"/api/orders/{live['id']}/publish", headers=sales, json={"version": live["version"], "reviewed": True})
    assert r.status_code == 409 and r.json()["detail"]["internal_order_no"] == live["internal_order_no"]
    again = client.get(f"/api/orders/{live['id']}", headers=sales).json()
    assert again["internal_order_no"] == live["internal_order_no"] and again["version"] == live["version"]


# ---------------------------------------------------------------- locks
def test_live_order_details_cannot_be_edited_via_api(client, sales):
    live = make_live(client, sales)
    r = client.put(f"/api/orders/{live['id']}", headers=sales, json=payload(live, customer_name="Changed"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "order_locked"
    r = client.post(f"/api/orders/{live['id']}/attachments", headers=sales,
                    files={"file": ("logo.jpeg", LOGO_JPEG.read_bytes(), "image/jpeg")})
    assert r.status_code == 409
    assert client.post(f"/api/orders/{live['id']}/re-extract", headers=sales, json={"version": live["version"]}).status_code == 409
    # Deleting (archiving) a Live order that Printing has not started is allowed for Sales: see test_permissions.py
    assert client.get(f"/api/orders/{live['id']}", headers=sales).json()["customer_name"] == "Kalpit Pandya - Frn"


def test_comments_allowed_after_live_without_changing_details(client, sales, printing):
    live = make_live(client, sales)
    r = client.post(f"/api/orders/{live['id']}/comment", headers=sales, json={"text": "Customer called: urgent"})
    assert r.status_code == 201
    r = client.post(f"/api/orders/{live['id']}/comment", headers=printing, json={"text": "Starting tomorrow"})
    after = r.json()
    assert [c["text"] for c in after["comments"]] == ["Customer called: urgent", "Starting tomorrow"]
    assert after["version"] == live["version"] and after["status"] == "Live"
    assert client.post(f"/api/orders/{live['id']}/comment", headers=sales, json={"text": "   "}).status_code == 422


# ---------------------------------------------------------------- printing
def test_printing_queue_shows_live_orders_oldest_first(client, sales, printing):
    upload(client, sales)  # a Draft: must not appear
    a = make_live(client, sales)
    b = make_live(client, sales, MEET_PAPERS)
    queue = client.get("/api/orders", headers=printing).json()
    assert [o["internal_order_no"] for o in queue["items"]] == [a["internal_order_no"], b["internal_order_no"]]
    assert all(o["printing_status"] == "New" for o in queue["items"])
    found = client.get("/api/orders", headers=printing, params={"q": "39390483"}).json()["items"]
    assert [o["id"] for o in found] == [b["id"]]


def test_printing_status_flow_and_lock(client, sales, printing):
    live = make_live(client, sales)
    url = f"/api/orders/{live['id']}/printing-status"
    skip = client.post(url, headers=printing, json={"status": "Print Done"})
    assert skip.status_code == 409 and skip.json()["detail"]["code"] == "invalid_transition"
    r = client.post(url, headers=printing, json={"status": "Processing"})
    assert r.status_code == 200 and r.json()["printing_status"] == "Processing"
    assert r.json()["permissions"]["next_printing_statuses"] == ["Print Done"]
    back = client.post(url, headers=printing, json={"status": "New"})
    assert back.status_code == 409
    done = client.post(url, headers=printing, json={"status": "Print Done"}).json()
    assert done["printing_status"] == "Print Done" and done["print_done_at"]
    assert done["permissions"]["next_printing_statuses"] == []
    for target in ("New", "Processing", "Print Done", "Bogus"):
        r = client.post(url, headers=printing, json={"status": target})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "print_done_locked"
    events = [a["details"] for a in done["activity"] if a["event"] == "printing_status_changed"]
    assert events == ["New → Processing", "Processing → Print Done"]


def test_photo_upload_after_print_done(client, sales, printing):
    live = make_live(client, sales)
    url = f"/api/orders/{live['id']}/photos"
    files = {"file": ("done.jpeg", LOGO_JPEG.read_bytes(), "image/jpeg")}
    assert client.post(url, headers=printing, files=files).status_code == 409
    for s in ("Processing", "Print Done"):
        client.post(f"/api/orders/{live['id']}/printing-status", headers=printing, json={"status": s})
    assert client.post(url, headers=sales, files=files).status_code == 403
    r = client.post(url, headers=printing, files=files)
    assert r.status_code == 201 and r.json()["photos"][0]["filename"] == "done.jpeg"
    assert client.post(url, headers=printing, files={"file": ("x.pdf", REAL_PO.read_bytes(), "application/pdf")}).status_code == 415


def test_source_pdf_and_print_view(client, sales, printing):
    live = make_live(client, sales)
    pdf = client.get(f"/api/orders/{live['id']}/source-pdf", headers=printing)
    assert pdf.status_code == 200 and pdf.content == REAL_PO.read_bytes()
    page = client.get(f"/api/orders/{live['id']}/print", headers=printing)
    assert page.status_code == 200 and live["internal_order_no"] in page.text and "Print logo on every unit" in page.text


def test_print_view_escapes_html(client, sales):
    order = save(client, sales, upload(client, sales), customer_name="<script>alert(1)</script>")
    page = client.get(f"/api/orders/{order['id']}/print", headers=sales).text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


# ---------------------------------------------------------------- dashboard / archive / persistence
def test_dashboard_counts_come_from_database(client, sales, printing):
    upload(client, sales)
    live = make_live(client, sales)
    make_live(client, sales, MEET_PAPERS)
    client.post(f"/api/orders/{live['id']}/printing-status", headers=printing, json={"status": "Processing"})
    s = client.get("/api/dashboard", headers=sales).json()["counts"]
    assert s == {"total": 3, "draft": 1, "live": 2, "awaiting_printing": 1, "processing": 1, "print_done": 0}
    p = client.get("/api/dashboard", headers=printing).json()
    assert "draft" not in p["counts"] and p["counts"]["total"] == 2
    assert all(o["status"] == "Live" for o in p["recent"])


def test_archive_draft(client, sales):
    order = upload(client, sales)
    r = client.post(f"/api/orders/{order['id']}/archive", headers=sales, json={"version": order["version"]})
    assert r.status_code == 200
    assert client.get("/api/orders", headers=sales).json()["total"] == 0
    assert client.get("/api/orders", headers=sales, params={"include_archived": True}).json()["total"] == 1


def test_data_survives_restart(client, sales):
    live = make_live(client, sales)
    configure_database(settings.database_path)  # simulate a backend restart (new engine, same files)
    headers = login(client)
    again = client.get(f"/api/orders/{live['id']}", headers=headers).json()
    assert again["internal_order_no"] == live["internal_order_no"]
    assert client.get(f"/api/orders/{live['id']}/source-pdf", headers=headers).content == REAL_PO.read_bytes()
    with SessionLocal() as db:
        assert db.get(Order, live["id"]).status == "Live"


def test_search_by_sku_and_customer(client, sales):
    a = upload(client, sales)
    upload(client, sales, ANNESHA)
    hits = client.get("/api/orders", headers=sales, params={"q": "creative_lamp"}).json()["items"]
    assert [h["id"] for h in hits] == [a["id"]]
    assert client.get("/api/orders", headers=sales, params={"q": "annesha"}).json()["total"] == 1


def test_re_extract_restores_pdf_values(client, sales):
    order = save(client, sales, upload(client, sales), customer_name="Typo", global_customization="Keep me")
    r = client.post(f"/api/orders/{order['id']}/re-extract", headers=sales, json={"version": order["version"]})
    assert r.status_code == 200
    assert r.json()["customer_name"] == "Kalpit Pandya - Frn" and r.json()["global_customization"] == "Keep me"


def test_upload_filename_is_sanitised(client, sales):
    r = client.post("/api/orders/upload", headers=sales,
                    files={"file": ("..\\..\\evil.pdf", io.BytesIO(REAL_PO.read_bytes()), "application/pdf")})
    assert r.status_code == 201 and r.json()["source_filename"] == "evil.pdf"


def test_old_courier_and_amount_warnings_are_not_shown_for_review(client, sales):
    """Orders uploaded before the Shipping/Amounts sections were removed keep their stored data,
    but their stored courier warning is hidden and amount warnings are shown as info only."""
    order = upload(client, sales)
    with SessionLocal() as db:
        stored = db.get(Order, order["id"])
        stored.extraction_warnings = [
            {"field": "courier", "level": "warning", "message": "No courier / transport is printed on the PO."},
            {"field": "total", "level": "warning", "message": "Unrecognised amount 'Shipping Charges: 150.00'."},
            {"field": "gstin", "level": "warning", "message": "GSTIN is not valid."},
        ]
        db.commit()
    detail = client.get(f"/api/orders/{order['id']}", headers=sales).json()
    assert [(w["field"], w["level"]) for w in detail["extraction_warnings"]] == [("total", "info"), ("gstin", "warning")]
    assert detail["warning_count"] == 1
    with SessionLocal() as db:  # stored data unchanged
        assert len(db.get(Order, order["id"]).extraction_warnings) == 3
