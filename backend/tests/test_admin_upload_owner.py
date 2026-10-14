"""Admin uploads a PO for a chosen Sales user: that user owns it (created_by); other Sales users cannot see it."""
from __future__ import annotations

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Order, OrderEvent

from .conftest import MEET_PAPERS, REAL_PO, login, publish, save, upload
from .test_order_visibility import dashboard, foreign_requests, ids

PASSWORD = "Test-Owner-Pass-1"  # test-only


@pytest.fixture()
def mohit(client, admin):
    """A Sales user the Admin creates later, the way it is done in the app."""
    r = client.post("/api/admin/users", headers=admin, json={"username": "Mohit", "role": "sales", "password": PASSWORD})
    assert r.status_code == 201, r.text
    token = client.post("/api/login", json={"username": "mohit", "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def stored_files() -> int:
    return sum(1 for p in settings.upload_dir.rglob("*") if p.is_file()) if settings.upload_dir.exists() else 0


def test_admin_assigns_upload_to_chosen_sales_user(client, admin, mohit):
    order = upload(client, admin, MEET_PAPERS, owner="  MOHIT ")  # chosen name is normalised
    assert order["created_by"] == "mohit" and order["status"] == "Draft"
    with SessionLocal() as db:
        event = db.query(OrderEvent).filter_by(order_id=order["id"], event="pdf_uploaded").one()
        assert event.actor == "admin" and "for mohit" in event.details  # history shows who uploaded it, for whom

    # the chosen Sales user sees the draft everywhere and can work on it like their own upload
    assert order["id"] in ids(client, mohit)
    assert dashboard(client, mohit)["counts"]["draft"] == 1
    detail = client.get(f"/api/orders/{order['id']}", headers=mohit).json()
    assert detail["permissions"]["can_edit"] and detail["permissions"]["can_publish"]
    saved = save(client, mohit, detail, global_customization="Logo on every unit")
    assert publish(client, mohit, saved).status_code == 200
    assert client.get(f"/api/orders/{order['id']}/source-pdf", headers=mohit).status_code == 200

    # Admin still sees and manages it; Printing sees it once Live
    assert order["id"] in ids(client, admin)
    assert client.get(f"/api/orders/{order['id']}", headers=admin).status_code == 200
    assert order["id"] in ids(client, login(client, "printing"))


def test_other_sales_users_cannot_see_or_reach_assigned_order(client, admin, mohit):
    draft = upload(client, admin, MEET_PAPERS, owner="mohit")
    other = login(client, "sales")
    assert draft["id"] not in ids(client, other, include_archived=True)
    assert dashboard(client, other)["counts"]["total"] == 0
    for method, url, kwargs in foreign_requests(draft):
        assert getattr(client, method)(url, headers=other, **kwargs).status_code == 404, (method, url)


def test_admin_must_choose_an_active_sales_user(client, admin, mohit):
    client.post("/api/admin/users", headers=admin, json={"username": "gone", "role": "sales", "password": PASSWORD})
    gone_id = next(u["id"] for u in client.get("/api/admin/users", headers=admin).json()["items"] if u["username"] == "gone")
    client.patch(f"/api/admin/users/{gone_id}", headers=admin, json={"is_active": False})
    before_files = stored_files()
    with SessionLocal() as db:
        before_orders = db.query(Order).count()
    for owner in (None, "", "   ", "nobody", "printing", "admin", "gone"):
        with open(REAL_PO, "rb") as fh:
            r = client.post("/api/orders/upload", headers=admin, data={"owner": owner} if owner is not None else None,
                            files={"file": ("po.pdf", fh, "application/pdf")})
        assert r.status_code == 422, (owner, r.status_code)
        message = r.json()["detail"]["message"]
        assert "Choose the Sales user" in message or "is not an active Sales user" in message
    with SessionLocal() as db:
        assert db.query(Order).count() == before_orders  # nothing created
    assert stored_files() == before_files  # and no PDF stored


def test_sales_uploads_unchanged_and_cannot_assign_to_others(client, mohit):
    sales = login(client, "sales")
    own = upload(client, sales)  # no owner: belongs to the uploader, as before
    assert own["created_by"] == "sales"
    assert upload(client, sales, owner="Sales")["created_by"] == "sales"  # naming yourself is fine
    with open(REAL_PO, "rb") as fh:
        r = client.post("/api/orders/upload", headers=sales, data={"owner": "mohit"},
                        files={"file": ("po.pdf", fh, "application/pdf")})
    assert r.status_code == 403
    assert not ids(client, mohit)  # nothing was created for Mohit


def test_duplicate_warning_is_from_the_owners_point_of_view(client, admin, mohit):
    """Sales uploaded a PO; Admin uploads the same PDF for Mohit: Mohit's warning names none of Sales' orders."""
    first = upload(client, login(client, "sales"), MEET_PAPERS)
    dup = upload(client, admin, MEET_PAPERS, owner="mohit")
    [warning] = [w["message"] for w in dup["extraction_warnings"] if w["message"].startswith("Possible duplicate")]
    assert "another user" in warning and f"Draft #{first['id']}" not in warning


def test_printing_cannot_upload(client, mohit):
    with open(REAL_PO, "rb") as fh:
        r = client.post("/api/orders/upload", headers=login(client, "printing"), data={"owner": "mohit"},
                        files={"file": ("po.pdf", fh, "application/pdf")})
    assert r.status_code == 403
