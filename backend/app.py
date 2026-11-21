"""ASMA Educational and Charitable Trust - Flask application (routes)."""

import os, io, re, csv, json, hmac, time, uuid, sqlite3, zipfile, secrets, hashlib
from datetime import datetime
from urllib.parse import urlsplit
from flask import (
    Flask,
    g,
    request,
    session,
    redirect,
    url_for,
    render_template,
    flash,
    jsonify,
    abort,
    send_file,
    send_from_directory,
    Response,
    make_response,
)
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.security import generate_password_hash, check_password_hash
from .config import *
from .database import db, q, ex, settings, init_db, is_pg, db_summary
from .authentication import csrf, admin
from .uploads import save, rmfile
from .payment import rzp, rzp_get, valid_payment, valid_webhook
from .pdf_generator import issue_certificate, make_pdf
from .email_service import email_cert, email_10be
from .qr_verification import lookup_certificate, resolve

PAGES = os.path.join(ROOT, "frontend", "pages")
app = Flask(__name__, static_folder=os.path.join(ROOT, "frontend", "static"), template_folder=PAGES)
app.jinja_loader = ChoiceLoader(
    [FileSystemLoader(PAGES), FileSystemLoader(ROOT)]
)  # 'admin/x.html' -> ROOT/admin/x.html
app.config.update(
    SECRET_KEY=secret_key(),
    MAX_CONTENT_LENGTH=200 * 1024 * 1024,
    SESSION_COOKIE_NAME="asma_session",  # unique name: never clashes with another app running on localhost
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=E("BASE_URL").startswith("https"),
    PERMANENT_SESSION_LIFETIME=8 * 3600,
)
init_db()
try:  # tell the admin which database is in use
    print(db_summary())
except Exception:
    pass
ENT = {
    "banners": dict(
        folder="Banners",
        label="Home Banner",
        cols=["caption", "sort"],
        req="image",
        fields=[
            ("image", "Banner image", "image", None),
            ("caption", "Caption (optional)", "text", None),
            ("sort", "Order", "number", None),
        ],
    ),
    "activities": dict(
        folder="Activities",
        label="Activities",
        cols=["title", "sort"],
        req="title",
        fields=[
            ("title", "Title", "text", None),
            ("description", "Description", "textarea", None),
            ("image", "Image", "image", None),
            ("sort", "Order", "number", None),
        ],
    ),
    "projects": dict(
        folder="Projects",
        label="Projects",
        cols=["title", "category", "status", "published"],
        req="title",
        fields=[
            ("title", "Project title", "text", None),
            ("category", "Category", "select", CATS),
            ("short", "Short description", "textarea", None),
            ("full", "Full description", "textarea", None),
            ("main_image", "Main image", "image", None),
            ("images", "More images (multiple)", "images", None),
            ("video", "Video", "video", None),
            ("date", "Project date", "date", None),
            ("location", "Project location", "text", None),
            ("status", "Project status", "select", STATUSES),
            ("published", "Published (visible on website)", "check", None),
        ],
    ),
    "gallery": dict(
        folder="Gallery",
        label="Gallery",
        cols=["kind", "caption", "activity", "project"],
        req="file",
        fields=[
            ("file", "Photo or video", "media", None),
            ("caption", "Caption", "text", None),
            (
                "activity",
                "Activity (optional)",
                "select",
                lambda: [""]
                + [r["title"] for r in q("select title from activities order by sort,id")],
            ),
            (
                "project",
                "Project (optional) – type any name or pick from the list",
                "combo",
                lambda: [""]
                + [r["title"] for r in q("select title from projects order by id desc")],
            ),
        ],
    ),
    "trustees": dict(
        folder="Gallery",
        label="Trustees & Members",
        cols=["name", "role", "sort"],
        req="name",
        fields=[
            ("name", "Name", "text", None),
            ("role", "Role", "text", None),
            ("bio", "Details", "textarea", None),
            ("photo", "Photo", "image", None),
            ("sort", "Order", "number", None),
        ],
    ),
}


@app.teardown_appcontext
def _close(e):
    d = g.pop("db", None)
    if d:
        d.close()


app.jinja_env.globals["csrf"] = csrf


@app.before_request
def _guard():
    if request.method == "POST" and request.endpoint != "webhook":
        t = request.form.get("_csrf") or request.headers.get("X-CSRF") or ""
        if not hmac.compare_digest(t, session.get("_c", "")):
            if request.path.startswith("/admin") and not session.get("aid"):
                # session expired / cookie lost while a page was open: go to login and come back afterwards
                flash("Your session expired. Please log in again.", "err")
                ref = urlsplit(request.referrer or "")
                nxt = ref.path + ("?" + ref.query if ref.query else "")
                if request.endpoint == "login":
                    nxt = request.args.get("next", "")
                if nxt.startswith("/admin") and not nxt.startswith("/admin/login"):
                    return redirect(url_for("login", next=nxt))
                return redirect(url_for("login"))
            abort(400)


@app.after_request
def _hdr(r):
    if request.path.startswith("/admin"):
        r.headers["Cache-Control"] = "no-store"  # always re-read from SQLite; back button never shows stale / private data
    r.headers.update(
        {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        }
    )
    return r


def _css_ver():
    # changes whenever style.css is edited, so browsers never show an old cached stylesheet
    try:
        return int(os.path.getmtime(os.path.join(app.static_folder, "style.css")))
    except OSError:
        return 0


@app.context_processor
def _ctx():
    if hasattr(g, "_pend"):
        pend = g._pend
    elif session.get("aid") and request.path.startswith("/admin"):
        pend = q("select count(*) c from donations where status='pending'", one=True)["c"]
    else:
        pend = 0
    return dict(
        S=settings(),
        CSS_V=_css_ver(),
        year=datetime.now().year,
        CATS=CATS,
        PAY=pay_mode(),
        ONLINE=online_enabled(),
        PEND=pend,
    )


@app.template_filter("jl")
def _jl(s):
    try:
        return json.loads(s or "[]")
    except Exception:
        return []


@app.template_filter("inr")
def _inr(n):
    return "{:,}".format(int(n or 0))


@app.route("/media/<path:n>")
def media(n):
    if n.replace("\\", "/").lstrip("/").lower().startswith("documents"):
        abort(404)  # receipts / Form 10BE are served only by their own protected routes
    return send_from_directory(UP, n, max_age=86400)


# ---------- public pages ----------
def pubprojects(limit=100, cat=None):
    if cat:
        return q(
            "select * from projects where published=1 and category=? order by date desc,id desc limit ?",
            (cat, limit),
        )
    return q(
        "select * from projects where published=1 order by date desc,id desc limit ?", (limit,)
    )


