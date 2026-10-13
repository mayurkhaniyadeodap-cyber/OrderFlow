"""Executive / sales contacts and hidden informational extraction notes."""
from __future__ import annotations

import sqlite3

import pytest

from app import contacts
from app.config import settings
from app.database import SessionLocal, configure_database
from app.models import AppSetting, Order, SalesContact

from .conftest import ANNESHA, MEET_PAPERS, REAL_PO, login, payload, save, upload

REAL_EXEC = "Dhruv Bhojani - Izzat (6358956693)"  # printed on the supplied sample PO


def names():
    with SessionLocal() as db:
        return [c.name for c in db.query(SalesContact).order_by(SalesContact.id)]


# ---------------------------------------------------------------- matching
@pytest.mark.parametrize("a,b", [("Dhruv Bhojani", "  dhruv bhojani  "), ("Rina Gohel-JD", "RINA   GOHEL-JD"),
                                 ("Harsha\tPrajapati", "harsha prajapati")])
def test_names_match_ignoring_case_and_spaces(a, b):
    assert contacts.name_key(a) == contacts.name_key(b)


def test_different_names_do_not_match():
    assert contacts.name_key("Dhruv Bhojani") != contacts.name_key("Dhruv Bhojani - Izzat")


# ---------------------------------------------------------------- automatic extraction
def test_upload_saves_extracted_executive_once(client, sales):
    upload(client, sales)
    assert names() == [REAL_EXEC]
    upload(client, sales)  # same executive on a later PO: reused, not duplicated
    upload(client, sales, MEET_PAPERS)  # a different executive is added
    assert names() == [REAL_EXEC, "Harsha Prajapati-JD (7283912175)"]
    with SessionLocal() as db:
        assert db.query(SalesContact).filter_by(name=REAL_EXEC).one().source == "extracted"


def test_po_without_executive_adds_nothing(client, sales):
    upload(client, sales, ANNESHA)  # the screenshot cuts off the executive line
    assert names() == []


# ---------------------------------------------------------------- manual entry on Save draft
def test_manual_entry_is_saved_and_reused_case_insensitively(client, sales):
    order = upload(client, sales)
    order = save(client, sales, order, executive="  Priya Shah  ")
    assert order["executive"] == "Priya Shah"  # order keeps the entered text (trimmed as before)
    assert names() == [REAL_EXEC, "Priya Shah"]
    save(client, sales, order, executive="PRIYA   shah")  # same person, different spelling
    save(client, sales, upload(client, sales), executive="dhruv bhojani - izzat (6358956693)")
    assert names() == [REAL_EXEC, "Priya Shah"]
    with SessionLocal() as db:
        assert db.query(SalesContact).filter_by(name="Priya Shah").one().source == "manual"


def test_blank_executive_is_not_saved(client, sales):
    save(client, sales, upload(client, sales, ANNESHA), executive="   ")
    assert names() == []


def test_contacts_survive_restart(client, sales):
    save(client, sales, upload(client, sales), executive="Priya Shah")
    configure_database(settings.database_path, settings.backup_dir)  # simulate a backend restart
    assert names() == [REAL_EXEC, "Priya Shah"]
    assert client.get("/api/contacts", headers=login(client)).json()["items"] == [REAL_EXEC, "Priya Shah"]


def test_sales_form_list(client, sales, admin):
    save(client, sales, upload(client, sales), executive="Asha")
    assert client.get("/api/contacts", headers=sales).json()["items"] == ["Asha", REAL_EXEC]  # sorted
    assert client.get("/api/contacts", headers=admin).status_code == 200
    assert client.get("/api/contacts", headers=login(client, "printing")).status_code == 403
    assert client.get("/api/contacts").status_code == 401


