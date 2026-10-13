"""Regression: "Method Not Allowed" on product Save Changes.

The editor calls PUT /api/orders/{id}/items/{item_id} (existing product), POST /api/orders/{id}/items (new product)
and PUT /api/orders/{id}/global. A backend without those routes answered 405 because the request fell through to the
GET-only React catch-all route. These tests pin the method/URL contract and require unknown API routes to give 404.
"""
from __future__ import annotations

import pytest

from app.main import FRONTEND_DIST, app

from .conftest import ITEM_KEYS, upload

# (method, path) pairs used by frontend/src/pages/OrderEditor.tsx
EDITOR_SAVE_ROUTES = [
    ("PUT", "/api/orders/{order_id}/items/{item_id}"),
    ("POST", "/api/orders/{order_id}/items"),
    ("PUT", "/api/orders/{order_id}/global"),
    ("PUT", "/api/orders/{order_id}"),
]


@pytest.mark.parametrize("method,path", EDITOR_SAVE_ROUTES)
def test_editor_save_routes_exist_with_the_right_method(method, path):
    paths = app.openapi()["paths"]  # what the running server exposes
    assert method.lower() in paths.get(path, {}), f"{method} {path} is not served"


def test_save_buttons_do_not_get_method_not_allowed(client, sales):
    order = upload(client, sales)
    item = {k: order["items"][0][k] for k in ITEM_KEYS if k != "id"} | {"version": order["version"], "quantity": 61}
    r = client.put(f"/api/orders/{order['id']}/items/{order['items'][0]['id']}", headers=sales, json=item)
    assert r.status_code == 200, r.text  # existing product
    order = r.json()["order"]
    r = client.post(f"/api/orders/{order['id']}/items", headers=sales,
                    json={"version": order["version"], "sku": "NEW-1", "quantity": 1})
    assert r.status_code == 201, r.text  # new product
    order = r.json()["order"]
    r = client.put(f"/api/orders/{order['id']}/global", headers=sales,
                   json={"version": order["version"], "global_customization": "LOGO", "global_names": []})
    assert r.status_code == 200, r.text  # global customization
    saved = client.get(f"/api/orders/{order['id']}", headers=sales).json()
    assert saved["items"][0]["quantity"] == 61 and saved["items"][-1]["sku"] == "NEW-1"
    assert saved["global_customization"] == "LOGO" and saved["status"] == "Draft"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_unknown_api_route_is_404_not_405(client, sales, method):
    r = client.request(method, "/api/orders/1/no-such-route", headers=sales, json={})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "unknown_api_route"
    assert "restart start_backend.bat" in r.json()["detail"]["message"]


def test_react_app_still_served_for_page_urls(client):
    if not FRONTEND_DIST.is_dir():
        pytest.skip("frontend not built")
    r = client.get("/orders/1")
    assert r.status_code == 200 and '<div id="root">' in r.text