@app.route("/")
def home():
    return render_template(
        "home.html",
        acts=q("select * from activities order by sort,id"),
        projects=pubprojects(4),
        gal=q("select * from gallery order by id desc limit 6"),
        banners=q("select * from banners order by sort,id"),
    )


@app.route("/about")
def about():
    return render_template("about.html", trustees=q("select * from trustees order by sort,id"))


@app.route("/activities")
def activities():
    return render_template("activities.html", acts=q("select * from activities order by sort,id"))


@app.route("/projects")
def projects():
    cat = request.args.get("category", "")
    return render_template(
        "projects.html", projects=pubprojects(100, cat if cat in CATS else None), cat=cat
    )


@app.route("/projects/<int:id>")
def project(id):
    p = q("select * from projects where id=? and published=1", (id,), one=True) or abort(404)
    return render_template(
        "project.html", p=p, gal=q("select * from gallery where project=?", (p["title"],))
    )


@app.route("/gallery")
def gallery():
    kind, act, pr = (
        request.args.get("kind", ""),
        request.args.get("activity", ""),
        request.args.get("project", ""),
    )
    sql, a = "select * from gallery where 1=1", []
    for col, v in (("kind", kind), ("activity", act), ("project", pr)):
        if v:
            sql += " and %s=?" % col
            a.append(v)
    return render_template(
        "gallery.html",
        items=q(sql + " order by id desc", a),
        kind=kind,
        act=act,
        pr=pr,
        acts=q("select title from activities order by sort,id"),
        prs=q(
            "select title from projects where published=1 union select project from gallery where project is not null and project!='' order by 1"
        ),
    )


@app.route("/donate")
def donate():
    resp = make_response(
        render_template(
            "donate.html",
            amount=request.args.get("amount", "1000"),
            test=False,
            pan_from=int(E("PAN_MANDATORY_FROM", "0") or 0),
        )
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/contact", methods=["GET", "POST"])
def contact():
    f = {"name": "", "email": "", "phone": "", "message": ""}
    if request.method == "POST":
        f = {
            k: request.form.get(k, "").strip()[:2000] for k in ("name", "email", "phone", "message")
        }
        f["email"] = re.sub(r"\s", "", f["email"])
        if len(f["name"]) < 2:
            err = "Please enter your name (at least 2 letters)."
        elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["email"]):
            err = "Please enter a valid email address, for example name@gmail.com."
        elif f["phone"] and not re.fullmatch(r"\+?[0-9][0-9 \-]{6,17}", f["phone"]):
            err = "Please enter a valid phone number or leave it empty."
        elif len(f["message"]) < 2:
            err = "Please type your message."
        else:
            err = ""
        if err:
            flash(err, "err")
        else:
            ex(
                "insert into messages(name,email,phone,message,created) values(?,?,?,?,?)",
                (f["name"], f["email"], f["phone"], f["message"], now()),
            )
            flash("Thank you! Your message has been sent.", "ok")
            return redirect(url_for("contact"))
    return render_template("contact.html", f=f)


@app.route("/verify")
def verify_form():
    n = request.args.get("n", "").strip()
    return (
        redirect(url_for("verify", num=n))
        if n
        else render_template("verify.html", c=None, searched=False)
    )


@app.route("/verify/<num>")
def verify(num):
    c = lookup_certificate(num)
    return render_template("verify.html", c=c, num=num, searched=True)


TFAILS = {}


@app.route("/track", methods=["GET", "POST"])
def track():
    """Donor enters the reference number (or UTR) + the mobile number used for the donation -> opens the status tracker."""
    if request.method == "POST":
        ip, t = request.remote_addr, time.time()
        TFAILS[ip] = [x for x in TFAILS.get(ip, []) if t - x < 600]
        if len(TFAILS[ip]) >= 10:
            flash("Too many attempts. Please try again in 10 minutes.", "err")
        else:
            key = request.form.get("ref", "").strip().upper()
            mob = re.sub(r"\D", "", request.form.get("mobile", ""))[-10:]
            d = q("select ref,mobile from donations where ref=? or utr=?", (key, key), one=True) if key else None
            if d and len(mob) == 10 and re.sub(r"\D", "", d["mobile"] or "")[-10:] == mob:
                return redirect(url_for("receipt", ref=d["ref"]))
            TFAILS[ip].append(t)
            flash("No donation found for that reference / UTR and mobile number. Please check and try again.", "err")
    return render_template("track.html", ref=request.form.get("ref", ""))


@app.route("/receipt/<ref>")
def receipt(ref):
    d = q("select * from donations where ref=?", (ref,), one=True) or abort(404)
    c = q("select * from certificates where donation_id=?", (d["id"],), one=True)
    if d["status"] == "paid" and not c:
        try:
            c = issue_certificate(d["id"])
        except Exception as e:
            print("Receipt generation failed:", e)
    resp = make_response(render_template("receipt.html", d=d, c=c))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/certificate/<num>.pdf")
def cert_pdf(num):
    num = resolve(num)
    c = q("select * from certificates where number=?", (num,), one=True)
    if not c or (c["revoked"] and not session.get("aid")):
        abort(404)
    p = os.path.join(CERTS, os.path.basename(num) + ".pdf")
    if not os.path.exists(p):
        make_pdf(num, q("select * from donations where id=?", (c["donation_id"],), one=True))
    return send_file(
        p,
        mimetype="application/pdf",
        download_name=num + ".pdf",
        as_attachment=request.args.get("dl") == "1",
    )


@app.route("/robots.txt")
def robots():
    return Response(
        "User-agent: *\nDisallow: /admin\nSitemap: %s/sitemap.xml\n" % E("BASE_URL").rstrip("/"),
        mimetype="text/plain",
    )


@app.route("/sitemap.xml")
def sitemap():
    b = E("BASE_URL").rstrip("/") or request.url_root.rstrip("/")
    u = ["/", "/about", "/activities", "/projects", "/gallery", "/donate", "/contact"] + [
        "/projects/%d" % p["id"] for p in pubprojects()
    ]
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join("<url><loc>%s%s</loc></url>" % (b, x) for x in u)
        + "</urlset>",
        mimetype="application/xml",
    )


@app.errorhandler(404)
def nf(e):
    return render_template("404.html"), 404


# ---------- donations & payments ----------
LOOK = {}


