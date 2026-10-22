"""Order permissions: Admin can do everything Sales can (plus edit Live orders and restore);
Sales and Admin can delete (archive) orders; deletions are logged and reversible."""
from __future__ import annotations

import pytest

from .conftest import (
    ITEM_KEYS, LOGO_JPEG, MEET_PAPERS, REAL_PO, approve_previews, login, make_live, payload, publish, save, upload,
)


def advance(client, printing, order, *statuses):
    for s in statuses:
        if s == "Print Done":
            approve_previews(client, order)  # Sales must confirm every product preview first
        r = client.post(f"/api/orders/{order['id']}/printing-status", headers=printing, json={"status": s})
        assert r.status_code == 200, r.text
    return r.json()


def get(client, headers, order):
    return client.get(f"/api/orders/{order['id']}", headers=headers).json()


def archive(client, headers, order):
    return client.post(f"/api/orders/{order['id']}/archive", headers=headers, json={"version": order["version"]})


# ---------------------------------------------------------------- Admin = Sales + more
def test_admin_full_sales_workflow(client, admin):
    order = upload(client, admin, owner="sales")  # upload (an Admin chooses the owning Sales user)
    assert order["created_by"] == "sales" and order["permissions"]["can_edit"] and order["permissions"]["can_publish"]
    order = save(client, admin, order, contact="9000000001")  # Save draft
    item = {k: order["items"][0][k] for k in ITEM_KEYS if k != "id"} | {"version": order["version"], "customization_text": "LOGO"}
    r = client.put(f"/api/orders/{order['id']}/items/{order['items'][0]['id']}", headers=admin, json=item)  # Save Changes
    assert r.status_code == 200
    order = r.json()["order"]
    r = client.put(f"/api/orders/{order['id']}/global", headers=admin, json={"version": order["version"], "global_notes": "rush"})
    order = r.json()
    r = client.post(f"/api/orders/{order['id']}/attachments", headers=admin, files={"file": ("l.jpeg", LOGO_JPEG.read_bytes(), "image/jpeg")})
    assert r.status_code == 201
    order = r.json()
    r = publish(client, admin, order)  # Publish Live
    assert r.status_code == 200 and r.json()["status"] == "Live" and r.json()["published_by"] == "admin"
    assert client.post(f"/api/orders/{order['id']}/comment", headers=admin, json={"text": "checked"}).status_code == 201
    assert client.get("/api/orders", headers=admin).status_code == 200


def test_admin_still_cannot_do_printing_actions(client, admin):
    live = make_live(client, login(client, "sales"))
    assert client.post(f"/api/orders/{live['id']}/printing-status", headers=admin, json={"status": "Processing"}).status_code == 403
    assert client.post(f"/api/orders/{live['id']}/photos", headers=admin,
                       files={"file": ("p.jpeg", LOGO_JPEG.read_bytes(), "image/jpeg")}).status_code == 403


@pytest.mark.parametrize("statuses", [(), ("Processing",), ("Processing", "Print Done")])
def test_admin_edits_live_order_in_any_printing_status(client, admin, statuses):
    sales, printing = login(client, "sales"), login(client, "printing")
    live = make_live(client, sales)
    live = advance(client, printing, live, *statuses) if statuses else live
    live = get(client, admin, live)
    assert live["permissions"]["can_edit"] and not live["permissions"]["can_publish"]
    body = payload(live, customer_name="Corrected Customer")
    body["items"][0]["quantity"] = 61
    r = client.put(f"/api/orders/{live['id']}", headers=admin, json=body)
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["customer_name"] == "Corrected Customer" and after["items"][0]["quantity"] == 61
    # the Live identity is never changed by an edit
    for key in ("status", "internal_order_no", "live_at", "printing_status", "published_by", "print_done_at"):
        assert after[key] == live[key], key
    event = [a for a in after["activity"] if a["event"] == "live_edited"][-1]
    assert event["actor"] == "admin" and "customer" in event["details"]
    # Printing sees the change
    assert get(client, printing, live)["customer_name"] == "Corrected Customer"


def test_admin_live_edit_must_keep_publish_rules(client, admin):
    live = make_live(client, login(client, "sales"))  # customization is global only
    r = client.put(f"/api/orders/{live['id']}", headers=admin, json=payload(live, global_customization=None))
    assert r.status_code == 422 and any("Customization is required" in e for e in r.json()["detail"]["errors"])
    r = client.put(f"/api/orders/{live['id']}/global", headers=admin, json={"version": live["version"], "global_customization": None})
    assert r.status_code == 422
    item = {k: live["items"][0][k] for k in ITEM_KEYS if k != "id"} | {"version": live["version"], "sku": None}
    assert client.put(f"/api/orders/{live['id']}/items/{live['items'][0]['id']}", headers=admin, json=item).status_code == 422
    unchanged = get(client, admin, live)
    assert unchanged["global_customization"] == "Print logo on every unit" and unchanged["version"] == live["version"]


