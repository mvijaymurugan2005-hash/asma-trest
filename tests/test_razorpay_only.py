"""Tests for the Razorpay-only donation flow (old UPI QR flow removed). Run:  python tests/test_razorpay_only.py
Uses a throw-away DATA_DIR and a mocked Razorpay API: no real network, real database or money is touched."""

import os, sys, re, json, hmac, hashlib, sqlite3, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="asma-test-")
os.environ.update(
    DATA_DIR=TMP, DATABASE_URL="", SECRET_KEY="test-secret", BASE_URL="http://localhost:5000", ADMIN_USER="admin",
    ADMIN_PASSWORD="TestAdminPass123", PAYMENT_MODE="razorpay", RAZORPAY_KEY_ID="rzp_test_x",
    RAZORPAY_KEY_SECRET="sekret", RAZORPAY_WEBHOOK_SECRET="whsec", SMTP_HOST="", SMTP_USER="", SMTP_PASS="",
)
# an OLD database with a verified UPI QR donation and a pending one: history must survive untouched
os.makedirs(os.path.join(TMP, "database"), exist_ok=True)
c = sqlite3.connect(os.path.join(TMP, "database", "asma.db"))
c.executescript(
    """create table donations(id integer primary key, ref text unique, name text, mobile text, email text, amount integer, message text, status text, order_id text, payment_id text, created text,
 address text default '', pan text default '', mode text, method text default '', paid_at text default '', channel text default '', utr text default '', screenshot text default '', verified_by text default '');
insert into donations(ref,name,mobile,email,amount,status,payment_id,created,address,mode,method,paid_at,channel,utr,verified_by) values
('DUPI1','Old UPI Donor','9876543210','old@example.org',2500,'paid','412345678901','2026-01-05 10:00','Old address, Chennai 600001','live','upi_qr','2026-01-05','upi_qr','412345678901','admin'),
('DUPI2','Pending UPI Donor','9876543211','p@example.org',500,'pending','','2026-02-05 10:00','Old address, Chennai 600001','live','upi_qr','','upi_qr','412345678902','');"""
)
c.commit(); c.close()
import backend.app as A

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  PASS  " + name)
    else: FAIL += 1; print("  FAIL  " + name, extra)

def dbrow(sql, a=()):
    c = sqlite3.connect(os.path.join(TMP, "database", "asma.db")); c.row_factory = sqlite3.Row
    r = c.execute(sql, a).fetchone(); c.close(); return r

ORDERS = []
def fake_rzp(path, payload):
    ORDERS.append(payload); return {"id": "order_T%d" % len(ORDERS)}
PAYS = {}
A.rzp = fake_rzp
A.rzp_get = lambda path: PAYS[path.split("/")[-1]]

def client():
    cl = A.app.test_client(); cl.get("/donate")
    with cl.session_transaction() as s: tok = s["_c"]
    return cl, tok

BODY = dict(name="Test Donor", mobile="9876501234", email="d@example.org",
            address="12 Main Street, Vengikkal, Tiruvannamalai 606604", pan="", amount=1500, message="")

print("\n[1] Donate page has no QR / UTR / screenshot")
cl, tok = client()
page = cl.get("/donate").get_data(as_text=True)
js = open(os.path.join(ROOT, "frontend/static/donate.js"), encoding="utf-8").read()
for bad in ("kotak", "upi-qr", "UTR", "screenshot", "I HAVE COMPLETED PAYMENT", "Copy UPI ID", "Download QR", 'id="upi"'):
    check("page has no '%s'" % bad, bad.lower() not in page.lower())
check("Razorpay donate button present", 'id="bo"' in page and "Donate Now" in page and "not available right now" not in page)
check("donate.js has no UPI/UTR code", not re.search(r"utr|upi/submit|showUpi|screenshot", js, re.I))
check("QR image file deleted from static", not os.path.exists(os.path.join(ROOT, "frontend/static/img/kotak-upi-qr.png")))

print("\n[2] Server side")
r = cl.post("/api/upi/submit", data={"ref": "DUPI2", "utr": "412345678902", "_csrf": tok})
check("/api/upi/submit no longer exists", r.status_code in (404, 405))
r = cl.post("/api/donate", json=dict(BODY, channel="upi_qr"), headers={"X-CSRF": tok})
j = r.get_json()
check("channel=upi_qr request is ignored: Razorpay order created", r.status_code == 200 and j["mode"] == "online" and j["order_id"].startswith("order_T"))
row = dbrow("select * from donations where ref=?", (j["ref"],))
check("donation saved as created/razorpay with order id", row["status"] == "created" and row["channel"] == "razorpay" and row["order_id"] == j["order_id"])
check("order amount comes from server in paise", ORDERS[-1]["amount"] == 150000 and ORDERS[-1]["currency"] == "INR")
check("secret never returned to browser", "sekret" not in json.dumps(j) and "whsec" not in json.dumps(j))
r = cl.post("/api/donate", json=dict(BODY, amount=5), headers={"X-CSRF": tok})
check("amount below minimum rejected", r.status_code == 400)