# ---------------------------------------------------------------- Admin management
def test_admin_can_add_view_edit_and_delete(client, admin, sales):
    order = upload(client, sales)
    r = client.post("/api/admin/contacts", headers=admin, json={"name": "  Mohit  Mahaliya "})
    assert r.status_code == 201 and r.json()["name"] == "Mohit Mahaliya" and r.json()["source"] == "admin"
    mohit = r.json()["id"]
    assert client.post("/api/admin/contacts", headers=admin, json={"name": "MOHIT MAHALIYA"}).status_code == 409
    assert client.post("/api/admin/contacts", headers=admin, json={"name": "   "}).status_code == 422

    listed = {c["name"]: c for c in client.get("/api/admin/contacts", headers=admin).json()["items"]}
    assert listed[REAL_EXEC]["orders"] == 1 and listed["Mohit Mahaliya"]["orders"] == 0

    r = client.patch(f"/api/admin/contacts/{mohit}", headers=admin, json={"name": "Mohit M."})
    assert r.status_code == 200 and r.json()["name"] == "Mohit M."
    dhruv = listed[REAL_EXEC]["id"]
    assert client.patch(f"/api/admin/contacts/{mohit}", headers=admin, json={"name": REAL_EXEC.upper()}).status_code == 409
    assert client.delete(f"/api/admin/contacts/{dhruv}", headers=admin).json() == {"ok": True}
    assert names() == ["Mohit M."]
    # deleting/renaming a contact never changes orders
    assert client.get(f"/api/orders/{order['id']}", headers=sales).json()["executive"] == REAL_EXEC
    assert client.delete("/api/admin/contacts/9999", headers=admin).status_code == 404
    actions = {i["action"] for i in client.get("/api/admin/activity", headers=admin, params={"source": "admin"}).json()["items"]}
    assert {"contact_created", "contact_updated", "contact_deleted"} <= actions


@pytest.mark.parametrize("who", ["sales", "printing", None])
def test_contact_management_is_admin_only(client, who):
    headers = login(client, who) if who else {}
    code = 403 if who else 401
    assert client.get("/api/admin/contacts", headers=headers).status_code == code
    assert client.post("/api/admin/contacts", headers=headers, json={"name": "X Y"}).status_code == code
    assert client.patch("/api/admin/contacts/1", headers=headers, json={"name": "X Y"}).status_code == code
    assert client.delete("/api/admin/contacts/1", headers=headers).status_code == code
    assert names() == []


# ---------------------------------------------------------------- one-time backfill
def test_backfill_imports_existing_order_names_once_without_changing_orders(client, sales):
    a = save(client, sales, upload(client, sales), executive="Rina Gohel-JD")
    b = save(client, sales, upload(client, sales), executive="  rina gohel-jd ")
    with SessionLocal() as db:  # simulate a database from before this feature
        db.query(SalesContact).delete()
        db.query(AppSetting).filter_by(key=contacts.BACKFILL_FLAG).delete()
        db.commit()
        before = [(o.id, o.executive, o.version, o.updated_at) for o in db.query(Order).order_by(Order.id)]
        assert contacts.backfill_from_orders(db) == 1  # one contact for both spellings
        after = [(o.id, o.executive, o.version, o.updated_at) for o in db.query(Order).order_by(Order.id)]
        assert after == before  # orders untouched
        assert contacts.backfill_from_orders(db) is None  # runs only once
    assert names() == ["Rina Gohel-JD"]
    assert {a["executive"], b["executive"]} == {"Rina Gohel-JD", "rina gohel-jd"}


def test_new_table_on_existing_database_is_backed_up_first(tmp_path):
    db_path = tmp_path / "old.db"
    configure_database(db_path, tmp_path / "bk")  # create a full database
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE sales_contacts")  # as it was before this update
    con.commit()
    con.close()
    configure_database(db_path, tmp_path / "bk")
    snapshots = [p.name for p in (tmp_path / "bk").iterdir()]
    assert len(snapshots) == 1 and snapshots[0].startswith("pre_schema_update_")
    con = sqlite3.connect(tmp_path / "bk" / snapshots[0])
    assert "sales_contacts" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master")}  # copy taken before
    con.close()


