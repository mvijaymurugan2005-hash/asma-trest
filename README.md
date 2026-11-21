# ASMA Educational and Charitable Trust – Website

Python (Flask) + SQLite + ReportLab. Public website, admin dashboard, Razorpay donations (UPI/cards/net banking), automatic PDF certificates with QR verification, email.

## Folder structure
```
ASMA-TRUST-WEBSITE/
├── frontend/                 public website
│   ├── pages/                home, about, activities, projects, project (details), gallery,
│   │                         donate (Donation), verify (Certificate Verification), contact, receipt
│   └── static/               style.css, admin.css, images (developer logo), optional fonts/
├── admin/                    admin panel pages
│   ├── login, dash (Dashboard), list + form (Manage Activities / Projects / Gallery / Members / Banners),
│   ├── donations, certs, messages, settings, password, reports
├── backend/
│   ├── app.py                routes + admin CRUD
│   ├── authentication.py     CSRF + admin guard (password hashing, login rate-limit in app.py)
│   ├── database.py / config.py   SQLite schema + settings / paths and constants
│   ├── payment.py            Razorpay orders + signature verification
│   ├── pdf_generator.py      certificate numbering + PDF
│   ├── qr_verification.py    QR code + verification lookup
│   ├── email_service.py      SMTP email with certificate attached
│   └── uploads.py            safe file uploads
├── uploads/                  Logo, Banners, Activities, Projects, Gallery, Documents (certificates in Documents/certificates)
├── database/                 created on first run (asma.db)
├── run.py   Procfile   requirements.txt   .env.example
```

## Run on your computer
```
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # edit values (keep PAYMENT_MODE=test while developing)
python run.py              # open http://localhost:5000
```
Admin: http://localhost:5000/admin (username/password from `.env`; if ADMIN_PASSWORD is empty a random one is printed in the console on first start).

## First steps in Admin
1. **Website Settings** – upload the official ASMA logo, set address, phone, WhatsApp, email, Google Maps embed URL, social links, vision/mission, registration details, signatory name.
2. **Home Banner** – upload genuine photos. 3. **Activities / Projects / Gallery / Trustees** – add real content. Projects stay hidden until "Published" is ticked.
Everything saves to the database and shows on the public site immediately.

## Live payments (Razorpay)
1. Create a Razorpay account and complete KYC. UPI is enabled in Razorpay Dashboard → Payment Methods.
2. Put `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` in `.env` (server only), set `PAYMENT_MODE=razorpay`.
3. Dashboard → Webhooks: URL `https://YOUR-DOMAIN/webhook/razorpay`, event `payment.captured`, set a secret and copy it to `RAZORPAY_WEBHOOK_SECRET`.
4. Test with Razorpay *test keys* first. The certificate is issued only after the server verifies the payment signature.

## Deploy (Linux VPS, Render, Railway…)
- Start command: `gunicorn backend.app:app --bind 0.0.0.0:$PORT --workers 2` (Procfile included).
- Set the variables from `.env.example` on the host; `BASE_URL` = your https domain (needed for QR links).
- Mount a **persistent disk** and set `DATA_DIR` to it (database/ and uploads/ live there), otherwise data is lost on redeploy.
- Use HTTPS (Nginx + Let's Encrypt). Upload limit is 200 MB; in Nginx set `client_max_body_size 200m;`.
- Use Admin → Reports & Backup regularly and keep backups off the server.

## Notes
- No 80G/tax-exemption claim anywhere; the certificate says no tax exemption is claimed.
- Tamil donor names in PDFs need a Unicode font at `frontend/static/fonts/NotoSans-Regular.ttf`.
- Members' photos are stored in `uploads/Gallery`.

## Old UPI QR payments (removed from the public site)
The Donate page now offers **only Razorpay online payment** (UPI, cards, net banking through Razorpay Checkout). The manual
"scan QR, enter UTR, upload screenshot" flow, the QR image and `/api/upi/submit` were removed. Historical UPI QR donations,
UTRs, screenshots and receipts are kept untouched and stay visible in Admin (Donations > filter channel "upi_qr"). Any old
donation still *pending* can still be verified or rejected by the admin.
