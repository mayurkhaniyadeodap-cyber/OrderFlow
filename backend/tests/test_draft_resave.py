"""Regression: Save draft must work repeatedly on the same Draft and persist the latest values."""
from __future__ import annotations

from .conftest import ITEM_KEYS, LOGO_JPEG, payload, publish, upload


def put_draft(client, headers, order, **changes):
    body = payload(order, **{k: v for k, v in changes.items() if k != "row0"})
    if "row0" in changes:
        body["items"][0].update(changes["row0"])
    r = client.put(f"/api/orders/{order['id']}", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def reload(client, headers, order):
    return client.get(f"/api/orders/{order['id']}", headers=headers).json()


def test_second_save_draft_persists_latest_values(client, sales):
    order = upload(client, sales)
    first = put_draft(client, sales, order, customer_name="First Name", contact="9000000001", global_notes="note 1",
                      subtotal=100.0, row0={"quantity": 61, "notes": "row note 1", "customization_names": ["A"]})
    stored = reload(client, sales, order)
    assert (stored["customer_name"], stored["contact"], stored["items"][0]["quantity"]) == ("First Name", "9000000001", 61)

    second = put_draft(client, sales, first, customer_name="Second Name", contact="9000000002", global_notes="note 2",
                       subtotal=200.5, email="second@example.com",
                       row0={"quantity": 77, "notes": "row note 2", "customization_names": ["A", "B"]})
    assert second["version"] == first["version"] + 1

    stored = reload(client, sales, order)  # "refresh the page"
    assert stored["customer_name"] == "Second Name"
    assert stored["contact"] == "9000000002"
    assert stored["global_notes"] == "note 2"
    assert stored["subtotal"] == 200.5 and stored["email"] == "second@example.com"
    row = stored["items"][0]
    assert (row["quantity"], row["notes"], row["customization_names"]) == (77, "row note 2", ["A", "B"])
    assert [a["event"] for a in stored["activity"]].count("draft_saved") == 2
    assert stored["status"] == "Draft"


def test_save_draft_many_times_with_section_saves_in_between(client, sales):
    order = upload(client, sales)
    for n in range(1, 4):
        order = put_draft(client, sales, order, customer_name=f"Name {n}", row0={"quantity": 60 + n})
        # product card save
        item = {k: order["items"][1][k] for k in ITEM_KEYS if k != "id"} | {"version": order["version"], "notes": f"card {n}"}
        r = client.put(f"/api/orders/{order['id']}/items/{order['items'][1]['id']}", headers=sales, json=item)
        assert r.status_code == 200, r.text
        order = r.json()["order"]
        # global save
        r = client.put(f"/api/orders/{order['id']}/global", headers=sales, json={
            "version": order["version"], "global_customization": f"LOGO {n}", "global_names": []})
        assert r.status_code == 200, r.text
        order = r.json()
        # logo upload (does not change the version)
        r = client.post(f"/api/orders/{order['id']}/attachments", headers=sales,
                        files={"file": ("logo.jpeg", LOGO_JPEG.read_bytes(), "image/jpeg")})
        assert r.status_code == 201 and r.json()["version"] == order["version"]
        order = r.json()
    order = put_draft(client, sales, order, customer_name="Final", contact="9000000003")

    stored = reload(client, sales, order)
    assert stored["customer_name"] == "Final" and stored["contact"] == "9000000003"
    assert stored["items"][0]["quantity"] == 63 and stored["items"][1]["notes"] == "card 3"
    assert stored["global_customization"] == "LOGO 3"
    live = publish(client, sales, stored)  # Publish Live still works afterwards
    assert live.status_code == 200 and live.json()["status"] == "Live"
