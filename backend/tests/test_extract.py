"""PDF extraction against the supplied sample PO and the layout variants seen in the PO screenshots."""
from __future__ import annotations

import pytest

from app.pdf_extract import extract_po, parse_int, parse_number, parse_source_date

from .conftest import ANNESHA, IMAGE_ONLY_PDF, MEET_PAPERS, REAL_PO, RIYA, sample


def fields(result, level=None):
    return {w["field"] for w in result.warnings if level is None or w["level"] == level}


def messages(result):
    return " | ".join(w["message"] for w in result.warnings)


def test_real_sample_po_order_fields():
    r = extract_po(sample(REAL_PO))
    assert r.layout == "selfserve"
    o = r.order
    assert o["po_number"] == "135-73530274"
    assert o["source_status"] == "Processing"
    assert o["source_order_date"] == "2026-10-08T18:13"
    assert o["customer_name"] == "Kalpit Pandya - Frn"
    assert o["shipping_name"] == "Kalpit Pandya Frn"
    assert o["billing_address"] == "124-A Shrinath Nagar, Sector-9, Udaipur, Rajasthan,\n313002\nUdaipur 313002 Rajasthan"
    assert o["shipping_address"] == o["billing_address"]
    assert o["contact"] == "8619140473"
    assert o["email"] == "k4kalpit@gmail.com"
    assert "gstin" not in o  # printed as N/A
    assert o["executive"] == "Dhruv Bhojani - Izzat (6358956693)"
    assert (o["subtotal"], o["packaging_charges"], o["processing_charges"], o["additional_charges"], o["total"]) == (
        18673.50, 100.00, 746.94, 560.00, 20080.40)
    assert r.meta["agent"] == "Kalpit Pandya Frn (129432)"
    assert r.meta["item_summary"] == "3 / 420 / 30720 gms."
    assert r.meta["selfship_type"] == "No / Orange"


def test_real_sample_po_items():
    items = extract_po(sample(REAL_PO)).items
    assert [(i["sku"], i["quantity"], i["rate"], i["value"]) for i in items] == [
        ("12939_3d_square_shape_creative_lamp", 60, 87.20, 5232.00),
        ("6462_7in1_keyboard_clean_brush", 150, 67.00, 10050.00),
        ("whl135_5027e_custom_print_level5", 210, 16.15, 3391.50),
    ]
    assert [i.get("original_rate") for i in items] == [None, 70.01, 17.03]  # struck-through MRP
    assert items[0]["weight"] == "262 x 60 = 15720 Gms"
    assert [i["hsn"] for i in items] == ["940540", "901720", "392410"]
    assert all(i["tax"] == "GST 18%" for i in items)
    assert [i["location"] for i in items] == ["J022", "D060", None]


def test_real_sample_po_flags_without_inventing():
    r = extract_po(sample(REAL_PO))
    assert "courier" not in r.order  # "Transport" is blank on the PDF → never guessed
    assert "courier" not in fields(r)  # courier is not used: no "assign a courier" warning
    assert not fields(r, "error")
    assert "subtotal" not in fields(r, "warning")  # line values add up to the subtotal


def test_watermarked_draft_layout_with_seller_block():
    r = extract_po(MEET_PAPERS)
    o = r.order
    assert o["po_number"] == "135-39390483" and o["source_status"] == "Draft"
    assert o["customer_name"] == "MEET PAPERS"
    assert "DRAFT" not in o["billing_address"] and "DRAFT" not in o["shipping_address"]
    # The billing GSTIN is not a valid GSTIN: kept as printed and flagged; the seller's GSTIN is NOT used.
    assert o["gstin"] == "9714741880 24AB"
    assert "not a valid 15-character GSTIN" in messages(r)
    assert "24AAHCD5265C1ZX" in r.meta["seller"]
    assert (o["subtotal"], o["tax"], o["total"]) == (10470.00, 1884.60, 12354.60)
    assert r.meta["pretax_total"] == 10470.00
    assert [(i["sku"], i["rate"], i.get("original_rate"), i["quantity"], i["value"]) for i in r.items] == [
        ("2834_500ml_vacuum_flask_set", 170.00, 229.00, 60, 10200.00),
        ("whl135_5027c_custom_print_level3", 4.50, 5.00, 60, 270.00),
    ]
    assert o["executive"] == "Harsha Prajapati-JD (7283912175)"
    assert fields(r, "warning") == {"gstin"}  # only the invalid GSTIN needs review


def test_status_box_layout_and_partial_page():
    r = extract_po(ANNESHA)
    assert r.order["po_number"] == "135-85801119" and r.order["source_status"] == "New"
    assert (r.meta["order_type"], r.meta["part_type"], r.meta["total_parts"], r.meta["box_status"]) == (
        "CLO", "PRIMARY", "2", "AWAITED")
    assert r.order["customer_name"] == "Annesha Solutions"
    assert r.order["shipping_name"] == "Chinmay Sinha"
    assert "shipping_name" in fields(r, "info")
    assert r.order["contact"] == "9939198875"
    assert [i["sku"] for i in r.items] == ["whl135_5027e_custom_print_level5", "whl205_79509_stainless_steel_cassrole"]
    assert r.items[1]["tax"] == "GST 05%"
    # Totals are cut off in the source screenshot → flagged, not invented.
    assert {"subtotal", "total"} <= fields(r, "info")  # amounts are informational only
    assert not {"subtotal", "total"} & fields(r, "warning")
    assert "subtotal" not in r.order and "total" not in r.order


def test_subtotal_mismatch_is_flagged_and_values_kept():
    r = extract_po(RIYA)
    assert r.order["subtotal"] == 15377.90
    assert [i["value"] for i in r.items] == [15137.92, 240.00]
    assert "15377.92" in messages(r) and "subtotal" in fields(r, "info")
    assert r.items[0].get("original_rate") is None and r.items[1]["original_rate"] == 6.81
    assert r.order["gstin"] == "24BGFPS9800N1ZW"
    assert "gstin" not in fields(r, "warning")


def test_image_only_pdf_is_flagged_for_manual_entry():
    r = extract_po(sample(IMAGE_ONLY_PDF))
    assert r.order == {} and r.items == []
    assert r.warnings[0]["level"] == "error" and "OCR" in r.warnings[0]["message"]


def test_corrupt_pdf_does_not_raise(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\nthis is not really a pdf\n%%EOF")
    r = extract_po(bad)
    assert r.items == [] and r.warnings[0]["level"] == "error"


@pytest.mark.parametrize("text,expected", [
    ("87.20", 87.20), ("18,673.50", 18673.50), ("₹1,000", 1000.0), ("Rs. 25", 25.0), ("-19178.50", -19178.50),
    ("abc", None), ("", None), (None, None),
])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_parse_int_rejects_fractions():
    assert parse_int("150") == 150 and parse_int("1,200") == 1200
    assert parse_int("1.5") is None and parse_int("x") is None


def test_parse_source_date_day_first():
    assert parse_source_date("08/10/2026 - 06:13 PM") == "2026-10-08T18:13"
    assert parse_source_date("09/10/2026 - 12:02 AM") == "2026-10-09T00:02"
    assert parse_source_date("31/02/2026") is None
