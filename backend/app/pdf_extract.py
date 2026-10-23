"""PO PDF text extraction.

The supplied sample POs ("SelfServe Order #..." dispatch notes) print Billing and Shipping
addresses side by side, so plain text extraction merges the two columns. This module works on
word coordinates instead: it locates the block headings, the Rate/Qty/Value table and the
totals labels, then reads values from the matching regions.

Rules:
* Only values printed in the PDF are returned. Nothing is guessed.
* Every missing, unusual or inconsistent value produces a warning so Sales can review it.
* Scanned/image-only PDFs (no text layer) are reported, not OCR'd.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber

LEVEL_ERROR = "error"  # extraction could not run / layout unknown
LEVEL_WARNING = "warning"  # value missing, uncertain or inconsistent: review needed
LEVEL_INFO = "info"  # worth knowing, no action strictly required

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w])(\+?\d[\d \-]{8,14}\d)(?![\w])")
NUMBER_RE = re.compile(r"^-?(?:₹|Rs\.?\s*)?\d[\d,]*(?:\.\d+)?$")
ORDER_RE = re.compile(r"Order\s*#\s*([A-Za-z0-9][\w\-/]*)\s*(?:\(\s*([^)]+?)\s*\))?", re.I)
PO_FALLBACK_RE = re.compile(r"\bP\.?\s?O\.?\s*(?:No\.?|Number|#)\s*[:\-]?\s*([A-Za-z0-9][\w\-/]*)", re.I)
DATE_RE = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?:\s*-?\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?)?")
NA_VALUES = {"", "n/a", "na", "-", "--", "nil", "none", "null"}

BLOCK_HEADINGS = {
    "billing": re.compile(r"^billing\s+address:?$", re.I),
    "shipping": re.compile(r"^shipping\s+address:?$", re.I),
    "seller": re.compile(r"^seller\s+gst\s+details:?$", re.I),
    "agent": re.compile(r"^agent\s*/\s*dropshipper\s*/\s*reseller:?$", re.I),
}
STATUS_BOX_LABELS = {"TYPE": "order_type", "PART TYPE": "part_type", "TOTAL PARTS": "total_parts", "STATUS": "box_status"}
DETAIL_WEIGHT = re.compile(r"^weight\s*:\s*(.*)$", re.I)
DETAIL_HSN = re.compile(r"^hsn(?:\s*/\s*sac)?\s*:\s*([^,]*?)\s*(?:,\s*tax\s*:\s*(.*))?$", re.I)
DETAIL_LOCATION = re.compile(r"^location\s*:\s*(.*)$", re.I)
TOTAL_LABELS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^sub\s*-?\s*total$", re.I), "subtotal"),
    (re.compile(r"^pre\s*-?\s*tax\s+total$", re.I), "pretax_total"),
    (re.compile(r"^packaging\s+charges?$", re.I), "packaging_charges"),
    (re.compile(r"^processing\s+charges?$", re.I), "processing_charges"),
    (re.compile(r"^additional\s+charges?$", re.I), "additional_charges"),
    (re.compile(r"^(?:total\s+)?(?:tax|gst)(?:\s+amount)?$", re.I), "tax"),
    (re.compile(r"^(?:grand\s+|net\s+)?total(?:\s*\(\s*including\s+tax\s*\))?$", re.I), "total"),
]
SUMMARY_LABELS = {
    "item_summary": re.compile(r"^item\s*/\s*qty\s*/\s*wt$", re.I),
    "selfship_type": re.compile(r"^selfship\s*/\s*type$", re.I),
    "wallet_balance": re.compile(r"^wallet\s+balance$", re.I),
}


# ---------------------------------------------------------------- data classes
@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    bold: bool
    size: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class ExtractionResult:
    order: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    layout: str = "unknown"
    text_chars: int = 0
    pages: int = 0

    def warn(self, field_name: str, message: str, level: str = LEVEL_WARNING) -> None:
        self.warnings.append({"field": field_name, "level": level, "message": message})

    @property
    def note(self) -> str:
        counts = {lvl: sum(1 for w in self.warnings if w["level"] == lvl) for lvl in (LEVEL_ERROR, LEVEL_WARNING)}
        layout = {"selfserve": "SelfServe Order layout", "generic": "unrecognised layout"}.get(self.layout, self.layout)
        parts = [f"{len(self.items)} product row(s) extracted from {self.pages} page(s) ({layout})."]
        if counts[LEVEL_ERROR]:
            parts.append(f"{counts[LEVEL_ERROR]} error(s).")
        if counts[LEVEL_WARNING]:
            parts.append(f"{counts[LEVEL_WARNING]} warning(s) need review.")
        if not counts[LEVEL_ERROR] and not counts[LEVEL_WARNING]:
            parts.append("No issues detected; still verify against the source PDF before publishing.")
        return " ".join(parts)


# ---------------------------------------------------------------- parsing helpers
def parse_number(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().replace("₹", "").replace(",", "")
    cleaned = re.sub(r"^Rs\.?\s*", "", cleaned, flags=re.I)
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int(text: str | None) -> int | None:
    value = parse_number(text)
    if value is None or value != int(value):
        return None
    return int(value)


def is_number(text: str) -> bool:
    return bool(NUMBER_RE.match(text.strip()))


def parse_source_date(text: str) -> str | None:
    """Parse 'dd/mm/yyyy - hh:mm AM' (Indian day-first format) into 'YYYY-MM-DDTHH:MM'."""
    m = DATE_RE.search(text)
    if not m:
        return None
    day, month, year, hour, minute, ampm = m.groups()
    try:
        h = int(hour) if hour else 0
        if ampm:
            h = h % 12 + (12 if ampm.lower() == "pm" else 0)
        dt = datetime(int(year), int(month), int(day), h, int(minute) if minute else 0)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M")


def is_na(value: str | None) -> bool:
    return value is None or value.strip().lower() in NA_VALUES


def close(a: float, b: float, tolerance: float = 0.01) -> bool:
    return abs(a - b) <= tolerance + 1e-9


# ---------------------------------------------------------------- page model
class PageModel:
    """All upright words of the document with page tops offset so pages stack vertically."""

    def __init__(self, pdf: pdfplumber.PDF):
        self.words: list[Word] = []
        self.strikes: list[tuple[float, float, float]] = []  # (x0, x1, y)
        self.width = float(pdf.pages[0].width) if pdf.pages else 595.0
        offset = 0.0
        for page in pdf.pages:
            # Drop rotated/skewed characters (diagonal "DRAFT" watermarks, vertical side text).
            horizontal = page.filter(lambda o: o.get("object_type") != "char" or _is_horizontal(o))
            for w in horizontal.extract_words(
                keep_blank_chars=True, x_tolerance=1.5, y_tolerance=2, extra_attrs=["fontname", "size"]
            ):
                text = re.sub(r"\s+", " ", w["text"]).strip()
                if not text:
                    continue
                if re.fullmatch(r"(?:DRAFT\s*)+", text):  # watermark text
                    continue
                self.words.append(
                    Word(text, float(w["x0"]), float(w["x1"]), float(w["top"]) + offset,
                         float(w["bottom"]) + offset, "bold" in w.get("fontname", "").lower(), float(w.get("size", 0)))
                )
            for obj in list(page.lines) + [r for r in page.rects if float(r["height"]) <= 1.5]:
                if abs(float(obj["top"]) - float(obj["bottom"])) <= 1.5:
                    y = (float(obj["top"]) + float(obj["bottom"])) / 2 + offset
                    self.strikes.append((float(obj["x0"]), float(obj["x1"]), y))
            offset += float(page.height)
        self.words.sort(key=lambda w: (round(w.top), w.x0))

    def rows(self, words: list[Word] | None = None, tolerance: float = 3.0) -> list[list[Word]]:
        rows: list[list[Word]] = []
        for w in sorted(words if words is not None else self.words, key=lambda w: (w.top, w.x0)):
            if rows and abs(rows[-1][0].top - w.top) <= tolerance:
                rows[-1].append(w)
            else:
                rows.append([w])
        return [sorted(r, key=lambda w: w.x0) for r in rows]

    def find(self, pattern: re.Pattern[str], **bounds: float) -> Word | None:
        found = self.find_all(pattern, **bounds)
        return found[0] if found else None

    def find_all(self, pattern: re.Pattern[str], min_x: float = -1, max_top: float = 1e12) -> list[Word]:
        return [w for w in self.words if pattern.match(w.text) and w.x0 >= min_x and w.top < max_top]

    def same_row(self, anchor: Word, min_x: float | None = None, max_x: float | None = None) -> list[Word]:
        return [
            w for w in self.words
            if abs(w.top - anchor.top) <= 3 and w is not anchor
            and (min_x is None or w.x0 >= min_x) and (max_x is None or w.x1 <= max_x)
        ]

    def is_struck(self, w: Word) -> bool:
        return any(
            w.top + 1 <= y <= w.bottom - 1 and min(x1, w.x1) - max(x0, w.x0) >= 0.5 * (w.x1 - w.x0)
            for x0, x1, y in self.strikes
        )


def _is_horizontal(char: dict) -> bool:
    a, b, c, d, *_ = char.get("matrix") or (1, 0, 0, 1)
    return abs(b) < 1e-3 and abs(c) < 1e-3 and a > 0 and d > 0


def _row_text(row: list[Word]) -> str:
    return " ".join(w.text for w in row).strip()


# ---------------------------------------------------------------- main entry point
def extract_po(path: str | Path) -> ExtractionResult:
    result = ExtractionResult()
    try:
        with pdfplumber.open(str(path)) as pdf:
            result.pages = len(pdf.pages)
            if not pdf.pages:
                result.warn("file", "The PDF has no pages.", LEVEL_ERROR)
                return result
            model = PageModel(pdf)
    except Exception as exc:  # pdfminer raises many exception types for damaged files
        result.warn("file", f"The PDF could not be read ({type(exc).__name__}). It may be corrupt or password-protected. "
                    "The file was kept; enter the order details manually or re-upload a valid PDF.", LEVEL_ERROR)
        return result

    result.text_chars = sum(len(w.text) for w in model.words)
    if result.text_chars < 20:
        result.warn("file", "No extractable text was found. This looks like a scanned or image-only PDF; OCR is not "
                    "supported yet. Enter the order details manually from the source PDF.", LEVEL_ERROR)
        return result

    _extract_header(model, result)
    table = _find_table_header(model)
    if table is None and not model.find(BLOCK_HEADINGS["billing"]):
        result.layout = "generic"
        _extract_generic(model, result)
        return result

    result.layout = "selfserve"
    _extract_status_box(model, result)
    _extract_blocks(model, result, table)
    end_top = _extract_summary(model, result)
    if table is None:
        result.warn("items", "Product table (Rate / Qty / Value) was not found. Add product rows manually.")
    else:
        _extract_items(model, result, table, end_top)
    _cross_check(result)
    return result


# ---------------------------------------------------------------- sections
def _extract_header(model: PageModel, result: ExtractionResult) -> None:
    rows = model.rows()
    header_text = " ".join(_row_text(r) for r in rows[:3])
    m = ORDER_RE.search(header_text)
    if m:
        result.order["po_number"] = m.group(1)
        if m.group(2):
            result.order["source_status"] = m.group(2).strip()
    else:
        m2 = PO_FALLBACK_RE.search(" ".join(_row_text(r) for r in rows))
        if m2:
            result.order["po_number"] = m2.group(1)
    if not result.order.get("po_number"):
        result.warn("po_number", "PO / order number was not found.")
    elif not m:
        result.warn("po_number", "PO number found outside the page header; verify it.")

    date = parse_source_date(header_text)
    if date:
        result.order["source_order_date"] = date
        result.meta["source_order_date_printed"] = DATE_RE.search(header_text).group(0)  # type: ignore[union-attr]
        if int(date[8:10]) <= 12:
            result.warn("source_order_date", "Order date was read as day/month/year (Indian format).", LEVEL_INFO)
    else:
        result.warn("source_order_date", "Source order date was not found in the header.")


def _extract_status_box(model: PageModel, result: ExtractionResult) -> None:
    billing = model.find(BLOCK_HEADINGS["billing"])
    limit = billing.top if billing else 200
    for label, key in STATUS_BOX_LABELS.items():
        for lw in model.words:
            if lw.text != label or lw.top > limit:
                continue
            above = [w for w in model.words if w is not lw and abs(w.cx - lw.cx) <= 40
                     and lw.top - 30 <= w.top < lw.top - 2 and w.text not in STATUS_BOX_LABELS]
            if above:
                result.meta[key] = max(above, key=lambda w: w.top).text
            break


def _block_lines(model: PageModel, heading: Word, x_min: float, x_max: float, y_max: float) -> list[str]:
    words = [w for w in model.words if x_min <= w.x0 < x_max and heading.bottom - 1 <= w.top < y_max and w is not heading]
    return [_row_text(r) for r in model.rows(words) if _row_text(r)]


def _extract_blocks(model: PageModel, result: ExtractionResult, table: dict[str, Word] | None) -> None:
    headings = {key: model.find(rx) for key, rx in BLOCK_HEADINGS.items()}
    found = {k: h for k, h in headings.items() if h}
    left_x = headings["billing"].x0 if headings["billing"] else 0
    split = headings["shipping"].x0 - 4 if headings["shipping"] else model.width / 2
    table_top = table["rate"].top if table else 1e12
    blocks: dict[str, list[str]] = {}
    for key, h in found.items():
        is_left = h.x0 < split
        x_min, x_max = (left_x - 3, split) if is_left else (split, model.width)
        later = [o.top for o in found.values() if o is not h and o.top > h.top and ((o.x0 < split) == is_left)]
        blocks[key] = _block_lines(model, h, x_min, x_max, min(later + [table_top]))

    # Billing → customer
    billing = blocks.get("billing")
    if billing is None:
        result.warn("billing_address", "Billing Address block was not found.")
    else:
        name, address, gstin, contact = _split_block(billing)
        if name:
            result.order["customer_name"] = name
        if address:
            result.order["billing_address"] = address
        if gstin is None:
            result.warn("gstin", "GSTIN was not printed in the billing address.", LEVEL_INFO)
        elif is_na(gstin):
            result.warn("gstin", "GSTIN is printed as N/A.", LEVEL_INFO)
        else:
            result.order["gstin"] = gstin
            if not GSTIN_RE.match(gstin.replace(" ", "").upper()):
                result.warn("gstin", f"GSTIN '{gstin}' is not a valid 15-character GSTIN. Verify with the customer.")
        if contact:
            _apply_contact(result, contact)

    shipping = blocks.get("shipping")
    if shipping is None:
        result.warn("shipping_address", "Shipping Address block was not found.")
    else:
        name, address, _gst, contact = _split_block(shipping)
        if name:
            result.order["shipping_name"] = name
        if address:
            result.order["shipping_address"] = address
        if contact:
            _apply_contact(result, contact, overwrite=True)

    if "agent" in blocks:
        lines = blocks["agent"]
        agent = next((ln for ln in lines if not ln.lower().startswith("contact")), None)
        if agent:
            result.meta["agent"] = agent
        contact = next((ln for ln in lines if ln.lower().startswith("contact")), None)
        if contact and not result.order.get("contact"):
            _apply_contact(result, contact)
            result.warn("contact", "Contact taken from the Agent / DropShipper block.", LEVEL_INFO)
    if "seller" in blocks:
        result.meta["seller"] = " | ".join(blocks["seller"])

    if not result.order.get("customer_name"):
        if result.order.get("shipping_name"):
            result.order["customer_name"] = result.order["shipping_name"]
            result.warn("customer_name", "Customer name taken from the shipping address (billing name missing).")
        else:
            result.warn("customer_name", "Customer name was not found.")
    elif result.order.get("shipping_name") and _norm(result.order["shipping_name"]) != _norm(result.order["customer_name"]):
        result.warn("shipping_name", "Ship-to name differs from the billing (customer) name.", LEVEL_INFO)
    if not result.order.get("contact"):
        result.warn("contact", "Contact number was not found.")
    if not result.order.get("email"):
        result.warn("email", "Email address was not found.", LEVEL_INFO)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _split_block(lines: list[str]) -> tuple[str | None, str | None, str | None, str | None]:
    gstin = contact = None
    rest: list[str] = []
    for ln in lines:
        if m := re.match(r"^GSTIN\s*:?\s*(.*)$", ln, re.I):
            gstin = m.group(1).strip()
        elif re.match(r"^(contact|phone|mobile|tel)\b", ln, re.I):
            contact = ln
        else:
            rest.append(ln)
    name = rest[0] if rest else None
    address = "\n".join(rest[1:]) if len(rest) > 1 else None
    return name, address, gstin, contact


def _apply_contact(result: ExtractionResult, line: str, overwrite: bool = False) -> None:
    body = re.sub(r"^[A-Za-z ]+:\s*", "", line)
    emails = EMAIL_RE.findall(body)
    phones = [p.strip() for p in PHONE_RE.findall(EMAIL_RE.sub(" ", body))]
    if phones and (overwrite or not result.order.get("contact")):
        result.order["contact"] = " / ".join(dict.fromkeys(phones))
    if emails and (overwrite or not result.order.get("email")):
        result.order["email"] = emails[0]


def _extract_summary(model: PageModel, result: ExtractionResult) -> float:
    """Executive, summary rows, transport and totals. Returns the top of the summary area."""
    tops: list[float] = []
    right_start = model.width * 0.55

    executive = model.find(re.compile(r"^executive:?$", re.I))
    if executive:
        tops.append(executive.top)
        right_labels = [w.x0 for w in model.same_row(executive, min_x=executive.x1) if not is_number(w.text) and w.x0 > right_start]
        limit = min(right_labels) - 1 if right_labels else right_start
        value = " ".join(w.text for w in model.same_row(executive, min_x=executive.x1, max_x=limit)).strip()
        if value:
            result.order["executive"] = value
    if not result.order.get("executive"):
        result.warn("executive", "Executive / sales contact was not found.", LEVEL_INFO)

    for key, rx in SUMMARY_LABELS.items():
        label = model.find(rx)
        if label:
            tops.append(label.top)
            value = " ".join(w.text for w in model.same_row(label, min_x=label.x1, max_x=right_start)).strip()
            if value:
                result.meta[key] = value

    seen: set[str] = set()
    for row in model.rows():
        right = [w for w in row if w.x0 >= right_start]
        if len(right) < 2 or not is_number(right[-1].text):
            continue
        label = " ".join(w.text for w in right[:-1]).strip()
        if not re.search(r"[A-Za-z]", label):
            continue
        amount = parse_number(right[-1].text)
        key = next((k for rx, k in TOTAL_LABELS if rx.match(label)), None)
        tops.append(row[0].top)
        if key is None:
            result.meta.setdefault("other_amounts", {})[label] = amount
            result.warn("total", f"Unrecognised amount '{label}: {right[-1].text}' kept in source details.", LEVEL_INFO)
        elif key in seen:
            result.warn(key, f"'{label}' appears more than once; the first value was used.", LEVEL_INFO)
        else:
            seen.add(key)
            if key == "pretax_total":
                result.meta["pretax_total"] = amount
            else:
                result.order[key] = amount
    if "subtotal" not in seen:
        result.warn("subtotal", "Subtotal was not found.", LEVEL_INFO)
    if "total" not in seen:
        result.warn("total", "Order total was not found.", LEVEL_INFO)
    return min(tops) if tops else 1e12


def _find_table_header(model: PageModel) -> dict[str, Word] | None:
    for rate in model.find_all(re.compile(r"^(rate|price|unit\s+price)$", re.I)):
        row = model.same_row(rate)
        qty = next((w for w in row if re.match(r"^(qty|quantity)$", w.text, re.I)), None)
        value = next((w for w in row if re.match(r"^(value|amount|total)$", w.text, re.I)), None)
        if qty and value:
            return {"rate": rate, "qty": qty, "value": value}
    return None


def _extract_items(model: PageModel, result: ExtractionResult, table: dict[str, Word], end_top: float) -> None:
    columns = {"rate": table["rate"].x1, "qty": table["qty"].x1, "value": table["value"].x1}
    desc_limit = table["rate"].x0 - 25
    start = max(w.bottom for w in table.values())
    region = [w for w in model.words if start <= w.top < end_top - 1]
    if end_top >= 1e12:
        result.warn("items", "End of the product table was not detected; check that no extra rows were captured.")

    desc_rows = model.rows([w for w in region if w.x0 < desc_limit])
    numbers = [w for w in region if w.x0 >= desc_limit and is_number(w.text)]
    any_bold = any(w.bold for r in desc_rows for w in r)

    def is_detail(text: str) -> bool:
        return bool(DETAIL_WEIGHT.match(text) or DETAIL_HSN.match(text) or DETAIL_LOCATION.match(text))

    # Group description rows into items: a title row (bold, not a detail line) starts an item.
    groups: list[dict[str, Any]] = []
    for row in desc_rows:
        text = _row_text(row)
        title_like = not is_detail(text) and (all(w.bold for w in row) if any_bold else True)
        if title_like and (not groups or groups[-1]["details"]):
            groups.append({"top": row[0].top, "title": [text], "details": []})
        elif title_like:
            groups[-1]["title"].append(text)  # wrapped title
        elif groups:
            groups[-1]["details"].append(text)
        else:
            result.warn("items", f"Text '{text}' above the first product row was ignored.")

    derived_names = False
    for idx, group in enumerate(groups):
        top = group["top"] - 3
        bottom = groups[idx + 1]["top"] - 3 if idx + 1 < len(groups) else end_top
        cells: dict[str, list[Word]] = {"rate": [], "qty": [], "value": []}
        for w in numbers:
            if top <= w.top < bottom:
                col = min(columns, key=lambda c: abs(columns[c] - w.x1))
                if abs(columns[col] - w.x1) <= 20:
                    cells[col].append(w)
        for col in cells:
            cells[col].sort(key=lambda w: w.top)

        item: dict[str, Any] = {"position": idx}
        title = " ".join(group["title"]) if len(group["title"]) == 1 else "".join(group["title"])
        if len(group["title"]) > 1:
            result.warn(f"items.{idx}.sku", "Product code wrapped over several lines; verify it.")
        if re.fullmatch(r"[\w\-./]+", title):
            item["sku"] = title
            item["product_name"] = title.replace("_", " ")
            derived_names = True
        elif m := re.match(r"^(\S+)\s+[-–:|]\s+(.+)$", title):
            item["sku"], item["product_name"] = m.group(1), m.group(2)
            result.warn(f"items.{idx}.sku", f"SKU '{m.group(1)}' was split from '{title}'; verify it.")
        else:
            item["product_name"] = title
            result.warn(f"items.{idx}.sku", f"No SKU code could be separated from '{title}'. Enter the SKU.")

        extra: list[str] = []
        for d in group["details"]:
            if m := DETAIL_WEIGHT.match(d):
                item["weight"] = m.group(1).strip() or None
            elif m := DETAIL_HSN.match(d):
                item["hsn"] = None if is_na(m.group(1)) else m.group(1).strip()
                if m.group(2) and not is_na(m.group(2)):
                    item["tax"] = m.group(2).strip()
            elif m := DETAIL_LOCATION.match(d):
                item["location"] = None if is_na(m.group(1)) else m.group(1).strip()
            else:
                extra.append(d)
        if extra:
            item["product_name"] = f"{item.get('product_name') or ''} — {'; '.join(extra)}".strip(" —")

        rates = cells["rate"]
        if rates:
            item["rate"] = parse_number(rates[0].text)
            if model.is_struck(rates[0]):
                result.warn(f"items.{idx}.rate", "The first rate is struck through on the PDF; verify the rate.")
            for extra_rate in rates[1:]:
                if model.is_struck(extra_rate):
                    item["original_rate"] = parse_number(extra_rate.text)
                else:
                    result.warn(f"items.{idx}.rate", f"Extra unstruck number {extra_rate.text} in the Rate column; verify the rate.")
        else:
            result.warn(f"items.{idx}.rate", "Rate was not found.")
        if cells["qty"]:
            qty = parse_int(cells["qty"][0].text)
            if qty is None:
                result.warn(f"items.{idx}.quantity", f"Quantity '{cells['qty'][0].text}' is not a whole number.")
            item["quantity"] = qty
        else:
            result.warn(f"items.{idx}.quantity", "Quantity was not found.")
        if cells["value"]:
            item["value"] = parse_number(cells["value"][0].text)
        else:
            result.warn(f"items.{idx}.value", "Line value was not found.")
        if item.get("rate") is not None and item.get("quantity") and item.get("value") is not None:
            expected = round(item["rate"] * item["quantity"], 2)
            if not close(expected, item["value"], max(0.01, item["value"] * 0.0005)):
                result.warn(f"items.{idx}.value",
                            f"Rate × Qty = {expected:.2f} but the PDF shows {item['value']:.2f}. Kept the printed value; verify.")
        result.items.append(item)

    if not groups:
        result.warn("items", "No product rows were found in the product table. Add them manually.")
    if derived_names:
        result.warn("items", "The PO prints only a product code per row; product names were derived from it "
                    "(underscores replaced by spaces).", LEVEL_INFO)


def _cross_check(result: ExtractionResult) -> None:
    values = [i.get("value") for i in result.items]
    subtotal = result.order.get("subtotal")
    if subtotal is not None and values and all(v is not None for v in values):
        total_values = round(sum(values), 2)  # type: ignore[arg-type]
        if not close(total_values, subtotal):
            result.warn("subtotal", f"Sum of line values ({total_values:.2f}) differs from the printed subtotal "
                        f"({subtotal:.2f}). Values kept as printed; verify.", LEVEL_INFO)

    summary = result.meta.get("item_summary")
    if summary:
        nums = re.findall(r"\d+(?:\.\d+)?", summary)
        if len(nums) >= 2:
            count, qty = int(float(nums[0])), float(nums[1])
            if count != len(result.items):
                result.warn("items", f"The PO summary lists {count} item(s) but {len(result.items)} row(s) were extracted.")
            quantities = [i.get("quantity") for i in result.items]
            if all(q is not None for q in quantities) and sum(quantities) != qty:  # type: ignore[arg-type]
                result.warn("items", f"The PO summary total quantity is {nums[1]} but extracted rows add up to {sum(quantities)}.")  # type: ignore[arg-type]

    pretax, tax, total = result.meta.get("pretax_total"), result.order.get("tax"), result.order.get("total")
    if pretax is not None and tax is not None and total is not None and not close(pretax + tax, total):
        result.warn("total", f"PreTax Total + Tax ({pretax + tax:.2f}) differs from Total ({total:.2f}); verify.", LEVEL_INFO)
    if tax is None and total is not None:
        result.warn("tax", "Tax amount is not printed separately.", LEVEL_INFO)


def _extract_generic(model: PageModel, result: ExtractionResult) -> None:
    """Unknown layout: do not guess field values; list detected contact details for reference only."""
    text = "\n".join(_row_text(r) for r in model.rows())
    result.warn("file", "This PO layout is not recognised. Only the PO number/date were attempted; enter the "
                "customer and product rows manually from the source PDF.", LEVEL_ERROR)
    detected = {
        "emails": sorted(set(EMAIL_RE.findall(text))),
        "phones": sorted(set(p.strip() for p in PHONE_RE.findall(EMAIL_RE.sub(" ", text)))),
        "gstins": sorted(set(re.findall(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b", text))),
    }
    result.meta["detected_for_reference"] = {k: v for k, v in detected.items() if v}


# ---------------------------------------------------------------- SKU selection
def parse_sku_list(text: str | None) -> list[str]:
    """Comma/newline separated SKUs typed by Sales; blanks and repeats dropped, order kept."""
    seen: dict[str, str] = {}
    for part in re.split(r"[,\n;]+", text or ""):
        sku = part.strip()
        if sku and sku.lower() not in seen:
            seen[sku.lower()] = sku
    return list(seen.values())


def _sku_matches(wanted: str, sku: str | None) -> bool:
    """Exact match (case-insensitive), or the PO SKU starts with the typed code followed by a separator
    (e.g. '6462' matches '6462_7in1_keyboard_clean_brush')."""
    if not sku:
        return False
    w, s = wanted.lower(), sku.lower()
    return s == w or (s.startswith(w) and not s[len(w)].isalnum())


def filter_items_by_sku(result: ExtractionResult, skus: list[str]) -> None:
    """Keep only the product rows whose SKU was requested; renumber per-row warnings and flag SKUs not found."""
    if not skus:
        return
    keep = [idx for idx, item in enumerate(result.items) if any(_sku_matches(w, item.get("sku")) for w in skus)]
    remap = {old: new for new, old in enumerate(keep)}
    warnings = []
    for w in result.warnings:
        if m := re.match(r"^items\.(\d+)\.(.+)$", w["field"]):
            old = int(m.group(1))
            if old not in remap:
                continue
            w = {**w, "field": f"items.{remap[old]}.{m.group(2)}"}
        warnings.append(w)
    result.warnings = warnings
    total = len(result.items)
    result.items = [{**result.items[old], "position": new} for new, old in enumerate(keep)]
    missing = [w for w in skus if not any(_sku_matches(w, i.get("sku")) for i in result.items)]
    if missing:
        result.warn("items", f"SKU(s) not found in the PO: {', '.join(missing)}. Add those rows manually if needed.")
    result.meta["selected_skus"] = ", ".join(skus)
    result.warn("items", f"Only the requested SKU(s) were kept: {len(result.items)} of {total} product row(s). "
                "Order totals are still the PO's printed totals.", LEVEL_INFO)