def test_live_lock_unchanged_for_sales_and_re_extract(client, admin):
    sales = login(client, "sales")
    live = make_live(client, sales)
    r = client.put(f"/api/orders/{live['id']}", headers=sales, json=payload(live, customer_name="x"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "order_locked"
    assert get(client, sales, live)["permissions"]["can_edit"] is False
    # re-extracting would replace product rows: Drafts only, even for Admin
    assert client.post(f"/api/orders/{live['id']}/re-extract", headers=admin, json={"version": live["version"]}).status_code == 409


def test_printing_cannot_manage_orders(client):
    printing = login(client, "printing")
    live = make_live(client, login(client, "sales"))
    with open(REAL_PO, "rb") as fh:
        assert client.post("/api/orders/upload", headers=printing, files={"file": ("po.pdf", fh)}).status_code == 403
    assert client.put(f"/api/orders/{live['id']}", headers=printing, json=payload(live)).status_code == 403
    assert archive(client, printing, live).status_code == 403
    assert client.post(f"/api/orders/{live['id']}/restore", headers=printing, json={"version": 1}).status_code == 403


# ---------------------------------------------------------------- delete (archive) + restore
def test_sales_deletes_draft_and_new_live_order_but_not_started_ones(client):
    sales, printing = login(client, "sales"), login(client, "printing")
    draft = upload(client, sales)
    assert archive(client, sales, draft).status_code == 200
    new_live = make_live(client, sales)
    assert get(client, sales, new_live)["permissions"]["can_delete"] is True
    r = archive(client, sales, new_live)
    assert r.status_code == 200 and r.json()["is_archived"] is True
    started = advance(client, printing, make_live(client, sales, MEET_PAPERS), "Processing")
    started = get(client, sales, started)
    assert started["permissions"]["can_delete"] is False
    r = archive(client, sales, started)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "delete_not_allowed"


def test_admin_deletes_any_order_and_restores_it(client, admin):
    sales, printing = login(client, "sales"), login(client, "printing")
    done = advance(client, printing, make_live(client, sales), "Processing", "Print Done")
    done = get(client, admin, done)
    r = archive(client, admin, done)
    assert r.status_code == 200
    deleted = r.json()
    assert deleted["permissions"]["can_restore"] and not deleted["permissions"]["can_delete"]
    # hidden from the Printing queue, Sales list and dashboards; history kept
    assert client.get(f"/api/orders/{done['id']}", headers=printing).status_code == 404
    assert client.get("/api/orders", headers=printing).json()["total"] == 0
    assert client.get("/api/orders", headers=sales).json()["total"] == 0
    assert client.get("/api/admin/dashboard", headers=admin).json()["orders"]["archived"] == 1
    # deleted orders cannot be edited or deleted again
    assert client.put(f"/api/orders/{done['id']}", headers=admin, json=payload(deleted)).status_code == 409
    assert archive(client, admin, deleted).status_code == 409
    # only Admin restores; everything comes back unchanged
    assert client.post(f"/api/orders/{done['id']}/restore", headers=sales, json={"version": deleted["version"]}).status_code == 403
    r = client.post(f"/api/orders/{done['id']}/restore", headers=admin, json={"version": deleted["version"]})
    assert r.status_code == 200
    back = r.json()
    for key in ("internal_order_no", "status", "printing_status", "live_at", "print_done_at"):
        assert back[key] == done[key], key
    assert [o["id"] for o in client.get("/api/orders", headers=printing).json()["items"]] == [done["id"]]
    assert client.post(f"/api/orders/{done['id']}/restore", headers=admin, json={"version": back["version"]}).status_code == 409


def test_deletions_are_in_the_activity_log(client, admin):
    sales = login(client, "sales")
    draft = upload(client, sales)
    archive(client, sales, draft)
    deleted = get(client, admin, draft)
    client.post(f"/api/orders/{draft['id']}/restore", headers=admin, json={"version": deleted["version"]})
    log = client.get("/api/admin/activity", headers=admin, params={"source": "order"}).json()["items"]
    archived = next(i for i in log if i["action"] == "archived")
    restored = next(i for i in log if i["action"] == "restored")
    assert archived["actor"] == "sales" and archived["label"] == "Deleted (archived)" and archived["order_id"] == draft["id"]
    assert restored["actor"] == "admin" and restored["label"] == "Restored"
    assert any(e["event"] == "archived" for e in get(client, admin, draft)["activity"])


def test_delete_requires_current_version(client):
    sales, printing = login(client, "sales"), login(client, "printing")
    live = make_live(client, sales)
    advance(client, printing, live, "Processing")  # Printing started after Sales opened the order
    r = archive(client, sales, live)  # stale version and no longer New
    assert r.status_code in (403, 409)
    assert get(client, sales, live)["is_archived"] is False
