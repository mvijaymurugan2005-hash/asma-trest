"""File uploads into uploads/<Folder>/."""

import os, uuid
from flask import flash
from .config import UP


def save(fs, allowed, folder):
    if not fs or not fs.filename:
        return None
    ext = fs.filename.rsplit(".", 1)[-1].lower() if "." in fs.filename else ""
    if ext not in allowed:
        flash("File type not allowed: " + fs.filename, "err")
        return None
    n = "%s/%s.%s" % (folder, uuid.uuid4().hex, ext)
    fs.save(os.path.join(UP, n))
    return n


def rmfile(n):
    if n:
        p = os.path.abspath(os.path.join(UP, n))
        if p.startswith(os.path.abspath(UP) + os.sep) and os.path.isfile(p):
            os.remove(p)
