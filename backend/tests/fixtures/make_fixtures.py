"""Regenerate PO layout-variant fixtures.

Only one sample PO was supplied as a real PDF (samples/order_73530274.pdf). Three more sample POs
were supplied as phone screenshots (WhatsApp images). These fixtures re-typeset the values visible
in those screenshots with the same layout (fonts, columns, struck-through MRP, status box, Seller
GST block, DRAFT watermark) so the extractor can be tested against each variant. Parts cut off in
the screenshots are intentionally omitted.

Run:  python tests/fixtures/make_fixtures.py
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "layouts"
W, H = A4
SELLER = ["Dabster International Private Limited", "C/o, Barjar Paint,Opp. Rangoli Masala, Village-", "Navagam",
          "rajkot 360003 Gujarat", "GSTIN: 24AAHCD5265C1ZX"]


class Page:
    def __init__(self, path: Path):
        self.c = canvas.Canvas(str(path), pagesize=A4)

    def text(self, x, top, s, bold=False, size=9.8, right=False):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        y = H - top - size * 0.8
        (self.c.drawRightString if right else self.c.drawString)(x, y, s)

    def struck(self, x_right, top, s, size=8.7):
        self.text(x_right, top, s, size=size, right=True)
        width = self.c.stringWidth(s, "Helvetica", size)
        y = H - top - size * 0.45
        self.c.line(x_right - width, y, x_right, y)

    def block(self, x, top, heading, lines):
        self.text(x, top, heading, bold=True)
        for i, ln in enumerate(lines):
            self.text(x, top + 12 + i * 11.8, ln)

    def item(self, top, sku, details, rate, mrp, qty, value):
        self.text(116, top, sku, bold=True)
        for i, d in enumerate(details):
            self.text(116, top + 11 + i * 11, d, size=8.7)
        self.text(457, top, rate, right=True)
        if mrp:
            self.struck(457, top + 11, mrp)
        self.text(500, top, qty, bold=True, right=True)
        self.text(562, top, value, right=True)

    def table_header(self, top):
        self.text(457, top, "Rate", bold=True, size=8.7, right=True)
        self.text(500, top, "Qty", bold=True, size=8.7, right=True)
        self.text(562, top, "Value", bold=True, size=8.7, right=True)

    def label_value(self, top, label, value):
        self.text(106, top, label, size=8.7, right=True)
        self.text(116, top, value, bold=True, size=8.7)

    def total(self, top, label, value):
        self.text(501, top, label, bold=True, right=True)
        self.text(562, top, value, bold=True, right=True)

    def watermark(self):
        self.c.saveState()
        self.c.setFont("Helvetica", 9)
        self.c.setFillGray(0.85)
        for gx in range(0, int(W), 60):
            for gy in range(0, int(H), 60):
                self.c.saveState()
                self.c.translate(gx, gy)
                self.c.rotate(45)
                self.c.drawString(0, 0, "DRAFT")
                self.c.restoreState()
        self.c.restoreState()

    def save(self):
        self.c.showPage()
        self.c.save()


def meet_papers_draft():
    p = Page(OUT / "meet_papers_draft.pdf")
    p.watermark()
    p.text(25, 19, "SelfServe Order #135-39390483 (Draft)", bold=True, size=11.7)
    p.text(571, 19, "09/10/2026 - 10:02 AM", bold=True, size=11.7, right=True)
    addr = ["STREET NO 5, NAVALNAGAR -6 CORNER, NR", "RAMANATH HOS, MAIN ROAD, RAJKOT, Rajkot,", "Gujarat, 360004",
            "RAJKOT 360004 Gujarat"]
    p.block(25, 47, "Billing Address", ["MEET PAPERS", *addr, "GSTIN: 9714741880 24AB"])
    p.block(266, 47, "Shipping Address", ["Meet Papers", *addr, "Contact: 9714741880 / MEET@gmail.com"])
    p.block(25, 140, "Seller GST Details", SELLER)
    p.block(266, 140, "Agent / DropShipper / Reseller", ["Meet Papers (145940)", "Contact: 9714741880 / MEET@gmail.com"])
    p.table_header(215)
    p.item(233, "2834_500ml_vacuum_flask_set", ["Weight: 500 x 60 = 30000 Gms", "HSN/SAC: 961700, Tax: GST 18%",
           "Location: A087"], "170.00", "229.00", "60", "10200.00")
    p.item(300, "whl135_5027c_custom_print_level3", ["Weight: 100 x 60 = 6000 Gms", "HSN/SAC: 392410, Tax: GST 18%",
           "Location: C000"], "4.50", "5.00", "60", "270.00")
    p.label_value(370, "Executive", "Harsha Prajapati-JD (7283912175)")
    p.total(370, "SubTotal", "10470.00")
    p.label_value(389, "Item / Qty / Wt", "2 / 120 / 36000 gms.")
    p.label_value(408, "SelfShip / Type", "No / Dropshipper")
    p.label_value(427, "Wallet Balance", "0.00 (0.00 Unverified)")
    p.total(480, "PreTax Total", "10470.00")
    p.total(499, "Tax", "1884.60")
    p.total(518, "Total", "12354.60")
    p.text(106, 560, "Ship Boxes", size=8.7, right=True)
    p.text(500, 560, "Packed By", size=8.7, right=True)
    p.text(500, 580, "Transport", size=8.7, right=True)
    p.save()


def annesha_new_with_status_box():
    p = Page(OUT / "annesha_new_status_box.pdf")
    p.text(25, 19, "SelfServe Order #135-85801119 (New)", bold=True, size=11.7)
    p.text(571, 19, "08/10/2026 - 02:08 PM", bold=True, size=11.7, right=True)
    for i, (value, label) in enumerate([("CLO", "TYPE"), ("PRIMARY", "PART TYPE"), ("2", "TOTAL PARTS"), ("AWAITED", "STATUS")]):
        cx = 85 + i * 142
        p.c.rect(cx - 70, H - 80, 140, 40)
        p.c.setFont("Helvetica-Bold", 14)
        p.c.drawCentredString(cx, H - 58, value)
        p.c.setFont("Helvetica", 8)
        p.c.drawCentredString(cx, H - 73, label)
    addr = ["Near Saraswati Mandir , Naragoria ,PO- Naragoria,", "Dist - Purulia,723133", "Raghunathpur 723133 West Bengal"]
    p.block(25, 92, "Billing Address", ["Annesha Solutions", *addr, "GSTIN: N/A"])
    p.block(266, 92, "Shipping Address", ["Chinmay Sinha", *addr, "Contact: 9939198875 / anneshasolutions@gmail.com"])
    p.block(25, 170, "Seller GST Details", SELLER)
    p.block(266, 170, "Agent / DropShipper / Reseller",
            ["Chinmay Sinha (114982)", "Contact: 9939198875 / anneshasolutions@gmail.com"])
    p.table_header(245)
    p.item(263, "whl135_5027e_custom_print_level5", ["Weight: 10 x 7 = 70 Gms", "HSN/SAC: 392410, Tax: GST 18%",
           "Location:"], "15.00", "25.00", "7", "105.00")
    p.item(330, "whl205_79509_stainless_steel_cassrole", ["Weight: 500 x 7 = 3500 Gms", "HSN/SAC: 732310, Tax: GST 05%",
           "Location: A001"], "273.60", "304.00", "7", "1915.20")
    p.save()


def riya_processing():
    p = Page(OUT / "riya_marketing_processing.pdf")
    p.text(25, 19, "SelfServe Order #135-56931055 (Processing)", bold=True, size=11.7)
    p.text(571, 19, "09/10/2026 - 01:48 PM", bold=True, size=11.7, right=True)
    addr = ["D-501, SOLARIS-2, VASNA-BHAYLI ROAD, BHAYLI,", "Vadodara, Gujarat", "Vadodara 391410 Gujarat"]
    p.block(25, 47, "Billing Address", ["RIYA MARKETING", *addr, "GSTIN: 24BGFPS9800N1ZW"])
    p.block(266, 47, "Shipping Address", ["Riya Marketing", *addr, "Contact: 9898363330 / riyamarketingbrd5@gmail.com"])
    p.block(25, 125, "Seller GST Details", SELLER)
    p.block(266, 125, "Agent / DropShipper / Reseller",
            ["Riya Marketing (123238)", "Contact: 9898363330 / riyamarketingbrd5@gmail.com"])
    p.table_header(200)
    p.item(218, "18721_premium_4in1_gift_set_combo", ["Weight: 1210 x 31 = 37510 Gms", "HSN/SAC: 732393, Tax: GST 18%",
           "Location: K023"], "488.32", None, "31", "15137.92")
    p.item(285, "whl135_5027d_custom_print_level4", ["Weight: 10 x 30 = 300 Gms", "HSN/SAC: 392410, Tax: GST 18%",
           "Location:"], "8.00", "6.81", "30", "240.00")
    p.label_value(355, "Executive", "Khushi Chudasama - Izzat (6358956676)")
    p.total(355, "SubTotal", "15377.90")
    p.save()


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    meet_papers_draft()
    annesha_new_with_status_box()
    riya_processing()
    print("Fixtures written to", OUT)
