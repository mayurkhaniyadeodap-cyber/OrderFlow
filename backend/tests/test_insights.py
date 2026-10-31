"""Dashboard charts and notifications: read-only, scoped like the order lists, and free of money for Printing."""
from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import Order

from .conftest import ADMIN_PASSWORD, ANNESHA, MEET_PAPERS, RIYA, login, make_live, make_user, upload

MONEY_KEYS = {"top_customers", "pipeline", "executives"}


@pytest.fixture()
def world(client, admin):
    make_user("salesb", "sales")
    a, b = login(client, "sales"), login(client, "salesb", ADMIN_PASSWORD)
    return {
        "a": a, "b": b, "printing": login(client, "printing"), "admin": admin,
        "a_live": make_live(client, a, ANNESHA), "a_draft": upload(client, a, RIYA),
        "b_live": make_live(client, b, MEET_PAPERS),
    }


def insights(client, headers, **params) -> dict:
    r = client.get("/api/dashboard/insights", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def attention(client, headers) -> dict:
    r = client.get("/api/dashboard/attention", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_requires_sign_in(client):
    assert client.get("/api/dashboard/insights").status_code == 401
    assert client.get("/api/dashboard/attention").status_code == 401


@pytest.mark.parametrize("days,expected", [(7, 7), (14, 14), (30, 30)])
def test_trend_has_one_row_per_day(client, world, days, expected):
    d = insights(client, world["admin"], days=days)
    assert d["days"] == days and len(d["trend"]) == expected


@pytest.mark.parametrize("days", [0, 6, 91])
def test_rejects_out_of_range_days(client, world, days):
    assert client.get("/api/dashboard/insights", headers=world["admin"], params={"days": days}).status_code == 422


def test_sales_sees_only_their_own_orders(client, world):
    a, b = insights(client, world["a"]), insights(client, world["b"])
    assert sum(r["created"] for r in a["trend"]) == 2
    assert sum(r["created"] for r in b["trend"]) == 1
    assert sum(r["published"] for r in a["trend"]) == 1
    assert a["pipeline"] == {"uploaded": 2, "published": 1, "processing": 0, "print_done": 0}
    assert {c["name"] for c in a["top_customers"]} == {world["a_live"]["customer_name"]}


def test_admin_sees_everything(client, world):
    d = insights(client, world["admin"])
    assert d["pipeline"]["uploaded"] == 3 and d["pipeline"]["published"] == 2
    assert sum(r["created"] for r in d["trend"]) == 3
    assert sum(r["total"] for r in d["top_customers"]) == pytest.approx(
        (world["a_live"]["total"] or 0) + (world["b_live"]["total"] or 0))
    assert "executives" in d


def test_sales_gets_no_admin_only_charts(client, world):
    d = insights(client, world["a"])
    assert "executives" not in d


def test_printing_gets_no_money_and_no_drafts(client, world):
    d = insights(client, world["printing"])
    assert not MONEY_KEYS & set(d)
    assert "total" not in str(d)
    assert all(r["created"] == 0 for r in d["trend"])  # uploads would reveal drafts
    assert sum(r["published"] for r in d["trend"]) == 2


def test_archived_orders_are_left_out(client, world):
    with SessionLocal() as db:
        db.get(Order, world["b_live"]["id"]).is_archived = True
        db.commit()
    d = insights(client, world["admin"])
    assert d["pipeline"]["uploaded"] == 2 and d["pipeline"]["published"] == 1
    assert world["b_live"]["id"] not in {o["id"] for o in attention(client, world["printing"])["items"]}


def test_open_jobs_are_grouped_by_age(client, world):
    d = insights(client, world["printing"])
    assert {row["label"]: row["count"] for row in d["job_ages"]}["Under 1 day"] == 2


def test_attention_is_scoped_by_role(client, world):
    a = attention(client, world["a"])
    assert a["count"] == 1 and [o["id"] for o in a["items"]] == [world["a_draft"]["id"]]
    assert attention(client, world["b"])["count"] == 0
    assert attention(client, world["admin"])["count"] == 1
    printing = attention(client, world["printing"])
    assert printing["count"] == 2
    assert {o["id"] for o in printing["items"]} == {world["a_live"]["id"], world["b_live"]["id"]}
    assert world["a_draft"]["id"] not in {o["id"] for o in printing["items"]}


def test_reading_changes_nothing(client, world):
    before = client.get(f"/api/orders/{world['a_live']['id']}", headers=world["a"]).json()
    insights(client, world["admin"], days=30)
    attention(client, world["admin"])
    after = client.get(f"/api/orders/{world['a_live']['id']}", headers=world["a"]).json()
    assert after["version"] == before["version"] and after["updated_at"] == before["updated_at"]
