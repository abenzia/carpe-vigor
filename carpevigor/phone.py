"""Pairing a phone with a QR code, so nobody types an address or a secret.

The diary page, opened at this computer, shows a QR code. It holds a one-time pairing code (valid 10 minutes, one use),
not the long-lived token: the code is in the address, so it ends up in logs; the token never does. Scanning it opens
/m/pair/<code> on the phone, which sets an HttpOnly cookie and from then on /m, a page made for the phone ("What are
you eating?", with the keyboard's microphone), writes into the diary like the watch's shortcut does.
"""
from __future__ import annotations

import io
import secrets
import threading
import time

import qrcode
import qrcode.image.svg

VALID_SECONDS = 600
COOKIE = "cv_phone"
_codes: dict[str, float] = {}
_lock = threading.Lock()


def new_code() -> str:
    code = secrets.token_urlsafe(9)
    now = time.time()
    with _lock:
        for c, until in list(_codes.items()):
            if until < now:
                del _codes[c]
        _codes[code] = now + VALID_SECONDS
    return code


def take(code: str) -> bool:
    """True once for a code still valid; the code is gone after."""
    with _lock:
        until = _codes.pop(code, None)
    return until is not None and until >= time.time()


def qr_svg(text: str) -> str:
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    out = io.BytesIO()
    image.save(out)
    svg = out.getvalue().decode("utf-8")
    return svg[svg.index("<svg"):]   # inline in the page: no XML declaration