print("\n[3] Payment verification (browser callback is only a hint)")
ref, oid = j["ref"], j["order_id"]
r = cl.post("/api/verify", json={"ref": ref, "razorpay_payment_id": "pay_X", "razorpay_signature": "bad"}, headers={"X-CSRF": tok})
check("bad signature -> not paid", r.status_code == 400 and dbrow("select status from donations where ref=?", (ref,))["status"] != "paid")
cl2, tok2 = client()
j2 = cl2.post("/api/donate", json=BODY, headers={"X-CSRF": tok2}).get_json()
ref2, oid2 = j2["ref"], j2["order_id"]
sig = hmac.new(b"sekret", ("%s|%s" % (oid2, "pay_OK")).encode(), hashlib.sha256).hexdigest()
PAYS["pay_OK"] = {"order_id": oid2, "amount": 149900, "status": "captured", "method": "upi"}
r = cl2.post("/api/verify", json={"ref": ref2, "razorpay_payment_id": "pay_OK", "razorpay_signature": sig}, headers={"X-CSRF": tok2})
check("wrong amount at Razorpay -> not paid", r.status_code == 400 and dbrow("select status from donations where ref=?", (ref2,))["status"] != "paid")
PAYS["pay_OK"]["amount"] = 150000
r = cl2.post("/api/verify", json={"ref": ref2, "razorpay_payment_id": "pay_OK", "razorpay_signature": sig}, headers={"X-CSRF": tok2})
d = dbrow("select * from donations where ref=?", (ref2,))
check("valid signature + matching captured payment -> paid", r.status_code == 200 and d["status"] == "paid" and d["payment_id"] == "pay_OK")
n1 = dbrow("select count(*) c from certificates where donation_id=?", (d["id"],))["c"]
receipt_html = cl2.get("/receipt/" + ref2).get_data(as_text=True)
check("receipt immediately shows PAYMENT COMPLETED + Download button (no admin verify)", "PAYMENT COMPLETED!" in receipt_html and "DOWNLOAD DONATION CERTIFICATE" in receipt_html and "Verified automatically" in receipt_html)
cert_num = dbrow("select number from certificates where donation_id=?", (d["id"],))["number"]
dl_resp = cl2.get("/certificate/%s.pdf?dl=1" % cert_num)
check("donor can immediately download certificate PDF", dl_resp.status_code == 200 and dl_resp.data[:4] == b"%PDF")
r = cl2.post("/api/verify", json={"ref": ref2, "razorpay_payment_id": "pay_OK", "razorpay_signature": sig}, headers={"X-CSRF": tok2})
check("repeat verify -> still exactly one receipt", n1 == 1 and dbrow("select count(*) c from certificates where donation_id=?", (d["id"],))["c"] == 1)

print("\n[4] Webhook")
def hook(ev, secret=b"whsec"):
    body = json.dumps(ev).encode()
    return cl.post("/webhook/razorpay", data=body, headers={"X-Razorpay-Signature": hmac.new(secret, body, hashlib.sha256).hexdigest(), "Content-Type": "application/json"})
cl3, tok3 = client()
j3 = cl3.post("/api/donate", json=BODY, headers={"X-CSRF": tok3}).get_json()
ev = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_W1", "order_id": j3["order_id"], "amount": 150000, "status": "captured", "method": "card"}}}}
body = json.dumps(ev).encode()
check("webhook with wrong signature rejected", cl.post("/webhook/razorpay", data=body, headers={"X-Razorpay-Signature": "x"}).status_code == 400)
check("webhook accepted", hook(ev).status_code == 200)
check("webhook marks paid", dbrow("select status from donations where ref=?", (j3["ref"],))["status"] == "paid")
hook(ev)
check("repeated webhook -> one receipt only", dbrow("select count(*) c from certificates c join donations d on d.id=c.donation_id where d.ref=?", (j3["ref"],))["c"] == 1)
j4 = cl3.post("/api/donate", json=BODY, headers={"X-CSRF": tok3}).get_json()
ev2 = json.loads(json.dumps(ev)); ev2["payload"]["payment"]["entity"].update(id="pay_W2", order_id=j4["order_id"], amount=100)
hook(ev2)
check("webhook with wrong amount -> not paid", dbrow("select status from donations where ref=?", (j4["ref"],))["status"] != "paid")

print("\n[5] Historical UPI QR records are preserved")
h = dbrow("select * from donations where ref='DUPI1'")
check("old paid UPI donation intact (UTR, verifier, amount)", h["status"] == "paid" and h["utr"] == "412345678901" and h["verified_by"] == "admin" and h["amount"] == 2500)
a = A.app.test_client(); a.get("/admin/login")
with a.session_transaction() as s: t = s["_c"]
a.post("/admin/login", data={"username": "admin", "password": "TestAdminPass123", "_csrf": t})
a.get("/admin")
with a.session_transaction() as s2: t = s2["_c"]
check("admin login works", "aid" in s2)
check("admin can still open historical UPI donation", a.get("/admin/donations/%d" % h["id"]).status_code == 200)
check("admin list shows historical UPI rows", "Old UPI Donor" in a.get("/admin/donations?channel=upi_qr").get_data(as_text=True))
check("old pending UPI donation still verifiable via admin route", a.post("/admin/donations/%d/upi-reject" % dbrow("select id from donations where ref='DUPI2'")["id"], data={"reason": "not credited", "_csrf": t}).status_code in (302, 303) and dbrow("select status from donations where ref='DUPI2'")["status"] == "rejected")

print("\n[6] Razorpay not configured")
os.environ["RAZORPAY_KEY_ID"] = ""
cl9, tok9 = client()
r = cl9.post("/api/donate", json=BODY, headers={"X-CSRF": tok9})
check("no keys -> clear 'not configured' error, nothing saved", r.status_code == 503 and "not configured" in r.get_json()["error"])
check("donate page still shows Donate Now button (never 'not available')", "Donate Now" in cl9.get("/donate").get_data(as_text=True) and "not available right now" not in cl9.get("/donate").get_data(as_text=True))

print("\nRESULT: %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
