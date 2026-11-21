"""CSRF protection and admin login guard."""

import secrets
from functools import wraps
from flask import session, redirect, url_for, request


def csrf():
    if "_c" not in session:
        session["_c"] = secrets.token_hex(16)
    return session["_c"]


def admin(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("aid"):
            return redirect(
                url_for("login", next=request.full_path if request.query_string else request.path)
            )
        return f(*a, **k)

    return w
