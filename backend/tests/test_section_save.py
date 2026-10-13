"""Independent saves: one product row ("Save Changes") and global customization ("Save Global Changes")."""
from __future__ import annotations

from .conftest import ITEM_KEYS, LOGO_JPEG, login, make_live, payload, save, upload


def item_body(order: dict, idx: int = 0, **changes) -> dict:
    body = {k: order["items"][idx][k] for k in ITEM_KEYS if k != "id"}
    body["version"] = order["version"]
    body.update(changes)
    return body


def global_body(order: dict, **changes) -> dict:
    body = {k: order[k] for k in ("global_customization", "global_names", "global_logo_reference", "global_notes")}
    body["version"] = order["version"]
    body.update(changes)
    return body


# ---------------------------------------------------------------- product row
def test_save_one_item_persists_only_that_row(client, sales):
    order = upload(client, sales)
    r = client.put(f"/api/orders/{order['id']}/items/{order['items'][1]['id']}", headers=sales, json=item_body(
        order, 1, quantity=151, rate=67.5, value=10192.5, tax="GST 12%", location="D061", weight="86 x 151",
        hsn="901721", customization_text="DEODAP", customization_names=[], logo_reference="logo v2", notes="Gold"))
    assert r.status_code == 200, r.text
    saved = r.json()["order"]
    assert saved["status"] == "Draft" and saved["internal_order_no"] is None  # not published
    assert saved["version"] == order["version"] + 1

    again = client.get(f"/api/orders/{order['id']}", headers=sales).json()  # persistence after refresh
    row = again["items"][1]
    assert (row["quantity"], row["rate"], row["value"], row["tax"], row["location"]) == (151, 67.5, 10192.5, "GST 12%", "D061")
    assert (row["customization_text"], row["logo_reference"], row["notes"]) == ("DEODAP", "logo v2", "Gold")
    # other rows and order fields untouched
    for i in (0, 2):
        assert {k: again["items"][i][k] for k in ITEM_KEYS} == {k: order["items"][i][k] for k in ITEM_KEYS}
    assert again["customer_name"] == order["customer_name"] and again["contact"] == order["contact"]
    event = [a for a in again["activity"] if a["event"] == "item_saved"][-1]
    assert "row 2" in event["details"] and "quantity" in event["details"]


def test_save_individual_names(client, sales):
    order = upload(client, sales)
    names = [f"Name {n}" for n in range(1, 61)]
    r = client.put(f"/api/orders/{order['id']}/items/{order['items'][0]['id']}", headers=sales,
                   json=item_body(order, 0, customization_names=names + ["  ", ""]))
    assert r.status_code == 200
    assert client.get(f"/api/orders/{order['id']}", headers=sales).json()["items"][0]["customization_names"] == names


