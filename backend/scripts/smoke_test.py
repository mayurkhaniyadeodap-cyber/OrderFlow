"""Live end-to-end smoke test against RUNNING servers (not part of pytest).

Usage:  python scripts/smoke_test.py [base_url] [path/to/po.pdf]
        base_url defaults to http://127.0.0.1:5173 (the Vite dev server, which proxies /api to the backend).

It signs in as the Sales and Printing accounts from backend\.env (SALES_* / PRINTING_*), uploads a PO, completes the Draft, publishes it, walks the printing
status to Print Done and posts comments. It creates real records, so point
the backend at a scratch database (DATABASE_PATH / UPLOAD_DIR environment variables) when running it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5173"
PDF = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "tests/fixtures/samples/order_73530274.pdf"
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))
    print(("PASS " if ok else "FAIL ") + label)


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60)
    check(c.get("/api/health").json()["status"] == "ok", "health endpoint")
    index = c.get("/")
    check(index.status_code == 200 and '<div id="root">' in index.text, "React app served at /")

    def login(user: str, pw: str) -> dict:
        r = c.post("/api/login", json={"username": user, "password": pw})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    # credentials come from the environment / backend\.env (SALES_* and PRINTING_*), never from this file
    sales = login(os.environ["SALES_USERNAME"], os.environ["SALES_PASSWORD"])
    printing = login(os.environ["PRINTING_USERNAME"], os.environ["PRINTING_PASSWORD"])
    check(c.get("/api/me", headers=sales).json()["user"]["role"] == "sales", "sales login")
    check(c.get("/api/me", headers=printing).json()["user"]["role"] == "printing", "printing login")

    r = c.post("/api/orders/upload", headers=sales, files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")})
    order = r.json()
    check(r.status_code == 201 and order["status"] == "Draft", f"upload -> Draft #{order.get('id')}")
    check(len(order["items"]) >= 1 and order["customer_name"], f"extracted {len(order['items'])} rows for {order['customer_name']}")
    check(c.get(f"/api/orders/{order['id']}", headers=printing).status_code == 404, "draft hidden from Printing")

    r = c.post(f"/api/orders/{order['id']}/publish", headers=sales, json={"version": order["version"], "reviewed": True})
    check(r.status_code == 422, "publish blocked without customization")

    body = {k: order[k] for k in (
        "po_number", "source_status", "source_order_date", "customer_name", "billing_address", "shipping_name",
        "shipping_address", "contact", "email", "gstin", "executive", "subtotal", "packaging_charges",
        "processing_charges", "additional_charges", "tax", "total", "global_names", "global_logo_reference", "global_notes")}
    item_keys = ("id", "sku", "product_name", "quantity", "rate", "original_rate", "value", "weight", "hsn", "tax",
                 "location", "customization_names", "customization_text", "logo_reference", "notes")
    body |= {"version": order["version"], "global_customization": "Smoke-test logo",
             "items": [{k: i[k] for k in item_keys} for i in order["items"]]}
    r = c.put(f"/api/orders/{order['id']}", headers=sales, json=body)
    check(r.status_code == 200, "draft saved with global customization")
    order = r.json()

    r = c.post(f"/api/orders/{order['id']}/publish", headers=sales, json={"version": order["version"], "reviewed": True})
    live = r.json()
    check(r.status_code == 200 and live["internal_order_no"], f"published as {live.get('internal_order_no')}")
    check(c.put(f"/api/orders/{order['id']}", headers=sales, json=body | {"version": live["version"]}).status_code == 409,
          "Live order locked against edits")

    queue = c.get("/api/orders", headers=printing).json()["items"]
    check(any(o["id"] == live["id"] and o["printing_status"] == "New" for o in queue), "order in printing queue as New")
    for status in ("Processing", "Print Done"):
        r = c.post(f"/api/orders/{live['id']}/printing-status", headers=printing, json={"status": status})
        check(r.status_code == 200 and r.json()["printing_status"] == status, f"printing -> {status}")
    check(c.post(f"/api/orders/{live['id']}/printing-status", headers=printing, json={"status": "New"}).status_code == 409,
          "Print Done locked")

    r = c.post(f"/api/orders/{live['id']}/comment", headers=printing, json={"text": "Smoke test comment"})
    check(r.status_code == 201, "comment after Print Done")
    pdf = c.get(f"/api/orders/{live['id']}/source-pdf", headers=printing)
    check(pdf.status_code == 200 and pdf.content[:5] == b"%PDF-", "source PDF download")

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
