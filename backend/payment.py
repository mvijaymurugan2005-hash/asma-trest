"""Razorpay integration (server side only)."""

import hmac, json, base64, hashlib, urllib.request
from .config import E


def rzp(path, payload):
    auth = base64.b64encode(
        ("%s:%s" % (E("RAZORPAY_KEY_ID"), E("RAZORPAY_KEY_SECRET"))).encode()
    ).decode()
    req = urllib.request.Request(
        "https://api.razorpay.com/v1/" + path,
        json.dumps(payload).encode(),
        {"Content-Type": "application/json", "Authorization": "Basic " + auth},
    )
    return json.load(urllib.request.urlopen(req, timeout=20))


def valid_payment(order_id, payment_id, signature):
    sig = hmac.new(
        E("RAZORPAY_KEY_SECRET").encode(),
        ("%s|%s" % (order_id, payment_id)).encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, signature or "")


def valid_webhook(body, signature):
    sec = E("RAZORPAY_WEBHOOK_SECRET")
    return bool(sec) and hmac.compare_digest(
        hmac.new(sec.encode(), body, hashlib.sha256).hexdigest(), signature or ""
    )


def rzp_get(path):
    auth = base64.b64encode(
        ("%s:%s" % (E("RAZORPAY_KEY_ID"), E("RAZORPAY_KEY_SECRET"))).encode()
    ).decode()
    req = urllib.request.Request(
        "https://api.razorpay.com/v1/" + path, headers={"Authorization": "Basic " + auth}
    )
    return json.load(urllib.request.urlopen(req, timeout=15))
