"""Trust e-mail address is asmafoundation2025@gmail.com everywhere; old stored value is migrated; admin-typed value is kept."""
import os, sys, sqlite3, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="asma-email-test-")
os.environ.update(DATA_DIR=TMP, DATABASE_URL="", SECRET_KEY="t", BASE_URL="http://localhost:5000", ADMIN_PASSWORD="x", PAYMENT_MODE="razorpay",
                  SMTP_HOST="smtp.gmail.com", SMTP_USER="asmafoundation2025@gmail.com", SMTP_PASS="")
os.makedirs(os.path.join(TMP, "database"), exist_ok=True)
NEW, OLD = "asmafoundation2025@gmail.com", "chezhiyaninnovativeservicesprivatelimited@gmail.com"
P = F = 0
def check(n, c):
    global P, F
    P, F = (P + 1, F) if c else (P, F + 1); print(("  PASS  " if c else "  FAIL  ") + n)
from backend.app import app
from backend.database import init_db
from backend.config import DBP, DEFAULTS
import backend.email_service as es
cl = app.test_client()
for path in ("/", "/contact", "/donate", "/about"):
    h = cl.get(path).get_data(as_text=True)
    check("%s shows the new e-mail and not the old one" % path, NEW in h and OLD not in h)
check("receipt e-mail on certificates is the new one", DEFAULTS["receipt_email"] == NEW and DEFAULTS["email"] == NEW)
c = sqlite3.connect(DBP)
c.execute("insert or replace into settings(k,v) values('email',?)", (OLD,)); c.commit()
with app.app_context(): init_db()
check("old address stored in the database is migrated", c.execute("select v from settings where k='email'").fetchone()[0] == NEW)
c.execute("update settings set v='custom@trust.org' where k='email'"); c.commit()
with app.app_context(): init_db()
check("an address typed by the admin is never overwritten", c.execute("select v from settings where k='email'").fetchone()[0] == "custom@trust.org")
check("no App Password yet -> treated as 'not configured' (no failing SMTP login)", es._ready() is False)
os.environ["SMTP_PASS"] = "abcdabcdabcdabcd"
check("with App Password the e-mail is enabled", es._ready() is True)
print("\nRESULT: %d passed, %d failed" % (P, F)); sys.exit(1 if F else 0)