def test_add_new_row_via_item_save(client, sales):
    order = upload(client, sales)
    body = {"version": order["version"], "sku": "NEW-1", "product_name": "Mug", "quantity": 2, "rate": 10, "value": 20,
            "customization_names": ["Asha", "Ravi"]}
    r = client.post(f"/api/orders/{order['id']}/items", headers=sales, json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    new = next(i for i in data["order"]["items"] if i["id"] == data["item_id"])
    assert new["sku"] == "NEW-1" and new["position"] == 3 and new["customization_names"] == ["Asha", "Ravi"]
    # the saved row can now receive a logo file
    r = client.post(f"/api/orders/{order['id']}/attachments", headers=sales, data={"item_id": str(data["item_id"])},
                    files={"file": ("logo.jpeg", LOGO_JPEG.read_bytes(), "image/jpeg")})
    assert r.status_code == 201


def test_item_save_validation_errors(client, sales):
    order = upload(client, sales)
    url = f"/api/orders/{order['id']}/items/{order['items'][0]['id']}"
    for bad in ({"quantity": -1}, {"quantity": 1.5}, {"rate": "abc"}, {"value": -5}, {"customization_names": "x"},
                {"sku": "x" * 201}):
        r = client.put(url, headers=sales, json=item_body(order, 0, **bad))
        assert r.status_code == 422, bad
        assert r.json()["detail"]["errors"]
    assert client.get(f"/api/orders/{order['id']}", headers=sales).json()["version"] == order["version"]  # nothing saved


def test_item_save_failures(client, sales, printing):
    order = upload(client, sales)
    other = upload(client, sales)
    url = f"/api/orders/{order['id']}/items/{order['items'][0]['id']}"
    stale = item_body(order, 0, quantity=1)
    save(client, sales, order, contact="9000000001")  # someone else saved meanwhile
    r = client.put(url, headers=sales, json=stale)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_conflict"
    fresh = client.get(f"/api/orders/{order['id']}", headers=sales).json()
    r = client.put(f"/api/orders/{order['id']}/items/{other['items'][0]['id']}", headers=sales, json=item_body(fresh, 0))
    assert r.status_code == 404  # row from another order
    assert client.put(url, headers=printing, json=item_body(fresh, 0)).status_code == 403
    assert client.put(url, json=item_body(fresh, 0)).status_code == 401


def test_item_save_rejected_after_publish(client, sales):
    live = make_live(client, sales)
    url = f"/api/orders/{live['id']}/items/{live['items'][0]['id']}"
    r = client.put(url, headers=sales, json=item_body(live, 0, quantity=999))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "order_locked"
    r = client.post(f"/api/orders/{live['id']}/items", headers=sales, json={"version": live["version"], "sku": "X", "quantity": 1})
    assert r.status_code == 409
    again = client.get(f"/api/orders/{live['id']}", headers=sales).json()
    assert again["items"][0]["quantity"] == live["items"][0]["quantity"] and again["version"] == live["version"]


# ---------------------------------------------------------------- global customization
def test_save_global_only(client, sales):
    order = upload(client, sales)
    r = client.put(f"/api/orders/{order['id']}/global", headers=sales, json=global_body(
        order, global_customization="KHODIYAR ENGINEERING", global_names=["Asha", " ", "Ravi"],
        global_logo_reference="WhatsApp logo 12-Oct", global_notes="Front side only"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Draft" and r.json()["internal_order_no"] is None
    again = client.get(f"/api/orders/{order['id']}", headers=sales).json()
    assert again["global_customization"] == "KHODIYAR ENGINEERING" and again["global_names"] == ["Asha", "Ravi"]
    assert again["global_logo_reference"] == "WhatsApp logo 12-Oct" and again["global_notes"] == "Front side only"
    assert [{k: i[k] for k in ITEM_KEYS} for i in again["items"]] == [{k: i[k] for k in ITEM_KEYS} for i in order["items"]]
    assert any(a["event"] == "global_saved" for a in again["activity"])
    # clearing works too
    r = client.put(f"/api/orders/{order['id']}/global", headers=sales, json=global_body(
        again, global_customization="  ", global_names=[], global_logo_reference=None, global_notes=None))
    assert r.json()["global_customization"] is None and r.json()["global_names"] == []


def test_global_save_validation_and_failures(client, sales, printing):
    order = upload(client, sales)
    url = f"/api/orders/{order['id']}/global"
    assert client.put(url, headers=sales, json=global_body(order, global_names="not a list")).status_code == 422
    assert client.put(url, headers=sales, json=global_body(order, global_notes="x" * 5001)).status_code == 422
    assert client.put(url, headers=printing, json=global_body(order)).status_code == 403
    assert client.put(url, headers=sales, json=global_body(order, version=order["version"] - 1)).status_code == 409


def test_global_save_rejected_after_publish(client, sales):
    live = make_live(client, sales)
    r = client.put(f"/api/orders/{live['id']}/global", headers=sales, json=global_body(live, global_customization="changed"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "order_locked"
    assert client.get(f"/api/orders/{live['id']}", headers=sales).json()["global_customization"] == "Print logo on every unit"


def test_section_saves_then_full_draft_and_publish(client, sales):
    """Section saves count for publishing and keep Save draft / Publish separate."""
    order = save(client, sales, upload(client, sales), contact="9000000001")
    r = client.put(f"/api/orders/{order['id']}/items/{order['items'][0]['id']}", headers=sales,
                   json=item_body(order, 0, customization_text="Happy Diwali"))
    order = r.json()["order"]
    assert order["status"] == "Draft"
    order = save(client, sales, order, global_notes="Rush")  # full save with the new version still works
    assert order["items"][0]["customization_text"] == "Happy Diwali"
    r = client.post(f"/api/orders/{order['id']}/publish", headers=sales, json={"version": order["version"], "reviewed": True})
    assert r.status_code == 200 and r.json()["status"] == "Live"
    assert payload(r.json())["items"][0]["customization_text"] == "Happy Diwali"
    login(client)  # sanity: session handling unaffected


# ---------------------------------------------------------------- fields hidden from the product card
HIDDEN = ("product_name", "original_rate", "weight", "hsn", "tax", "location")


def _store_long_hidden_values(order_id: int) -> None:
    """Simulate extraction storing values longer than the edit limits (SQLite does not enforce lengths)."""
    from app.database import SessionLocal
    from app.models import Order

    with SessionLocal() as db:
        item = db.get(Order, order_id).items[0]
        item.product_name = "P" * 400
        item.tax = "18% (CGST 9% + SGST 9%) inclusive of all taxes"
        db.commit()


def test_hidden_item_fields_are_kept_when_not_sent(client, sales):
    order = upload(client, sales)
    _store_long_hidden_values(order["id"])
    order = client.get(f"/api/orders/{order['id']}", headers=sales).json()
    before = {k: order["items"][0][k] for k in HIDDEN}
    visible = ("sku", "quantity", "rate", "value", "customization_names", "customization_text", "logo_reference", "notes")

    # product card Save Changes without the hidden fields
    body = {k: order["items"][0][k] for k in visible} | {"version": order["version"], "quantity": 61}
    r = client.put(f"/api/orders/{order['id']}/items/{order['items'][0]['id']}", headers=sales, json=body)
    assert r.status_code == 200, r.text  # long hidden values no longer block the save
    order = r.json()["order"]

    # Save draft without the hidden fields
    full = payload(order, customer_name="Saved")
    for item in full["items"]:
        for k in HIDDEN:
            item.pop(k)
    r = client.put(f"/api/orders/{order['id']}", headers=sales, json=full)
    assert r.status_code == 200, r.text

    stored = client.get(f"/api/orders/{order['id']}", headers=sales).json()
    assert stored["items"][0]["quantity"] == 61 and stored["customer_name"] == "Saved"
    assert {k: stored["items"][0][k] for k in HIDDEN} == before  # untouched, not truncated
    assert stored["items"][1]["hsn"] == order["items"][1]["hsn"]


def test_sent_hidden_fields_still_update(client, sales):
    """API clients that send a field can still change or clear it (existing behaviour)."""
    order = upload(client, sales)
    r = client.put(f"/api/orders/{order['id']}/items/{order['items'][0]['id']}", headers=sales,
                   json=item_body(order, 0, location="Z999", tax=None))
    assert r.status_code == 200
    row = client.get(f"/api/orders/{order['id']}", headers=sales).json()["items"][0]
    assert row["location"] == "Z999" and row["tax"] is None
