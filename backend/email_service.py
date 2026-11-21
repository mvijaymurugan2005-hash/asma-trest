"""Sends donation receipts and official Form 10BE PDFs by email (SMTP)."""

import os, ssl, smtplib
from email.message import EmailMessage
from .config import E, CERTS, UP
from .database import ex, settings


def _ready():
    """True only when the e-mail settings in .env are complete (host, and password when a user name is set)."""
    return bool(E("SMTP_HOST")) and not (E("SMTP_USER") and not E("SMTP_PASS"))


def _send(m):
    h = E("SMTP_HOST")
    port = int(E("SMTP_PORT", "587"))
    with (
        smtplib.SMTP_SSL(h, port, timeout=25) if port == 465 else smtplib.SMTP(h, port, timeout=25)
    ) as s:
        if port != 465:
            s.starttls(context=ssl.create_default_context())
        if E("SMTP_USER"):
            s.login(E("SMTP_USER"), E("SMTP_PASS"))
        s.send_message(m)


def _base():
    return E("BASE_URL").rstrip("/") or "http://localhost:5000"


def email_cert(num, don):
    """Emails the donation receipt PDF. Returns False when SMTP is not configured."""
    if not _ready():
        return False
    S = settings()
    m = EmailMessage()
    m["Subject"] = "Donation Receipt %s - %s" % (num, S["trust_name"])
    m["From"] = E("MAIL_FROM") or E("SMTP_USER")
    m["To"] = don["email"]
    m.set_content(
        "Dear %s,\n\nThank you for your generous donation of INR %s to %s.\n\n"
        "Your donation receipt (No. %s) is attached to this email. You can also open it online at:\n%s/receipt/%s\n\n"
        "Important: this is a donation receipt / acknowledgement. It is not the official Form 10BE certificate under section 80G. "
        "You can check the 80G certificate status of your donation here:\n%s/80g/%s\n\n"
        "With gratitude,\n%s\n%s"
        % (
            don["name"],
            "{:,}".format(don["amount"]),
            S["trust_name"],
            num,
            _base(),
            don["ref"],
            _base(),
            don["ref"],
            S["trust_name"],
            S["receipt_email"],
        )
    )
    m.add_attachment(
        open(os.path.join(CERTS, os.path.basename(num) + ".pdf"), "rb").read(),
        maintype="application",
        subtype="pdf",
        filename=num + ".pdf",
    )
    _send(m)
    ex("update certificates set emailed=1, email_error='' where number=?", (num,))
    return True


def email_10be(don, path):
    """Emails an official Form 10BE PDF (uploaded by the Trust admin) to the donor."""
    if not _ready():
        return False
    S = settings()
    m = EmailMessage()
    m["Subject"] = "Form 10BE (80G) - %s" % S["trust_name"]
    m["From"] = E("MAIL_FROM") or E("SMTP_USER")
    m["To"] = don["email"]
    m.set_content(
        "Dear %s,\n\nAttached is the official Form 10BE issued for your donation (reference %s) by %s, after Form 10BD processing on the Income Tax portal.\n"
        "Any deduction is subject to the conditions of the Income-tax Act; please consult your tax advisor.\n\nWith gratitude,\n%s"
        % (don["name"], don["ref"], S["trust_name"], S["trust_name"])
    )
    m.add_attachment(
        open(path, "rb").read(),
        maintype="application",
        subtype="pdf",
        filename="Form10BE-%s.pdf" % don["ref"],
    )
    _send(m)
    return True