# ---------------------------------------------------------------- hidden informational notes
HIDDEN = ("GSTIN is printed as N/A.", "The PO prints only a product code per row", "Tax amount is not printed separately.")


def test_three_info_notes_hidden_but_duplicate_warning_kept(client, sales):
    first = upload(client, sales)
    shown = " | ".join(w["message"] for w in first["extraction_warnings"])
    assert not any(h in shown for h in HIDDEN)
    assert "day/month/year" in shown  # other useful notes stay
    second = upload(client, sales, REAL_PO)
    assert any(w["message"].startswith("Possible duplicate") and w["level"] == "warning" for w in second["extraction_warnings"])
    assert not any(h in " | ".join(w["message"] for w in second["extraction_warnings"]) for h in HIDDEN)
    with SessionLocal() as db:  # still stored on the order, unchanged
        stored = " | ".join(w["message"] for w in db.get(Order, first["id"]).extraction_warnings)
    assert all(h in stored for h in HIDDEN)
    order = client.get(f"/api/orders/{first['id']}", headers=sales).json()
    assert order["gstin"] is None and order["items"][0]["product_name"] == "12939 3d square shape creative lamp"
    assert payload(order)["tax"] is None


# ---------------------------------------------------------------- contact detail: linked orders
def _contact_id(client, admin, name):
    return next(c["id"] for c in client.get("/api/admin/contacts", headers=admin).json()["items"] if c["name"] == name)


def test_contact_orders_lists_matching_orders(client, sales, admin):
    a = upload(client, sales)                                       # extracted exactly
    b = save(client, sales, upload(client, sales), executive="  DHRUV   bhojani - izzat (6358956693) ")  # case/spaces
    c = save(client, sales, upload(client, sales, MEET_PAPERS), executive="Someone Else")
    gone = upload(client, sales)
    client.post(f"/api/orders/{gone['id']}/archive", headers=sales, json={"version": gone["version"]})
    cid = _contact_id(client, admin, REAL_EXEC)
    listed = next(x for x in client.get("/api/admin/contacts", headers=admin).json()["items"] if x["id"] == cid)

    r = client.get(f"/api/admin/contacts/{cid}/orders", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert data["contact"]["name"] == REAL_EXEC
    assert data["total"] == listed["orders"] == 2  # same number as the list shows; deleted order left out
    assert {o["id"] for o in data["items"]} == {a["id"], b["id"]} and c["id"] not in {o["id"] for o in data["items"]}
    row = next(o for o in data["items"] if o["id"] == a["id"])
    assert row["customer_name"] == "Kalpit Pandya - Frn" and row["po_number"] == "135-73530274"
    assert row["status"] == "Draft" and row["printing_status"] is None and row["source_order_date"] == "2026-10-08T18:13"
    assert [o["id"] for o in data["items"]] == sorted([a["id"], b["id"]], reverse=True)  # newest first


def test_contact_with_no_orders(client, admin):
    cid = client.post("/api/admin/contacts", headers=admin, json={"name": "New Person"}).json()["id"]
    data = client.get(f"/api/admin/contacts/{cid}/orders", headers=admin).json()
    assert data["total"] == 0 and data["items"] == []
    assert client.get("/api/admin/contacts/9999/orders", headers=admin).status_code == 404


def test_contact_orders_is_admin_only_and_read_only(client, sales, admin):
    order = upload(client, sales)
    cid = _contact_id(client, admin, REAL_EXEC)
    for who in ("sales", "printing"):
        assert client.get(f"/api/admin/contacts/{cid}/orders", headers=login(client, who)).status_code == 403
    assert client.get(f"/api/admin/contacts/{cid}/orders").status_code == 401
    before = client.get(f"/api/orders/{order['id']}", headers=sales).json()
    client.get(f"/api/admin/contacts/{cid}/orders", headers=admin)
    after = client.get(f"/api/orders/{order['id']}", headers=sales).json()
    assert (after["version"], after["updated_at"], after["executive"]) == (before["version"], before["updated_at"], before["executive"])
    assert names() == [REAL_EXEC]
