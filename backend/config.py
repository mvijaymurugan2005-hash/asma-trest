"""Configuration, paths and constants."""

import os, secrets
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_p = os.path.join(ROOT, ".env")
if os.path.exists(_p):
    for _l in open(_p, encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().split(" #")[0].strip().strip("\"'"))
E = lambda k, d="": os.environ.get(k, d)
DATA = E("DATA_DIR") or ROOT
UP = os.path.join(DATA, "uploads")
DBDIR = os.path.join(DATA, "database")
DBP = os.path.join(DBDIR, "asma.db")
CERTS = os.path.join(UP, "Documents", "certificates")
PROOFS = os.path.join(
    UP, "Documents", "upi_proofs"
)  # donor UPI payment screenshots (private: never served by /media)
for _f in ("Logo", "Banners", "Activities", "Projects", "Gallery", "Documents"):
    os.makedirs(os.path.join(UP, _f), exist_ok=True)
for _d in (DBDIR, CERTS, PROOFS):
    os.makedirs(_d, exist_ok=True)


def secret_key():
    if E("SECRET_KEY"):
        return E("SECRET_KEY")
    p = os.path.join(DBDIR, "secret.key")
    if not os.path.exists(p):
        open(p, "w").write(secrets.token_hex(32))
    return open(p).read().strip()


IMG, VID = {"png", "jpg", "jpeg", "webp", "gif"}, {"mp4", "webm", "mov"}
CATS = [
    "Education Support Project",
    "Women Empowerment Project",
    "Child Welfare Project",
    "Healthcare Support Project",
    "Skill Development Project",
    "Social Welfare Project",
    "Rural Development Project",
    "Senior Citizen Welfare Project",
]
STATUSES = ["Proposed", "Ongoing", "Completed"]
ACTS = [
    ("Education Development", "Supporting education and learning opportunities."),
    ("School and College Development", "Improving learning spaces and facilities."),
    ("Scholarships", "Helping deserving students continue their studies."),
    ("Computer and Technical Training", "Digital and technical skills for all."),
    ("Women Empowerment", "Creating opportunities for women."),
    ("Child Welfare", "Care and support for children."),
    ("Medical and Healthcare", "Health support for those in need."),
    ("Old Age Care", "Dignity and care for senior citizens."),
    ("Rural Development", "Supporting rural communities."),
    ("Social Welfare", "Creating positive change in communities."),
    ("Skill Development", "Training for better livelihoods."),
    ("Disaster Relief", "Help in times of crisis."),
]
DEFAULTS = dict(
    trust_name="ASMA Educational and Charitable Trust",
    tagline="Educational and Charitable Trust",
    location="Tiruvannamalai, Tamil Nadu, India",
    email="asmafoundation2025@gmail.com",
    phone="+91 97871 62094",
    whatsapp="919787162094",
    address="1539/A1, Kanji Road, Vengikkal, Tiruvannamalai, Tamil Nadu, India",
    map_embed="",
    facebook="",
    youtube="",
    x="",
    linkedin="",
    instagram="",
    hero_title="Empowering Every",
    hero_highlight="Child\u2019s Future",
    hero_text="Join us in providing educational support, mentorship and resources to help children thrive and reach their full potential.",
    about_title="Together for a Better Tomorrow",
    about_text="ASMA Educational and Charitable Trust is committed to promote education, provide social support and bring positive change in society. We believe in the power of education and compassion.",
    history="ASMA Educational and Charitable Trust is a registered public charitable trust based in Vengikkal, Tiruvannamalai, Tamil Nadu. The Trust was founded by S. Sandhiya as Founder and Managing Trustee, together with six trustees from Tiruvannamalai, and is registered with the Sub-Registrar, Tiruvannamalai (Registration No. 37/2025). It works for education, child welfare, healthcare, women empowerment and the welfare of people in need.",
    vision="A society where every child and every family has access to quality education, healthcare and the opportunity to live with dignity.",
    mission="To promote education, provide social support and bring positive change in society through transparent, community-based service to children, women, the elderly and the underprivileged.",
    objectives="\u2022 Support education, scholarships and school and college development\n\u2022 Provide computer, technical and skill development training\n\u2022 Care for children, women and senior citizens\n\u2022 Provide medical and healthcare support to people in need\n\u2022 Promote rural development and social welfare\n\u2022 Offer relief and help in times of disaster",
    chairman_name="S. Sandhiya \u2013 Founder & Managing Trustee",
    chairman_message="",
    registration="Registered Trust \u2013 Registration No. 37/2025, Sub-Registrar Office, Tiruvannamalai\nPAN: AAMTA1285H\nNITI Aayog DARPAN ID: TW/2025/0902021\n80G: Form 10AC provisional approval \u2013 AAMTA1285HF20251 (19-12-2025), valid AY 2026-27 to AY 2028-29\nRegistered address: No. 1539/A, Kanji Main Road, AA Ricemill Opposite, Vengikkal, Tiruvannamalai, Tamil Nadu \u2013 606604",
    achievements="",
    signatory="",
    signatory_title="Authorised Signatory",
    logo="",
    pan="AAMTA1285H",
    reg_no="37/2025",
    darpan="TW/2025/0902021",
    receipt_place="TIRUVANNAMALAI, TAMIL NADU \u2013 606604",
    reg_address="No. 1539/A, Kanji Main Road, AA Ricemill Opposite, Vengikkal, Tiruvannamalai, Tamil Nadu \u2013 606604",
    receipt_email="asmafoundation2025@gmail.com",
    receipt_phone="9787162094",
    signature_img="",
    seal_img="",
    g80_reg="AAMTA1285HF20251",
    g80_date="19-12-2025",
    g80_validity="AY 2026-27 to AY 2028-29",
    g80_form="Form 10AC (provisional approval)",
)
SETTING_GROUPS = [
    (
        "trust",
        "Trust Information",
        [
            ("trust_name", "Trust name", "text"),
            ("tagline", "Tagline", "text"),
            ("location", "Location (short)", "text"),
            ("registration", "Registration details", "textarea"),
            ("logo", "Official Trust logo (used on site and certificates)", "image"),
        ],
    ),
    (
        "contact",
        "Contact & Social Links",
        [
            ("email", "Email", "text"),
            ("phone", "Phone", "text"),
            ("whatsapp", "WhatsApp number (country code, digits only)", "text"),
            ("address", "Full address", "textarea"),
            ("map_embed", "Google Maps embed URL (the src of the iframe)", "text"),
            ("facebook", "Facebook URL", "text"),
            ("youtube", "YouTube URL", "text"),
            ("x", "X (Twitter) URL", "text"),
            ("instagram", "Instagram URL", "text"),
            ("linkedin", "LinkedIn URL", "text"),
        ],
    ),
    (
        "content",
        "Home & About Us Content",
        [
            ("hero_title", "Hero title (white part)", "text"),
            ("hero_highlight", "Hero title (gold part)", "text"),
            ("hero_text", "Hero text", "textarea"),
            ("about_title", "About heading", "text"),
            ("about_text", "About the Trust", "textarea"),
            ("history", "Trust history", "textarea"),
            ("vision", "Vision", "textarea"),
            ("mission", "Mission", "textarea"),
            ("objectives", "Objectives", "textarea"),
            ("chairman_name", "Founder / Chairman name", "text"),
            ("chairman_message", "Founder / Chairman message", "textarea"),
            (
                "achievements",
                "Verified achievements - one per line as Value|Label (leave empty if none)",
                "textarea",
            ),
        ],
    ),
    (
        "cert",
        "Donation Receipt (PDF) details",
        [
            ("pan", "Trust PAN", "text"),
            ("reg_no", "Trust registration number", "text"),
            ("darpan", "NITI Aayog DARPAN ID", "text"),
            ("receipt_place", "Place line under trust name", "text"),
            ("reg_address", "Registered / administrative address (printed on receipt)", "textarea"),
            ("receipt_email", "Email printed on receipt", "text"),
            ("receipt_phone", "Phone printed on receipt", "text"),
            (
                "signatory",
                "Authorised signatory name (optional, printed under the signature)",
                "text",
            ),
            ("signatory_title", "Signatory title", "text"),
            (
                "signature_img",
                "Authorised signatory signature image (optional - replaces default)",
                "image",
            ),
            ("seal_img", "Trust seal image (optional - replaces default)", "image"),
        ],
    ),
    (
        "g80",
        "80G Provisional Approval (Form 10AC)",
        [
            ("g80_form", "Approval type", "text"),
            ("g80_reg", "80G registration number", "text"),
            ("g80_date", "Approval date", "text"),
            ("g80_validity", "Provisional validity", "text"),
        ],
    ),
]
now = lambda: datetime.now().strftime("%Y-%m-%d %H:%M")


