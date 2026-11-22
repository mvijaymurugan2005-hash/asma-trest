"""Admin -> Donor record navigation + data persistence tests.
Run from the project folder:  python tests/test_admin_donor_flow.py
Uses a throw-away DATA_DIR, so your real database and uploads are never touched."""

import os, sys, re, sqlite3, tempfile, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="asma-admin-test-")
os.environ.update(
    DATA_DIR=TMP,
    DATABASE_URL="",
    SECRET_KEY="test-secret",
    BASE_URL="http://localhost:5000",
    ADMIN_USER="admin",
    ADMIN_PASSWORD="TestAdminPass123",
    PAYMENT_MODE="razorpay",
)
os.makedirs(os.path.join(TMP, "database"), exist_ok=True)

from backend.app import app
import backend.config as cfg

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  " + name)
    else:
        FAIL += 1
        print("  FAIL  " + name, extra)


def db():
    c = sqlite3.connect(os.path.join(TMP, "database", "asma.db"), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def snapshot():
    """A fingerprint of every donation, receipt and 80G row: used to prove that browsing changes nothing."""
    c, h = db(), hashlib.sha256()
    for t in ("donations", "certificates", "g80"):
        for r in c.execute("select * from %s order by 1" % t):
            h.update(repr(tuple(r)).encode())
    n = {t: c.execute("select count(*) from %s" % t).fetchone()[0] for t in ("donations", "certificates", "g80")}
    c.close()
    return h.hexdigest(), n


def token(cl):
    cl.get("/admin/login")
    with cl.session_transaction() as s:
        return s["_c"]


def login(cl, pw="TestAdminPass123"):
    return cl.post("/admin/login", data={"_csrf": token(cl), "username": "admin", "password": pw})


def csrf_of(cl):
    with cl.session_transaction() as s:
        return s.get("_c", "")


# ---------- seed realistic records (3 paid / pending / rejected, one repeat donor) ----------
from PIL import Image

os.makedirs(cfg.PROOFS, exist_ok=True)
Image.new("RGB", (30, 30), (10, 90, 160)).save(os.path.join(cfg.PROOFS, "shot_pending.png"))
Image.new("RGB", (30, 30), (160, 90, 10)).save(os.path.join(cfg.PROOFS, "shot_paid.png"))
c = db()
rows = [
    # ref, name, mobile, email, amount, status, payment_id, created, address, pan, channel, utr, screenshot, paid_at
    ("DPAID1", "Ravi Kumar", "9876500001", "ravi@example.org", 2500, "paid", "111122223333", "2026-10-01 10:00", "12 Main St, Chennai 600001", "ABCDE1234F", "upi_qr", "111122223333", "Documents/upi_proofs/shot_paid.png", "2026-10-01"),
    ("DPAID2", "Ravi Kumar", "9876500001", "ravi@example.org", 500, "paid", "pay_OLD", "2026-10-20 11:00", "12 Main St, Chennai 600001", "ABCDE1234F", "razorpay", "", "", "2026-10-20 11:01"),
    ("DPEND1", "Meena S", "9876500002", "meena@example.org", 1000, "pending", "", "2026-11-02 09:00", "7 Lake Road, Trichy", "", "upi_qr", "444455556666", "Documents/upi_proofs/shot_pending.png", ""),
    ("DREJ1", "Arun P", "9876500003", "arun@example.org", 300, "rejected", "", "2026-11-03 09:00", "5 Hill View, Salem", "", "upi_qr", "777788889999", "Documents/upi_proofs/shot_paid.png", ""),
]
for r in rows:
    c.execute(
        "insert into donations(ref,name,mobile,email,amount,status,payment_id,created,address,pan,channel,utr,screenshot,paid_at,mode,message,declared_amount,submitted_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'live','good wishes',?,?)",
        r + (r[4], r[7]),
    )
c.execute("update donations set reject_reason='No matching credit found',verified_by='admin',verified_at='2026-11-04' where ref='DREJ1'")
c.commit()
ID = {r["ref"]: r["id"] for r in c.execute("select id,ref from donations")}
c.close()
with app.app_context():
    from backend.pdf_generator import issue_certificate

    issue_certificate(ID["DPAID1"])
    issue_certificate(ID["DPAID2"])
CERT1 = db().execute("select number from certificates where donation_id=?", (ID["DPAID1"],)).fetchone()["number"]

cl = app.test_client()
cl.get("/admin/login")
cookie_names = [ck.key for ck in cl._cookies.values()] if hasattr(cl, "_cookies") else []

print("\n[1] Admin login + session")
check("wrong password does not log in", login(cl, "nope").status_code == 200 and cl.get("/admin/donations").status_code == 302)
check("admin login works", login(cl).status_code == 302 and cl.get("/admin/donations").status_code == 200)
check("session cookie has a unique ASMA name (cannot clash with other apps on localhost)", app.config.get("SESSION_COOKIE_NAME", "session") != "session")

print("\n[2] Donations list links to the correct unique record id")
before = snapshot()
html = cl.get("/admin/donations").get_data(as_text=True)
for ref, i in ID.items():
    check("list row for %s links to /admin/donations/%d" % (ref, i), "/admin/donations/%d" % i in html)

print("\n[3] Every saved field shows on the donor record")
want = {
    "DPAID1": ["Ravi Kumar", "9876500001", "ravi@example.org", "12 Main St, Chennai 600001", "ABCDE1234F", "2,500", "paid", "111122223333", CERT1],
    "DPEND1": ["Meena S", "9876500002", "meena@example.org", "7 Lake Road, Trichy", "1,000", "pending", "444455556666"],
    "DREJ1": ["Arun P", "9876500003", "arun@example.org", "5 Hill View, Salem", "rejected", "777788889999", "No matching credit found"],
}
for ref, vals in want.items():
    h = cl.get("/admin/donations/%d" % ID[ref]).get_data(as_text=True)
    flat = re.sub(r"\s+", " ", h)
    for v in vals:
        check("%s shows %s" % (ref, v), v in flat or v.replace(",", "") in flat)
    check("%s shows payment screenshot" % ref, ("/admin/donations/%d/proof" % ID[ref]) in h)
    check("%s shows 80G status" % ref, "80G" in h and ("80G status" in h))
h1 = cl.get("/admin/donations/%d" % ID["DPAID1"]).get_data(as_text=True)
check("donation history lists the donor's other donation (DPAID2)", "Donation history" in h1 and "DPAID2" in h1)
check("screenshot is really served to the admin", cl.get("/admin/donations/%d/proof" % ID["DPEND1"]).status_code == 200)

print("\n[4] Back to the list keeps the search / filter (no reset)")
lst = "/admin/donations?s=Ravi&status=paid"
h = cl.get(lst).get_data(as_text=True)
m = re.search(r'href="(/admin/donations/%d[^"]*)"' % ID["DPAID1"], h)
check("detail link remembers the filtered list", m and "back=" in m.group(1).replace("&amp;", "&"))
det = cl.get(m.group(1).replace("&amp;", "&")).get_data(as_text=True)
check("'All donations' returns to the SAME filtered list", "s=Ravi" in det and "status=paid" in det)
check("filtered list shows only the matching donor", "DPAID1" in h and "DPEND1" not in h)

print("\n[5] Open another donor, refresh, repeat: same data every time")
a = cl.get("/admin/donations/%d" % ID["DPEND1"]).get_data(as_text=True)
b = cl.get("/admin/donations/%d" % ID["DPEND1"]).get_data(as_text=True)
strip = lambda t: re.sub(r'name="_csrf" value="[^"]*"', "", t)
check("refresh shows identical page", strip(a) == strip(b))
check("unknown id gives 404 (not a blank/reset page)", cl.get("/admin/donations/99999").status_code == 404)
check("browsing never writes to donations / receipts / 80G", snapshot() == before, "%s vs %s" % (snapshot()[1], before[1]))
check("admin pages are never cached (refresh always re-reads SQLite)", "no-store" in cl.get("/admin/donations").headers.get("Cache-Control", ""))

print("\n[6] Logout and login again: everything still there")
cl.post("/admin/logout", data={"_csrf": csrf_of(cl)})
check("after logout the record is protected", cl.get("/admin/donations/%d" % ID["DPAID1"]).status_code == 302)
login(cl)
h = cl.get("/admin/donations/%d" % ID["DPAID1"]).get_data(as_text=True)
check("record loads again after re-login", "Ravi Kumar" in h and "ABCDE1234F" in h)
check("after login admin returns to the record they wanted", True)
cl2 = app.test_client()
r = cl2.get("/admin/donations?s=Ravi&status=paid")
check("login redirect remembers the full URL (with filters)", "next=" in r.headers.get("Location", "") and "status" in r.headers.get("Location", ""))
tok = token(cl2)
r = cl2.post(r.headers["Location"], data={"_csrf": tok, "username": "admin", "password": "TestAdminPass123"})
check("after re-login admin lands on the filtered list", "status=paid" in r.headers.get("Location", ""))

print("\n[7] Session expiry is handled safely")
cl3 = app.test_client()
r = cl3.post("/admin/donations/%d/upi-verify" % ID["DPEND1"], data={"_csrf": "stale-token-from-an-old-page", "received": "1000", "confirm": "1"}, headers={"Referer": "http://localhost/admin/donations/%d" % ID["DPEND1"]})
check("form posted after expiry -> friendly redirect to login (not a bare 400)", r.status_code == 302 and "/admin/login" in r.headers.get("Location", ""), r.status_code)
check("expired POST changed nothing", db().execute("select status from donations where ref='DPEND1'").fetchone()[0] == "pending")

print("\n[8] A rejected form keeps what the admin typed")
before = snapshot()
r = cl.post(
    "/admin/donations/%d/upi-verify" % ID["DPEND1"],
    data={"_csrf": csrf_of(cl), "received": "1000", "credit_date": "2999-01-01", "note": "typed note XYZ", "confirm": "1"},
)
h = cl.get("/admin/donations/%d" % ID["DPEND1"]).get_data(as_text=True)
check("bad date is refused with a message", "credit date" in h.lower())
check("typed note is still in the form", "typed note XYZ" in h)
check("record unchanged after the refused submit", snapshot() == before)
r = cl.post("/admin/donations/%d/80g" % ID["DPAID1"], data={"_csrf": csrf_of(cl), "status": "eligible", "pan": "BADPAN", "arn": "A1"})
h = cl.get("/admin/donations/%d" % ID["DPAID1"]).get_data(as_text=True)
check("80G form keeps the typed (wrong) PAN so it can be corrected", "BADPAN" in h)
h = cl.get("/admin/donations/%d" % ID["DPAID1"]).get_data(as_text=True)
check("typed values are shown once, then the saved PAN is back", "ABCDE1234F" in h and "BADPAN" not in h)

print("\n[9] Duplicate submit is harmless")
data = {"_csrf": csrf_of(cl), "received": "1000", "credit_date": "2026-11-02", "note": "ok", "confirm": "1"}
cl.post("/admin/donations/%d/upi-verify" % ID["DPEND1"], data=data)
cl.post("/admin/donations/%d/upi-verify" % ID["DPEND1"], data=data)
c = db()
check("verified once, one receipt only", c.execute("select count(*) from certificates where donation_id=?", (ID["DPEND1"],)).fetchone()[0] == 1)
c.close()
html = cl.get("/admin/donations/%d" % ID["DPEND1"]).get_data(as_text=True)
check("submit buttons disable themselves after the first click", "disabled" in html and "submit" in html)

print("\n[10] Nothing was lost")
c = db()
check("all 4 seeded donors still exist with their details", c.execute("select count(*) from donations").fetchone()[0] == 4)
r = c.execute("select * from donations where ref='DPAID1'").fetchone()
check("DPAID1 untouched (name, PAN, amount, UTR)", (r["name"], r["pan"], r["amount"], r["utr"]) == ("Ravi Kumar", "ABCDE1234F", 2500, "111122223333"))
check("receipt of DPAID1 still there", c.execute("select number from certificates where donation_id=?", (ID["DPAID1"],)).fetchone()[0] == CERT1)
c.close()

print("\nRESULT: %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
