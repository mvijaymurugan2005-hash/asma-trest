"""Donor status tracker + certificate download after admin verification.
Run from the project folder:  python tests/test_tracker.py   (throw-away database, your real data is never touched)"""

import os, sys, re, sqlite3, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="asma-track-test-")
os.environ.update(DATA_DIR=TMP, DATABASE_URL="", SECRET_KEY="test-secret", BASE_URL="http://localhost:5000",
                  ADMIN_USER="admin", ADMIN_PASSWORD="TestAdminPass123", PAYMENT_MODE="razorpay")
os.makedirs(os.path.join(TMP, "database"), exist_ok=True)
from backend.app import app

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(("  PASS  " if cond else "  FAIL  ") + name, "" if cond else extra)


def db():
    c = sqlite3.connect(os.path.join(TMP, "database", "asma.db"), timeout=10)
    c.row_factory = sqlite3.Row
    return c


c = db()
for ref, st, utr, mob in [("DCRE", "created", "", "9876500010"), ("DPEN", "pending", "555566667777", "9876500011"),
                          ("DREJ", "rejected", "888899990000", "9876500012")]:
    c.execute("insert into donations(ref,name,mobile,email,amount,status,created,address,pan,channel,utr,mode,submitted_at) values(?,?,?,?,?,?,?,?,?,'upi_qr',?,'live','2026-11-16 10:00')",
              (ref, "Donor " + ref, mob, ref.lower() + "@example.org", 100, st, "2026-11-16 10:00", "addr", "", utr))
c.execute("update donations set reject_reason='No credit found' where ref='DREJ'")
c.commit()
ID = {r["ref"]: r["id"] for r in c.execute("select id,ref from donations")}
c.close()
cl = app.test_client()
steps = lambda h: re.findall(r'<li class="(\w+)">', h.split('class="trk"', 1)[1].split("</ol>", 1)[0])
page = lambda ref: cl.get("/receipt/" + ref).get_data(as_text=True)

print("\n[1] Tracker shows the right step for every state")
check("not submitted yet: step 1 current", steps(page("DCRE")) == ["now", "todo", "todo", "todo"])
check("pending: submitted done, 'Trust is verifying' current", steps(page("DPEN")) == ["done", "now", "todo", "todo"])
check("rejected: step 3 shows 'Not verified' in red", steps(page("DREJ")) == ["done", "done", "bad", "todo"])
check("pending page polls the status automatically", "/api/status/" in page("DPEN") and "trkLive" in page("DPEN"))
check("pending page has NO download button", "DOWNLOAD DONATION CERTIFICATE" not in page("DPEN"))

print("\n[2] Admin verifies -> donor sees certificate + Download")
st = cl.get("/api/status/DPEN").get_json()
check("before verification: status pending, not ready", st["status"] == "pending" and not st["ready"])
a = app.test_client()
a.get("/admin/login")
with a.session_transaction() as s:
    tok = s["_c"]
a.post("/admin/login", data={"_csrf": tok, "username": "admin", "password": "TestAdminPass123"})
a.get("/admin/donations")  # renders a page, which creates the new CSRF token after login
with a.session_transaction() as s:
    tok = s["_c"]
r = a.post("/admin/donations/%d/upi-verify" % ID["DPEN"], data={"_csrf": tok, "received": "100", "credit_date": "2026-11-16", "confirm": "1"})
check("admin verify accepted", r.status_code == 302)
st = cl.get("/api/status/DPEN").get_json()
check("donor's status check now says paid + certificate ready", st["status"] == "paid" and st["ready"] and st["download"].endswith("dl=1"), st)
h = page("DPEN")
check("tracker: all 4 steps done", steps(h) == ["done", "done", "done", "done"])
check("Download button is right on the page", "DOWNLOAD DONATION CERTIFICATE" in h)
dl = cl.get(st["download"])
check("certificate downloads as a PDF attachment", dl.status_code == 200 and dl.data[:4] == b"%PDF" and "attachment" in dl.headers.get("Content-Disposition", ""))
check("donor menu (Home / Contact / Address / Certification) is there", all(x in h for x in ("Home", "Contact", "Address", "Certification")))

print("\n[3] Verified but certificate missing -> created automatically")
c = db()
c.execute("update donations set status='paid',paid_at='2026-11-16',verified_at='2026-11-16 11:00' where ref='DREJ'")
c.commit(); c.close()
check("tracker waits on step 4 while preparing", steps(page("DREJ"))[3] in ("now", "done"))
st = cl.get("/api/status/DREJ").get_json()
check("status check issues the missing certificate by itself", st["ready"] and st["download"], st)

print("\n[4] Track-donation page")
check("footer links to Track donation", "Track donation" in cl.get("/").get_data(as_text=True))
check("track page opens", cl.get("/track").status_code == 200)
cl.get("/track")
with cl.session_transaction() as s:
    tk = s["_c"]
r = cl.post("/track", data={"_csrf": tk, "ref": "dpen", "mobile": "+91 98765 00011"})
check("right reference + mobile -> opens the tracker page", r.status_code == 302 and r.headers["Location"].endswith("/receipt/DPEN"), r.headers.get("Location"))
r = cl.post("/track", data={"_csrf": tk, "ref": "555566667777", "mobile": "9876500011"})
check("UTR works instead of the reference", r.status_code == 302 and r.headers["Location"].endswith("/receipt/DPEN"))
r = cl.post("/track", data={"_csrf": tk, "ref": "DPEN", "mobile": "9999999999"})
check("wrong mobile -> not shown (privacy)", r.status_code == 200 and "No donation found" in r.get_data(as_text=True))
for _ in range(12):
    r = cl.post("/track", data={"_csrf": tk, "ref": "NOPE", "mobile": "9999999999"})
r = cl.post("/track", data={"_csrf": tk, "ref": "DPEN", "mobile": "9876500011"})
check("repeated wrong guesses are rate-limited", "Too many attempts" in r.get_data(as_text=True))

print("\nRESULT: %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
