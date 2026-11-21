"""QR code drawing and certificate lookup for the verification page."""

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from .config import E
from .database import q


def verify_url(num):
    return "%s/verify/%s" % (E("BASE_URL").rstrip("/") or "http://localhost:5000", num)


def draw_qr(c, url, x, y, sz=90):
    w = qr.QrCodeWidget(url)
    b = w.getBounds()
    d = Drawing(sz, sz, transform=[sz / (b[2] - b[0]), 0, 0, sz / (b[3] - b[1]), 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x, y)


def resolve(num):
    a = q("select new_number from cert_alias where old=?", (num,), one=True)
    return a["new_number"] if a else num


def lookup_certificate(num):
    num = resolve(num)
    return q(
        "select c.*,d.name,d.amount,d.created as paid_on,d.paid_at,d.mode as dmode from certificates c join donations d on d.id=c.donation_id where c.number=? and d.status='paid'",
        (num,),
        one=True,
    )
