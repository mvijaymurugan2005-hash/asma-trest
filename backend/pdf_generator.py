"""Donation receipt numbering and premium PDF generation (ReportLab)."""

import os, sqlite3, secrets, threading
from datetime import datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .config import ROOT, UP, CERTS, now, fy_label, mask_pan
from .database import q, ex, db, settings, IntegrityError
from .qr_verification import verify_url, draw_qr
from .email_service import email_cert

NAVY, BLUE, GOLD = (
    colors.HexColor("#072a68"),
    colors.HexColor("#0b3a8c"),
    colors.HexColor("#c9971c"),
)
STATIC = os.path.join(ROOT, "frontend", "static")
METHODS = {
    "upi_qr": "UPI (Trust QR - Kotak Mahindra Bank)",
    "upi": "UPI",
    "card": "Card",
    "netbanking": "Net Banking",
    "wallet": "Wallet",
    "emi": "EMI",
    "paylater": "Pay Later",
}
ONES = "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen".split()
TENS = "x x Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _below100(n):
    return ONES[n] if n < 20 else TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else "")


def _below1000(n):
    return (
        (ONES[n // 100] + " Hundred" + (" and " + _below100(n % 100) if n % 100 else ""))
        if n >= 100
        else _below100(n)
    )


def words(n):
    """Indian numbering system (Lakh / Crore)."""
    n = int(n)
    if n == 0:
        return "Zero"
    out = []
    for div, name in ((10**7, "Crore"), (10**5, "Lakh"), (1000, "Thousand")):
        if n >= div:
            out.append(_below100(n // div) + " " + name)
            n %= div
    if n:
        out.append(_below1000(n))
    return " ".join(out)


def method_label(don):
    if (don["mode"] or "live") == "test":
        return "Test payment (simulated)"
    if (don["channel"] or "") == "upi_qr":
        return METHODS["upi_qr"]
    return METHODS.get((don["method"] or "").lower(), "Online (Razorpay)")


_fonts = {}


def uni_font(text):
    """Helvetica for Latin text; a Unicode TTF (Noto / Nirmala / DejaVu) for Tamil or other scripts if one can be found."""
    try:
        text.encode("latin-1")
        return None
    except UnicodeEncodeError:
        pass
    for p in (
        os.path.join(STATIC, "fonts", "NotoSans-Regular.ttf"),
        r"C:\Windows\Fonts\Nirmala.ttf",
        r"C:\Windows\Fonts\arialuni.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(p):
            if p not in _fonts:
                try:
                    pdfmetrics.registerFont(TTFont("U%d" % len(_fonts), p))
                    _fonts[p] = "U%d" % (len(_fonts))
                except Exception:
                    _fonts[p] = None
            if _fonts[p]:
                return _fonts[p]
    return None


def fit(c, text, font, size, maxw, minsize=9):
    while size > minsize and pdfmetrics.stringWidth(text, font, size) > maxw:
        size -= 0.5
    return size


def _img(setting_key, default):
    S = settings()
    p = os.path.join(UP, S.get(setting_key) or "") if S.get(setting_key) else ""
    return p if p and os.path.isfile(p) else os.path.join(STATIC, "img", default)


def issue_certificate(did):
    """Creates the receipt record + PDF exactly once per paid donation (idempotent, safe under concurrent calls)."""

    def existing():
        return q("select * from certificates where donation_id=?", (did,), one=True)

    if existing():
        return existing()
    don = q("select * from donations where id=?", (did,), one=True)
    if not don or don["status"] != "paid":
        return None
    try:
        fy = fy_label(datetime.strptime((don["paid_at"] or "")[:10], "%Y-%m-%d"))
    except ValueError:
        fy = fy_label()
    mode, row = don["mode"] or "live", None
    for _ in range(6):
        seq = q(
            "select coalesce(max(seq),0)+1 n from certificates where fy=? and mode=?",
            (fy, mode),
            one=True,
        )["n"]
        num = ("TEST-" if mode == "test" else "") + "ASMA-%s-%06d-%s" % (
            fy,
            seq,
            secrets.token_hex(2).upper(),
        )
        try:
            ex(
                "insert into certificates(number,donation_id,issued,seq,fy,mode) values(?,?,?,?,?,?)",
                (num, did, now(), seq, fy, mode),
            )
            break
        except IntegrityError:
            db().rollback()
            if existing():
                return existing()  # another request already issued it
    else:
        raise RuntimeError("Could not allocate a receipt number")
    make_pdf(num, don)
    send_in_background(num, dict(don))
    return q("select * from certificates where donation_id=?", (did,), one=True)


def send_in_background(num, don):
    """Email the receipt without making the donor wait for SMTP."""
    from flask import current_app

    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                email_cert(num, don)
            except Exception as e:
                ex("update certificates set email_error=? where number=?", (str(e)[:200], num))
                print("Receipt email failed:", e)

    threading.Thread(target=run, daemon=True).start()


def make_pdf(num, don):
    S = settings()
    W, H = landscape(A4)
    F, FB = "Helvetica", "Helvetica-Bold"
    test = (don["mode"] or "live") == "test"
    c = canvas.Canvas(os.path.join(CERTS, os.path.basename(num) + ".pdf"), pagesize=(W, H))
    c.setTitle("Donation Receipt " + num)
    c.setAuthor(S["trust_name"])
    # borders
    c.setStrokeColor(NAVY)
    c.setLineWidth(6)
    c.rect(20, 20, W - 40, H - 40)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.6)
    c.rect(32, 32, W - 64, H - 64)
    # header: logo, trust name
    lp = (
        os.path.join(UP, S["logo"])
        if S["logo"] and os.path.isfile(os.path.join(UP, S["logo"]))
        else os.path.join(STATIC, "img", "asma-logo.png")
    )
    c.drawImage(lp, W / 2 - 29, H - 102, 58, 58, preserveAspectRatio=True, mask="auto")
    c.setFillColor(NAVY)
    c.setFont(FB, 22)
    c.drawCentredString(W / 2, H - 122, S["trust_name"].upper())
    c.setFillColor(BLUE)
    c.setFont(FB, 9)
    c.drawCentredString(W / 2, H - 137, S["receipt_place"])
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.4)
    c.line(60, H - 146, W - 60, H - 146)
    c.setFillColor(GOLD)
    c.setFont(FB, 24)
    c.drawCentredString(W / 2, H - 176, "DONATION RECEIPT")
    c.setFillColor(colors.HexColor("#5b6b86"))
    c.setFont(F, 9.5)
    c.drawCentredString(W / 2, H - 190, "(Donation Acknowledgement)")
    c.setFont(F, 11)
    c.drawCentredString(W / 2, H - 212, "This receipt is presented with gratitude to")
    # donor
    nm = don["name"]
    nf = uni_font(nm) or FB
    sz = fit(c, nm, nf, 26, W - 180, 13)
    c.setFillColor(NAVY)
    c.setFont(nf, sz)
    c.drawCentredString(W / 2, H - 238, nm)
    c.setStrokeColor(colors.HexColor("#9fb2d3"))
    c.setLineWidth(0.8)
    c.line(W / 2 - 230, H - 245, W / 2 + 230, H - 245)
    addr = " ".join((don["address"] or "").split())
    af = uni_font(addr) or F
    if addr:
        c.setFillColor(colors.HexColor("#44506b"))
        for asz in (9, 8, 7.2, 6.4):  # long addresses shrink to fit two lines - never cut off
            lines = simpleSplit("Address: " + addr, af, asz, W - 220)
            if len(lines) <= 2:
                break
        c.setFont(af, asz)
        for i, ln in enumerate(lines[:2]):
            c.drawCentredString(W / 2, H - 258 - i * 11, ln)
    amt = "INR {:,.2f}".format(don["amount"])
    c.setFillColor(colors.HexColor("#1d2b4a"))
    c.setFont(F, 11.5)
    for i, ln in enumerate(
        simpleSplit(
            "The Trust gratefully acknowledges the donation of %s (Rupees %s Only) towards its charitable and educational objectives."
            % (amt, words(don["amount"])),
            F,
            11.5,
            W - 170,
        )
    ):
        c.drawCentredString(W / 2, H - 290 - i * 14, ln)
    # details table
    paid_on = (don["paid_at"] or don["created"] or "")[:10]
    try:
        paid_on = datetime.strptime(paid_on, "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        pass
    pan_lbl, pan_val = (
        ("Donor PAN", mask_pan(don["pan"])) if don["pan"] else ("Donor Mobile", don["mobile"] or "-")
    )
    rows = [
        ("Receipt No.", num, "Donation Date", paid_on),
        ("Payment Mode", method_label(don), "Transaction ID", don["payment_id"] or "-"),
        (pan_lbl, pan_val, "Reference No.", don["ref"]),
    ]
    cw = [96, 168, 100, 156]
    x0 = (W - sum(cw)) / 2
    top = H - 318
    rh = 24
    c.setFillColor(colors.HexColor("#f4f8ff"))
    c.setStrokeColor(colors.HexColor("#d5e0f3"))
    c.setLineWidth(0.8)
    c.rect(x0, top - rh * 3, sum(cw), rh * 3, fill=1, stroke=1)
    for i, r in enumerate(rows):
        y = top - rh * (i + 1)
        if i:
            c.line(x0, y + rh, x0 + sum(cw), y + rh)
        x = x0
        for j, v in enumerate(r):
            if j % 2 == 0:
                c.setFillColor(NAVY)
                f = FB
                s = 9
            else:
                c.setFillColor(colors.HexColor("#1d2b4a"))
                f = F
                s = fit(c, v, F, 9.5, cw[j] - 12, 6.5)
            c.setFont(f, s)
            c.drawString(x + 8, y + 8.5, v)
            x += cw[j]
    c.line(x0 + cw[0], top, x0 + cw[0], top - rh * 3)
    c.line(x0 + cw[0] + cw[1], top, x0 + cw[0] + cw[1], top - rh * 3)
    c.line(x0 + cw[0] + cw[1] + cw[2], top, x0 + cw[0] + cw[1] + cw[2], top - rh * 3)
    # QR | signature | seal
    url = verify_url(num)
    draw_qr(c, url, 70, 114, 78)
    c.setFillColor(colors.HexColor("#5b6b86"))
    c.setFont(F, 7.5)
    c.drawCentredString(109, 104, "Scan to verify this receipt online")
    sig = _img("signature_img", "signature.png")
    c.drawImage(sig, W / 2 - 62, 134, 124, 32, preserveAspectRatio=True, mask="auto")
    c.setStrokeColor(colors.HexColor("#44506b"))
    c.setLineWidth(0.8)
    c.line(W / 2 - 100, 131, W / 2 + 100, 131)
    c.setFillColor(NAVY)
    c.setFont(FB, 9)
    c.drawCentredString(W / 2, 120, S["signatory_title"] or "Authorised Signatory")
    c.setFillColor(colors.HexColor("#44506b"))
    c.setFont(F, 8)
    y = 110
    if S["signatory"] and not S["signatory"].startswith("["):
        c.drawCentredString(W / 2, y, S["signatory"])
        y -= 10
    c.drawCentredString(W / 2, y, S["trust_name"])
    seal = _img("seal_img", "seal.png")
    c.drawImage(seal, W - 160, 112, 82, 80, preserveAspectRatio=True, mask="auto")
    c.setFillColor(NAVY)
    c.setFont(FB, 9)
    c.drawCentredString(W - 119, 100, "Trust Seal")
    # footer
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.line(60, 94, W - 60, 94)
    c.setFillColor(colors.HexColor("#44506b"))
    c.setFont(FB, 7.6)
    c.drawCentredString(W / 2, 83, "Registered / Administrative Address: " + S["reg_address"])
    c.drawCentredString(
        W / 2,
        73,
        "PAN: %s   |   DARPAN ID: %s   |   Trust Registration No.: %s"
        % (S["pan"], S["darpan"], S["reg_no"]),
    )
    c.drawCentredString(
        W / 2, 63, "Email: %s   |   Phone: %s" % (S["receipt_email"], S["receipt_phone"])
    )
    c.setFillColor(colors.HexColor("#6b7893"))
    c.setFont(F, 6.8)
    for i, ln in enumerate(
        simpleSplit(
            "This is a donation receipt / acknowledgement only. It is NOT the statutory Form 10BE certificate under section 80G of the Income-tax Act and does not by itself entitle the donor to any tax deduction. "
            "Any 80G benefit depends on the Trust's verification, the donor's eligibility and official Form 10BD / Form 10BE processing on the Income Tax portal.",
            F,
            6.8,
            W - 150,
        )
    ):
        c.drawCentredString(W / 2, 54 - i * 7.5, ln)
    c.drawCentredString(W / 2, 38.5, "Verify: " + url)
    if test:
        c.saveState()
        c.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.13))
        c.setFont(FB, 62)
        c.translate(W / 2, H / 2 - 10)
        c.rotate(24)
        c.drawCentredString(0, 0, "TEST RECEIPT")
        c.setFont(FB, 26)
        c.drawCentredString(0, -40, "NOT VALID - NO REAL PAYMENT")
        c.restoreState()
    c.save()