def g80_get(did):
    """80G tracking row for a donation (created on first use, so old donations are migrated safely)."""
    r = q("select * from g80 where donation_id=?", (did,), one=True)
    if not r:
        don = q("select * from donations where id=?", (did,), one=True)
        st = (
            "na"
            if (don["mode"] or "live") == "test"
            else ("review" if don["pan"] else "pan_needed")
        )
        ex("insert into g80(donation_id,status,updated) values(?,?,?) on conflict(donation_id) do nothing", (did, st, now()))
        r = q("select * from g80 where donation_id=?", (did,), one=True)
    return r


def g80_peek(did):
    """Same as g80_get but READ-ONLY: opening a donor record never writes to the database."""
    r = q("select * from g80 where donation_id=?", (did,), one=True)
    if r:
        return r
    don = q("select * from donations where id=?", (did,), one=True)
    st = "na" if (don["mode"] or "live") == "test" else ("review" if don["pan"] else "pan_needed")
    return {
        "donation_id": did, "status": st, "arn": "", "filed_on": "", "filing_ref": "",
        "note": "", "form10be": "", "form10be_emailed": "", "updated": "",
    }


EMAIL_RE = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"


def clean_mobile(raw):
    """Return the mobile number in the form we store, or "" when it is not valid.
    - "+91 98765 43210" / "9876543210"  -> "9876543210"   (Indian numbers are stored as 10 digits, as before)
    - "+1 415 555 2671"                 -> "+14155552671" (other countries keep the country code)"""
    raw = re.sub(r"[\s\-().]", "", raw or "")
    if raw.startswith("+"):
        digits = raw[1:]
        if not re.fullmatch(r"[1-9]\d{6,14}", digits):
            return ""
        if digits.startswith("91"):  # India: must be a proper 10-digit mobile
            return digits[2:] if re.fullmatch(r"91[6-9]\d{9}", digits) else ""
        return "+" + digits
    raw = re.sub(r"^(91|0)(?=\d{10}$)", "", raw)  # old style input without "+"
    return raw if re.fullmatch(r"[6-9]\d{9}", raw) else ""


@app.post("/api/donate")
def api_donate():
    """Step 1 of every donation: check the form, save it as 'created' and start the chosen payment method."""
    d = request.get_json(silent=True) or {}
    name, email = " ".join((d.get("name") or "").split()), (d.get("email") or "").strip().lower()
    msg, addr = (d.get("message") or "").strip()[:300], " ".join((d.get("address") or "").split())
    pan = re.sub(r"\s", "", d.get("pan") or "").upper()
    mob = clean_mobile(d.get("mobile"))
    try:
        amt = int(float(d.get("amount")))
    except Exception:
        amt = 0
    pan_from = int(E("PAN_MANDATORY_FROM", "0") or 0)
    if not 2 <= len(name) <= 80:
        err = "Please enter your full name."
    elif not mob:
        err = "Enter a valid mobile number for the selected country."
    elif len(email) > 120 or not re.fullmatch(EMAIL_RE, email):
        err = "Enter a valid email address."
    elif not 10 <= len(addr) <= 300:
        err = "Please enter your full address (10 to 300 characters)."
    elif not 99 <= amt <= 500000:
        err = "Minimum donation amount is Rs. 99 (maximum 500000)."
    elif pan and not re.fullmatch(PAN_RE, pan):
        err = "PAN must look like ABCDE1234F (10 characters)."
    elif pan_from and amt >= pan_from and not pan:
        err = "PAN is required for donations of Rs. %s or more." % "{:,}".format(pan_from)
    else:
        err = ""
    if err:
        return jsonify(ok=False, error=err), 400

    mode = "live"  # real money. UPI QR payments are verified by the admin; online payments by Razorpay itself
    # Every new donation goes through Razorpay. The old manual UPI QR flow has been removed.
    if not online_enabled():
        return jsonify(ok=False, error="Online donations are not available right now. Please try again later or contact the Trust."), 503
    channel = "razorpay"

    ref = datetime.now().strftime("D%y%m%d") + secrets.token_hex(3).upper()
    try:  # ask Razorpay for an order; the amount is in paise (Rs. x 100)
        order_id = rzp("orders", {"amount": amt * 100, "currency": "INR", "receipt": ref})["id"]
    except Exception as e:
        print("Razorpay order failed:", e)
        return (
            jsonify(ok=False, error="Online payment is not available right now. Please try again in a few minutes."),
            502,
        )
    ex(
        "insert into donations(ref,name,mobile,email,amount,message,status,created,address,pan,mode,channel,order_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ref, name, mob, email, amt, msg, "created", now(), addr, pan, mode, channel, order_id),
    )
    return jsonify(
        ok=True,
        mode="online",
        ref=ref,
        amount=amt,
        order_id=order_id,
        key=E("RAZORPAY_KEY_ID"),
        name=name,
        email=email,
        mobile=mob,
    )


