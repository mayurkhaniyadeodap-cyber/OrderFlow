"""Upload PO with a comma-separated SKU list: only those product rows are kept in the Draft."""
from __future__ import annotations

from app.pdf_extract import extract_po, filter_items_by_sku, parse_sku_list

from .conftest import REAL_PO, sample


def test_parse_sku_list():
    assert parse_sku_list(" a, b ,,A\nc; ") == ["a", "b", "c"]
    assert parse_sku_list(None) == []


def test_filter_keeps_requested_rows_and_flags_missing():
    r = extract_po(sample(REAL_PO))
    filter_items_by_sku(r, parse_sku_list("WHL135_5027E_CUSTOM_PRINT_LEVEL5, 6462, nope_sku"))
    assert [i["sku"] for i in r.items] == ["6462_7in1_keyboard_clean_brush", "whl135_5027e_custom_print_level5"]
    assert [i["position"] for i in r.items] == [0, 1]
    assert all(int(w["field"].split(".")[1]) < 2 for w in r.warnings if w["field"].startswith("items."))
    assert any("nope_sku" in w["message"] for w in r.warnings)
    assert r.meta["selected_skus"] == "WHL135_5027E_CUSTOM_PRINT_LEVEL5, 6462, nope_sku"


def test_prefix_needs_separator():
    r = extract_po(sample(REAL_PO))
    filter_items_by_sku(r, ["646"])  # not a full code
    assert r.items == []


def test_upload_route_with_skus(client, sales):
    with open(sample(REAL_PO), "rb") as fh:
        res = client.post("/api/orders/upload", headers=sales, data={"skus": "12939"},
                          files={"file": ("po.pdf", fh, "application/pdf")})
    assert res.status_code == 201, res.text
    order = res.json()
    assert [i["sku"] for i in order["items"]] == ["12939_3d_square_shape_creative_lamp"]
    res = client.post(f"/api/orders/{order['id']}/re-extract", headers=sales, json={"version": order["version"]})
    assert res.status_code == 200, res.text
    assert [i["sku"] for i in res.json()["items"]] == ["12939_3d_square_shape_creative_lamp"]