def online_enabled():
    """Instant online payment (Razorpay) is offered ONLY when PAYMENT_MODE=razorpay and both Razorpay keys are in .env."""
    return (
        pay_mode() == "razorpay" and bool(E("RAZORPAY_KEY_ID")) and bool(E("RAZORPAY_KEY_SECRET"))
    )


pay_mode = lambda: "razorpay" if E("PAYMENT_MODE", "razorpay") == "razorpay" else "test"

# ---------- 80G workflow ----------
G80_STATUS = [
    ("review", "Under review by the Trust"),
    ("pan_needed", "Donor PAN required"),
    ("eligible", "Verified eligible for 80G reporting"),
    ("pre_arn", "Pre-ARN obtained"),
    ("filed", "Form 10BD filed"),
    ("issued", "Form 10BE issued"),
    ("na", "Acknowledgement only / not applicable"),
]
G80_LABEL = dict(G80_STATUS)
PAN_RE = r"[A-Z]{5}[0-9]{4}[A-Z]"


def fy_label(dt=None):
    dt = dt or datetime.now()
    y = dt.year if dt.month >= 4 else dt.year - 1
    return "%d-%02d" % (y, (y + 1) % 100)


def mask_pan(p):
    return (p[:2] + "*" * 6 + p[-2:]) if p and len(p) == 10 else ""