@app.get("/api/status/<ref>")
def api_status(ref):
    """Tiny status check used by the receipt page so the certificate appears by itself the moment payment is confirmed."""
    don = q("select id,status from donations where ref=?", (ref,), one=True) or abort(404)
    cert = q(
        "select number from certificates where donation_id=? and revoked=0", (don["id"],), one=True
    )
    if don["status"] == "paid" and not cert:
        try:  # verified but the certificate is missing (e.g. it failed once): create it now, safe to repeat
            issue_certificate(don["id"])
            cert = q("select number from certificates where donation_id=? and revoked=0", (don["id"],), one=True)
        except Exception as e:
            print("Receipt generation failed:", e)
    resp = jsonify(
        status=don["status"],
        ready=bool(cert),
        download=url_for("cert_pdf", num=cert["number"], dl=1) if cert else "",
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


def mark_paid(did, pid, method=""):
    """Atomic and repeatable: verify + webhook can both call it, but only one receipt is ever created."""
    db().execute(
        "update donations set status='paid', payment_id=?, method=?, paid_at=? where id=? and status!='paid'",
        (pid, method or "", now(), did),
    )
    db().commit()
    try:
        issue_certificate(did)
    except Exception as e:
        print("Receipt generation failed:", e)
    g80_get(did)


@app.post("/api/verify")
def api_verify():
    d = request.get_json(silent=True) or {}
    don = q("select * from donations where ref=?", (d.get("ref"),), one=True) or abort(404)
    if don["channel"] == "upi_qr":
        abort(404)  # UPI QR payments are confirmed only by the Trust admin
    ok_url = url_for("receipt", ref=don["ref"])
    if don["status"] == "paid":
        return jsonify(ok=True, url=ok_url)
    pid = d.get("razorpay_payment_id") or ""
    if (
        pay_mode() != "razorpay"
        or (don["mode"] or "live") != "live"
        or not don["order_id"]
        or not valid_payment(don["order_id"], pid, d.get("razorpay_signature"))
    ):
        ex("update donations set status='failed' where id=? and status='created'", (don["id"],))
        return jsonify(ok=False), 400  # bad signature: never a receipt
    try:
        p = rzp_get(
            "payments/" + pid
        )  # server-to-server double check of order, amount and capture status
    except Exception:
        p = None
    method, state = "", "captured"
    if p:
        if p.get("order_id") != don["order_id"] or p.get("amount") != don["amount"] * 100:
            return jsonify(ok=False), 400
        method, state = p.get("method") or "", p.get("status") or "captured"
    if state != "captured":
        return jsonify(
            ok=True, url=ok_url
        )  # authorised only: the webhook completes it once captured
    mark_paid(don["id"], pid, method)
    return jsonify(ok=True, url=ok_url)


@app.post("/api/fail")
def api_fail():
    ref = (request.get_json(silent=True) or {}).get("ref")
    ex(
        "update donations set status='failed' where ref=? and status='created' and channel!='upi_qr'",
        (ref,),
    )
    return jsonify(ok=True)


@app.post("/api/test-pay")
def api_test_pay():
    if pay_mode() != "test":
        abort(404)
    d = request.get_json(silent=True) or {}
    don = q("select * from donations where ref=?", (d.get("ref"),), one=True) or abort(404)
    if (don["mode"] or "live") != "test" or don["channel"] == "upi_qr":
        abort(404)  # a live (or UPI QR) donation can never be completed from the test endpoint
    if don["status"] == "created":
        if d.get("ok"):
            mark_paid(don["id"], "TEST-" + secrets.token_hex(4).upper(), "test")
        else:
            ex("update donations set status='failed' where id=?", (don["id"],))
    return jsonify(ok=True, url=url_for("receipt", ref=don["ref"]))


@app.post("/webhook/razorpay", endpoint="webhook")
def webhook():
    body = request.get_data()
    if not valid_webhook(body, request.headers.get("X-Razorpay-Signature", "")):
        abort(400)
    try:
        ev = json.loads(body)
    except ValueError:
        abort(400)
    if ev.get("event") in ("payment.captured", "order.paid"):
        p = ev.get("payload", {}).get("payment", {}).get("entity", {})
        don = q("select * from donations where order_id=?", (p.get("order_id"),), one=True)
        if (
            don
            and (don["mode"] or "live") == "live"
            and don["status"] != "paid"
            and p.get("amount") == don["amount"] * 100
            and p.get("status") == "captured"
        ):
            mark_paid(don["id"], p["id"], p.get("method") or "")
    return "ok"


# ---------- public 80G status ----------
G80_TEXT = {
    "review": "Your donation has been received. The Trust will review whether it can be included in 80G reporting. This is not a guarantee of any tax deduction.",
    "pan_needed": "No donor PAN is recorded for this donation. If you wish to be considered for 80G reporting, please contact the Trust with your PAN.",
    "eligible": "The Trust has verified this donation for inclusion in 80G reporting. The official Form 10BE can be issued only after the Trust files Form 10BD and the Income Tax portal processes it.",
    "pre_arn": "The Trust has obtained the required Pre-ARN acknowledgement for this donation. Form 10BD filing and portal processing are still pending.",
    "filed": "The Trust has filed Form 10BD covering this donation. The official Form 10BE will be shared after the Income Tax portal processes it.",
    "issued": "The official Form 10BE for this donation has been issued by the Trust. You can download it below.",
    "na": "This donation is covered by the donation receipt only. It is not part of 80G reporting.",
}


@app.route("/80g")
def g80_info():
    n, e = request.args.get("n", "").strip(), request.args.get("e", "").strip().lower()
    if n or e:
        ip, t = request.remote_addr, time.time()
        LOOK[ip] = [x for x in LOOK.get(ip, []) if t - x < 600]
        if len(LOOK[ip]) >= 10:
            flash("Too many lookups. Please try again in a few minutes.", "err")
        else:
            LOOK[ip].append(t)
            c = q(
                "select d.ref from certificates c join donations d on d.id=c.donation_id where c.number=? and lower(d.email)=? and d.status='paid'",
                (resolve(n), e),
                one=True,
            )
            if c:
                return redirect(url_for("g80_status", ref=c["ref"]))
            flash("No paid donation found for that receipt number and email address.", "err")
    return render_template("g80.html", n=n, e=e)


@app.route("/80g/<ref>")
def g80_status(ref):
    d = q("select * from donations where ref=? and status='paid'", (ref,), one=True) or abort(404)
    resp = make_response(
        render_template(
            "g80_status.html",
            d=d,
            c=q("select * from certificates where donation_id=?", (d["id"],), one=True),
            g=g80_get(d["id"]),
            txt=G80_TEXT,
        )
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/80g/<ref>/form10be.pdf")
def g80_form(ref):
    d = q("select * from donations where ref=? and status='paid'", (ref,), one=True) or abort(404)
    g = g80_get(d["id"])
    p = os.path.join(UP, g["form10be"] or "#")
    if g["status"] != "issued" or not g["form10be"] or not os.path.isfile(p):
        abort(404)  # only an official, admin-uploaded Form 10BE is ever served
    return send_file(
        p, mimetype="application/pdf", as_attachment=True, download_name="Form10BE-%s.pdf" % ref
    )


# ---------- admin ----------
FAILS = {}


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip, t = request.remote_addr, time.time()
        FAILS[ip] = [x for x in FAILS.get(ip, []) if t - x < 600]
        if len(FAILS[ip]) >= 5:
            flash("Too many attempts. Try again in 10 minutes.", "err")
        else:
            a = q(
                "select * from admins where username=?",
                (request.form.get("username", "").strip(),),
                one=True,
            )
            if a and check_password_hash(a["pw"], request.form.get("password", "")):
                session.clear()
                session["aid"] = a["id"]
                session.permanent = True
                FAILS.pop(ip, None)
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/admin") else url_for("dash"))
            FAILS[ip].append(t)
            flash("Invalid username or password.", "err")
    return render_template("admin/login.html")


@app.post("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/")
@app.route("/admin")
@admin
def dash():
    row = q(
        "select "
        "(select count(*) from projects) projects,"
        "(select count(*) from projects where published=1) published,"
        "(select count(*) from activities) activities,"
        "(select count(*) from gallery) gallery,"
        "(select count(*) from donations where status='paid') paid,"
        "(select coalesce(sum(amount),0) from donations where status='paid') total,"
        "(select count(*) from messages where seen=0) msgs,"
        "(select count(*) from certificates) certs,"
        "(select count(*) from donations where status='pending') pending",
        one=True,
    )
    stats = dict(row)
    g._pend = stats["pending"]
    return render_template(
        "admin/dash.html", st=stats, recent=q("select * from donations order by id desc limit 8")
    )


def save_entity(name, id=None):
    cfg = ENT[name]
    old = q("select * from %s where id=?" % name, (id,), one=True) if id else None
    vals = {}
    for col, label, t, o in cfg["fields"]:
        if t in ("text", "textarea", "select", "date", "combo"):
            vals[col] = request.form.get(col, "").strip()
        elif t == "number":
            try:
                vals[col] = int(request.form.get(col) or 0)
            except ValueError:
                vals[col] = 0
        elif t == "check":
            vals[col] = 1 if request.form.get(col) else 0
        elif t in ("image", "video", "media"):
            n = save(
                request.files.get(col),
                {"image": IMG, "video": VID, "media": IMG | VID}[t],
                cfg["folder"],
            )
            if n:
                rmfile(old[col] if old else None)
                vals[col] = n
            elif old and request.form.get("rm_" + col):
                rmfile(old[col])
                vals[col] = ""
            else:
                vals[col] = old[col] if old else ""
        elif t == "images":
            cur = _jl(old[col]) if old else []
            rm = set(request.form.getlist("rm_" + col))
            for f in cur:
                if f in rm:
                    rmfile(f)
            cur = [f for f in cur if f not in rm]
            for fs in request.files.getlist(col):
                n = save(fs, IMG, cfg["folder"])
                if n:
                    cur.append(n)
            vals[col] = json.dumps(cur)
    if name == "gallery" and vals.get("file"):
        vals["kind"] = "video" if vals["file"].rsplit(".", 1)[-1] in VID else "photo"
    if not vals.get(cfg["req"]):
        flash("Required field missing: " + cfg["req"], "err")
        return False
    cols = list(vals)
    if old:
        ex(
            "update %s set %s where id=?" % (name, ",".join('"' + c + '"=?' for c in cols)),
            [vals[c] for c in cols] + [id],
        )
    else:
        ex(
            "insert into %s(%s) values(%s)"
            % (name, ",".join('"' + c + '"' for c in cols), ",".join("?" * len(cols))),
            [vals[c] for c in cols],
        )
    return True


@app.route("/admin/<name>")
@admin
def a_list(name):
    if name not in ENT:
        abort(404)
    return render_template(
        "admin/list.html",
        name=name,
        cfg=ENT[name],
        rows=q("select * from %s order by id desc" % name),
    )


@app.route("/admin/<name>/new", methods=["GET", "POST"])
@app.route("/admin/<name>/<int:id>/edit", methods=["GET", "POST"])
@admin
def a_form(name, id=None):
    if name not in ENT:
        abort(404)
    row = (q("select * from %s where id=?" % name, (id,), one=True) or abort(404)) if id else None
    if request.method == "POST" and save_entity(name, id):
        flash("Saved. The live website is updated.", "ok")
        return redirect(url_for("a_list", name=name))
    fields = [(c, l, t, o() if callable(o) else o) for c, l, t, o in ENT[name]["fields"]]
    return render_template("admin/form.html", name=name, cfg=ENT[name], fields=fields, row=row)


@app.post("/admin/<name>/<int:id>/delete")
@admin
def a_delete(name, id):
    if name not in ENT:
        abort(404)
    row = q("select * from %s where id=?" % name, (id,), one=True)
    if row:
        for col, l, t, o in ENT[name]["fields"]:
            if t in ("image", "video", "media"):
                rmfile(row[col])
            elif t == "images":
                for f in _jl(row[col]):
                    rmfile(f)
        ex("delete from %s where id=?" % name, (id,))
        flash("Deleted.", "ok")
    return redirect(url_for("a_list", name=name))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin
def a_settings():
    if request.method == "POST":
        S = settings()
        for gid, gt, fl in SETTING_GROUPS:
            for k, l, t in fl:
                if t == "image":
                    n = save(
                        request.files.get(k), IMG, "Logo"
                    )  # a new file chosen -> replace the old one
                    if n:
                        rmfile(S.get(k))
                        v = n
                    elif request.form.get("remove_" + k) and S.get(k):
                        rmfile(S.get(k))
                        v = ""  # "Remove" ticked -> delete file, site falls back to the default image
                    else:
                        continue
                else:
                    v = request.form.get(k, "").strip()
                if k == "map_embed" and v:
                    m = re.search(
                        r'src\s*=\s*["\']([^"\']+)["\']', v
                    )  # allow pasting the whole <iframe ...> code from Google Maps
                    if m:
                        v = m.group(1)
                    if not v.startswith("https://www.google.com/maps"):
                        flash("Map URL must start with https://www.google.com/maps", "err")
                        continue
                ex(
                    "insert into settings(k,v) values(?,?) on conflict(k) do update set v=excluded.v",
                    (k, v),
                )
        flash("Settings saved. The live website is updated.", "ok")
        return redirect(url_for("a_settings"))
    return render_template("admin/settings.html", groups=SETTING_GROUPS)


def _list_back():
    """The donations-list URL (with its search / filters) the admin came from. Only /admin/donations is accepted."""
    b = request.args.get("back") or request.form.get("back", "")
    p = urlsplit(b)
    return b if b and not p.scheme and not p.netloc and p.path == "/admin/donations" else ""


def _here(id):
    """This donor's page, remembering which list the admin came from."""
    b = _list_back()
    return url_for("a_donation", id=id, back=b) if b else url_for("a_donation", id=id)


def _keep(id, form, keys):
    """After a refused submit keep what the admin typed, so the form is not reset (shown once on the next page load)."""
    session["fv_%d" % id] = {k: (form.get(k, "") or "")[:200] for k in keys}


def _back(default):
    b = request.form.get("back", "")
    return b if b.startswith("/admin") else default


@app.route("/admin/donations")
@admin
def a_donations():
    st, md, s, ch = (
        request.args.get("status", ""),
        request.args.get("mode", ""),
        request.args.get("s", "").strip(),
        request.args.get("channel", ""),
    )
    sql, a = (
        "select d.*,c.number,c.emailed,c.email_error,g.status g80 from donations d left join certificates c on c.donation_id=d.id left join g80 g on g.donation_id=d.id where 1=1",
        [],
    )
    if st:
        sql += " and d.status=?"
        a.append(st)
    if md:
        sql += " and d.mode=?"
        a.append(md)
    if ch in ("upi_qr", "razorpay"):
        sql += " and d.channel=?"
        a.append(ch)
    if s:
        sql += " and (lower(coalesce(d.name,'')) like lower(?) or lower(coalesce(d.email,'')) like lower(?) or lower(coalesce(d.mobile,'')) like lower(?) or lower(coalesce(d.ref,'')) like lower(?) or lower(coalesce(c.number,'')) like lower(?) or lower(coalesce(d.utr,'')) like lower(?))"
        a += ["%" + s + "%"] * 6
    return render_template(
        "admin/donations.html",
        back=request.full_path if request.query_string else request.path,
        rows=q(sql + " order by d.id desc limit 1000", a),
        st=st,
        md=md,
        s=s,
        ch=ch,
    )


@app.route("/admin/donations/<int:id>")
@admin
def a_donation(id):
    d = q("select * from donations where id=?", (id,), one=True) or abort(404)
    g = g80_peek(id)  # read-only: viewing a record never changes it
    hist = q(
        "select d.id,d.ref,d.amount,d.status,d.created,d.paid_at,c.number from donations d left join certificates c on c.donation_id=d.id"
        " where d.id!=? and ((d.mobile!='' and d.mobile=?) or (d.email!='' and lower(d.email)=lower(?)) or (d.pan!='' and d.pan=?))"
        " order by d.id desc limit 50",
        (id, d["mobile"] or "", d["email"] or "", d["pan"] or ""),
    )
    r = make_response(
        render_template(
            "admin/donation.html",
            d=d,
            c=q("select * from certificates where donation_id=?", (id,), one=True),
            g=g,
            g80_label=G80_LABEL.get(g["status"], g["status"]),
            hist=hist,
            back=_list_back() or url_for("a_donations"),
            here=_here(id),
            fv=session.pop("fv_%d" % id, {}),
            STAT=G80_STATUS,
        )
    )
    r.headers["Cache-Control"] = "no-store"
    return r  # donor PAN / address must never be cached


def _admin_name():
    return (
        q("select username from admins where id=?", (session.get("aid"),), one=True)
        or {"username": "admin"}
    )["username"]


@app.post("/admin/donations/<int:id>/upi-verify")
@admin
def a_upi_verify(id):
    """The ONLY place a UPI QR donation becomes PAID: the admin confirms the credit in the real bank account. Then the receipt is issued once."""
    d = q("select * from donations where id=?", (id,), one=True) or abort(404)
    back = _here(id)
    f = request.form
    if d["channel"] != "upi_qr" or d["status"] != "pending" or not d["utr"]:
        flash("Only a pending UPI QR payment with a UTR can be verified.", "err")
        return redirect(back)
    try:
        got = int(float(f.get("received", "")))
    except ValueError:
        got = 0
    day = f.get("credit_date", "")
    try:
        dt = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        dt = None
    if not f.get("confirm"):
        err = "Tick the confirmation that you checked this credit in the Kotak Mahindra Bank account / merchant app."
    elif not 10 <= got <= 500000:
        err = "Enter the amount actually credited to the bank account (10 to 500000 rupees)."
    elif not dt or dt.date() > datetime.now().date():
        err = "Enter the bank credit date (it cannot be in the future)."
    else:
        err = ""
    if err:
        _keep(id, f, ("received", "credit_date", "note"))
        flash(err, "err")
        return redirect(back)
    note = " ".join(f.get("note", "").split())[:200]
    if got != d["amount"]:
        note = (
            "Amount corrected from %s to %s as per the bank credit. " % (d["amount"], got) + note
        ).strip()
    c = db().execute(
        "update donations set status='paid', payment_id=utr, method='upi_qr', amount=?, paid_at=?, verified_by=?, verified_at=?, verify_note=? where id=? and status='pending'",
        (got, day, _admin_name(), now(), note, id),
    )
    db().commit()
    if c.rowcount != 1:
        flash("This payment was already processed.", "err")
        return redirect(back)
    try:
        issue_certificate(id)  # idempotent: one receipt per donation, even if verified twice
    except Exception as e:
        print("Receipt generation failed:", e)
    g80_get(id)
    flash(
        "Payment verified. Receipt issued and emailed to the donor (if email is configured).", "ok"
    )
    return redirect(back)


@app.post("/admin/donations/<int:id>/upi-reject")
@admin
def a_upi_reject(id):
    d = q("select * from donations where id=?", (id,), one=True) or abort(404)
    back = _here(id)
    reason = " ".join(request.form.get("reason", "").split())[:200]
    if d["channel"] != "upi_qr" or d["status"] != "pending":
        flash("Only a pending UPI QR payment can be rejected.", "err")
    elif len(reason) < 5:
        flash("Enter the reason for rejection (it is shown to the donor).", "err")
    else:
        ex(
            "update donations set status='rejected', reject_reason=?, verified_by=?, verified_at=? where id=? and status='pending'",
            (reason, _admin_name(), now(), id),
        )
        flash("Payment rejected. No receipt will be issued.", "ok")
    return redirect(back)


@app.route("/admin/donations/<int:id>/proof")
@admin
def a_upi_proof(id):
    d = q("select * from donations where id=?", (id,), one=True) or abort(404)
    p = os.path.abspath(os.path.join(UP, d["screenshot"] or "#"))
    if (
        not d["screenshot"]
        or not p.startswith(os.path.abspath(PROOFS) + os.sep)
        or not os.path.isfile(p)
    ):
        abort(404)
    r = send_file(
        p,
        mimetype={"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
            p.rsplit(".", 1)[-1], "application/octet-stream"
        ),
    )
    r.headers["Cache-Control"] = "no-store"
    return r


@app.post("/admin/donations/<int:id>/80g")
@admin
def a_g80_save(id):
    d = q("select * from donations where id=?", (id,), one=True) or abort(404)
    g = g80_get(id)
    back = _here(id)
    f = request.form
    _keep(id, f, ("status", "pan", "arn", "filed_on", "filing_ref", "note"))
    st = f.get("status", "")
    arn, filed_on, ref, note = (
        f.get(k, g[k] or "").strip()[:120] for k in ("arn", "filed_on", "filing_ref", "note")
    )
    pan = re.sub(r"\s", "", f.get("pan", "")).upper() if "pan" in f else (d["pan"] or "")
    fs, newfile = request.files.get("form10be"), None
    if pan and not re.fullmatch(PAN_RE, pan):
        flash("PAN must look like ABCDE1234F.", "err")
        return redirect(back)
    if fs and fs.filename:
        data = fs.read(5 * 1024 * 1024 + 1)
        if (
            not fs.filename.lower().endswith(".pdf")
            or not data.startswith(b"%PDF")
            or len(data) > 5 * 1024 * 1024
        ):
            flash("Upload the official Form 10BE as a PDF file (max 5 MB).", "err")
            return redirect(back)
        os.makedirs(os.path.join(UP, "Documents", "form10be"), exist_ok=True)
        newfile = "Documents/form10be/%s.pdf" % uuid.uuid4().hex
        open(os.path.join(UP, newfile), "wb").write(data)
    f10, test = newfile or g["form10be"], (d["mode"] or "live") == "test"
    if st not in G80_LABEL:
        err = "Choose a valid status."
    elif d["status"] != "paid":
        err = "80G tracking applies to paid donations only."
    elif test and st != "na":
        err = "Test payments are never eligible for 80G."
    elif st == "eligible" and not pan:
        err = "Add the donor PAN before marking a donation as verified eligible."
    elif st == "pre_arn" and g["status"] not in ("eligible", "pre_arn"):
        err = 'Verify eligibility first (status "Verified eligible"), and only then record the Pre-ARN.'
    elif st == "pre_arn" and not arn:
        err = "Enter the Pre-ARN / acknowledgement number received from the Income Tax portal."
    elif st == "pre_arn" and not f.get("confirm"):
        err = "Tick the confirmation that the Trust verified eligibility and obtained the required acknowledgement."
    elif st == "filed" and g["status"] not in ("eligible", "pre_arn", "filed"):
        err = "Mark the donation as verified eligible before recording the Form 10BD filing."
    elif st == "filed" and not (filed_on and ref):
        err = "Enter the Form 10BD filing date and acknowledgement / token number."
    elif st == "issued" and g["status"] not in ("filed", "issued"):
        err = "Form 10BE can be recorded only after Form 10BD is marked as filed."
    elif st == "issued" and not f10:
        err = "Upload the official Form 10BE PDF downloaded from the Income Tax portal. A Form 10BE is never generated by this website."
    else:
        err = ""
    if err:
        if newfile:
            rmfile(newfile)
        flash(err, "err")
        return redirect(back)
    session.pop("fv_%d" % id, None)  # saved: nothing to keep any more
    if newfile and g["form10be"]:
        rmfile(g["form10be"])
    if pan != (d["pan"] or ""):
        ex("update donations set pan=? where id=?", (pan, id))
    ex(
        "update g80 set status=?,arn=?,filed_on=?,filing_ref=?,note=?,form10be=?,updated=? where donation_id=?",
        (st, arn, filed_on, ref, note, f10 or "", now(), id),
    )
    flash("80G tracking saved.", "ok")
    return redirect(back)


@app.post("/admin/donations/<int:id>/10be-email")
@admin
def a_10be_email(id):
    d = q("select * from donations where id=?", (id,), one=True) or abort(404)
    g = g80_get(id)
    p = os.path.join(UP, g["form10be"] or "#")
    if g["status"] != "issued" or not os.path.isfile(p):
        flash("Only an issued Form 10BE (uploaded PDF) can be emailed.", "err")
    else:
        try:
            if email_10be(d, p):
                ex("update g80 set form10be_emailed=? where donation_id=?", (now(), id))
                flash("Form 10BE emailed to %s." % d["email"], "ok")
            else:
                flash("SMTP is not configured in .env", "err")
        except Exception as e:
            flash("Email failed: %s" % e, "err")
    return redirect(_here(id))


@app.route("/admin/donations/<int:id>/form10be.pdf")
@admin
def a_10be_file(id):
    g = g80_get(id)
    p = os.path.join(UP, g["form10be"] or "#")
    if not g["form10be"] or not os.path.isfile(p):
        abort(404)
    return send_file(p, mimetype="application/pdf", download_name="Form10BE-%d.pdf" % id)


@app.route("/admin/certificates")
@admin
def a_certs():
    return render_template(
        "admin/certs.html",
        rows=q(
            "select c.*,d.name,d.email,d.amount,d.mode dmode,d.id did from certificates c join donations d on d.id=c.donation_id order by c.id desc"
        ),
    )


@app.post("/admin/certificates/<int:id>/<act>")
@admin
def a_cert_act(id, act):
    c = q("select * from certificates where id=?", (id,), one=True) or abort(404)
    don = q("select * from donations where id=?", (c["donation_id"],), one=True)
    if act == "regen":
        make_pdf(c["number"], don)
        flash("Receipt PDF regenerated.", "ok")
    elif act == "email":
        try:
            flash(
                (
                    "Receipt emailed to %s." % don["email"]
                    if email_cert(c["number"], don)
                    else "SMTP is not configured in .env"
                ),
                "ok",
            )
        except Exception as e:
            flash("Email failed: %s" % e, "err")
    elif act == "revoke":
        ex("update certificates set revoked=1-revoked where id=?", (id,))
        flash("Receipt status changed.", "ok")
    elif act == "number":
        new = request.form.get("number", "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-]{5,39}", new):
            flash("Receipt number: 6-40 characters, letters, digits and hyphens only.", "err")
        elif new != c["number"] and q(
            "select 1 from certificates where number=?", (new,), one=True
        ):
            flash("That receipt number is already used.", "err")
        elif new != c["number"]:
            old, op = c["number"], os.path.join(CERTS, os.path.basename(c["number"]) + ".pdf")
            ex("update certificates set number=? where id=?", (new, id))
            ex(
                "insert into cert_alias(old,new_number) values(?,?) on conflict(old) do update set new_number=excluded.new_number",
                (old, new),
            )
            ex(
                "update cert_alias set new_number=? where new_number=?", (new, old)
            )  # old QR codes / links keep working
            if os.path.exists(op):
                os.remove(op)
            make_pdf(new, don)
            flash(
                "Receipt number changed to %s and the PDF was regenerated. Old links still work."
                % new,
                "ok",
            )
    return redirect(_back(url_for("a_certs")))


@app.route("/admin/80g")
@admin
def a_g80():
    for r in q(
        "select id from donations d where status='paid' and mode='live' and not exists(select 1 from g80 where donation_id=d.id)"
    ):
        g80_get(r["id"])
    st, fy = request.args.get("status", ""), request.args.get("fy", "")
    sql, a = (
        "select d.*,c.number,c.fy,g.status g80,g.arn,g.filed_on,g.filing_ref,g.form10be from donations d left join certificates c on c.donation_id=d.id left join g80 g on g.donation_id=d.id "
        "where d.status='paid' and d.mode='live'"
    ), []
    if st:
        sql += " and g.status=?"
        a.append(st)
    if fy:
        sql += " and c.fy=?"
        a.append(fy)
    counts = {
        r["s"]: (r["n"], r["t"])
        for r in q(
            "select g.status s,count(*) n,sum(d.amount) t from donations d join g80 g on g.donation_id=d.id where d.status='paid' and d.mode='live' group by g.status"
        )
    }
    fys = [
        r["fy"]
        for r in q(
            "select distinct fy from certificates where fy is not null and mode='live' order by fy desc"
        )
    ]
    return render_template(
        "admin/g80.html",
        rows=q(sql + " order by d.id desc", a),
        st=st,
        fy=fy,
        counts=counts,
        STAT=G80_STATUS,
        fys=fys,
    )


@app.route("/admin/messages")
@admin
def a_messages():
    return render_template("admin/messages.html", rows=q("select * from messages order by id desc"))


@app.post("/admin/messages/<int:id>/<act>")
@admin
def a_msg_act(id, act):
    if act == "delete":
        ex("delete from messages where id=?", (id,))
    elif act == "seen":
        ex("update messages set seen=1-seen where id=?", (id,))
    return redirect(url_for("a_messages"))


@app.route("/admin/password", methods=["GET", "POST"])
@admin
def a_password():
    if request.method == "POST":
        a = q("select * from admins where id=?", (session["aid"],), one=True)
        new = request.form.get("new", "")
        if not check_password_hash(a["pw"], request.form.get("old", "")):
            flash("Current password is wrong.", "err")
        elif len(new) < 10 or new != request.form.get("new2"):
            flash("New password must be 10+ characters and match the confirmation.", "err")
        else:
            ex("update admins set pw=? where id=?", (generate_password_hash(new), a["id"]))
            flash("Password changed.", "ok")
    return render_template("admin/password.html")


@app.route("/admin/reports")
@admin
def a_reports():
    return render_template("admin/reports.html")


def _safe(v):
    v = "" if v is None else v
    return (
        "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
    )  # blocks spreadsheet formula injection


def _export(headers, rows, name, fmt):
    rows = [[_safe(x) for x in r] for r in rows]
    if fmt == "xlsx":
        try:
            import openpyxl
        except ImportError:
            flash(
                "Excel export needs openpyxl. Run: pip install openpyxl (it is listed in requirements.txt).",
                "err",
            )
            return redirect(request.referrer or url_for("a_donations"))
        from openpyxl.styles import Font, PatternFill

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Report"
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="0B3A8C")
        for r in rows:
            ws.append(r)
        for i, h in enumerate(headers, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = max(
                14, min(42, len(str(h)) + 6)
            )
        ws.freeze_panes = "A2"
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=name + ".xlsx",
        )
    o = io.StringIO()
    w = csv.writer(o)
    w.writerow(headers)
    w.writerows(rows)
    return Response(
        "\ufeff" + o.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=%s.csv" % name},
    )


def _report(fmt):
    rows = q(
        "select d.*,c.number from donations d left join certificates c on c.donation_id=d.id order by d.id"
    )
    return _export(
        [
            "Reference",
            "Receipt No",
            "Name",
            "Mobile",
            "Email",
            "Amount",
            "Status",
            "Mode",
            "Channel",
            "Payment Method",
            "Payment/Transaction ID",
            "UTR (UPI QR)",
            "Declared Amount",
            "Verified By",
            "Verified At",
            "Rejection Reason",
            "Date",
            "PAN (masked)",
            "Message",
        ],
        [
            [
                d["ref"],
                d["number"],
                d["name"],
                d["mobile"],
                d["email"],
                d["amount"],
                d["status"],
                d["mode"],
                d["channel"],
                d["method"],
                d["payment_id"],
                d["utr"],
                d["declared_amount"],
                d["verified_by"],
                d["verified_at"],
                d["reject_reason"],
                d["paid_at"] or d["created"],
                mask_pan(d["pan"]),
                d["message"],
            ]
            for d in rows
        ],
        "donations-" + datetime.now().strftime("%Y%m%d"),
        fmt,
    )


def _g80_data(fmt):
    for r in q(
        "select id from donations d where status='paid' and mode='live' and not exists(select 1 from g80 where donation_id=d.id)"
    ):
        g80_get(r["id"])
    rows = q(
        "select d.*,c.number,c.fy,g.status g80,g.arn,g.filed_on,g.filing_ref from donations d left join certificates c on c.donation_id=d.id left join g80 g on g.donation_id=d.id where d.status='paid' and d.mode='live' order by d.id"
    )
    return _export(
        [
            "Financial Year",
            "Receipt No",
            "Donation Date",
            "Donor Name",
            "Donor PAN",
            "Address",
            "Mobile",
            "Email",
            "Amount (INR)",
            "Payment ID",
            "80G Status",
            "Pre-ARN",
            "10BD Filed On",
            "10BD Ack/Token",
        ],
        [
            [
                d["fy"] or fy_label(),
                d["number"],
                (d["paid_at"] or d["created"] or "")[:10],
                d["name"],
                d["pan"],
                d["address"],
                d["mobile"],
                d["email"],
                d["amount"],
                d["payment_id"],
                G80_LABEL.get(d["g80"], ""),
                d["arn"],
                d["filed_on"],
                d["filing_ref"],
            ]
            for d in rows
        ],
        "form10bd-data-" + datetime.now().strftime("%Y%m%d"),
        fmt,
    )


@app.route("/admin/report.csv")
@admin
def a_csv():
    return _report("csv")


@app.route("/admin/report.xlsx")
@admin
def a_xlsx():
    return _report("xlsx")


@app.route("/admin/80g-data.csv")
@admin
def a_g80_csv():
    return _g80_data("csv")


@app.route("/admin/80g-data.xlsx")
@admin
def a_g80_xlsx():
    return _g80_data("xlsx")


@app.route("/admin/backup")
@admin
def a_backup():
    buf = io.BytesIO()
    if is_pg():
        dump = {}
        for t in (
            "settings",
            "admins",
            "banners",
            "activities",
            "projects",
            "gallery",
            "trustees",
            "messages",
            "donations",
            "certificates",
            "cert_alias",
            "g80",
        ):
            dump[t] = [dict(r) for r in q("select * from %s" % t)]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("asma-supabase-backup.json", json.dumps(dump, indent=2, default=str))
            for r, ds, fl in os.walk(UP):
                for f in fl:
                    z.write(os.path.join(r, f), os.path.relpath(os.path.join(r, f), DATA))
    else:
        tmp = os.path.join(DBDIR, "backup.tmp.db")
        src = sqlite3.connect(DBP)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        dst.close()
        src.close()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp, "asma.db")
            for r, ds, fl in os.walk(UP):
                for f in fl:
                    z.write(os.path.join(r, f), os.path.relpath(os.path.join(r, f), DATA))
        os.remove(tmp)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="asma-backup-%s.zip" % datetime.now().strftime("%Y%m%d-%H%M"),
    )
