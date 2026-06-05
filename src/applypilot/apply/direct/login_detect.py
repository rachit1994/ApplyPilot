"""Detect when a Direct Apply page is a login/auth wall (pause for human login).

Conservative on purpose: a job page that merely mentions "log in" must NOT
trigger a pause. We only call it a login wall when the signal is strong — a
password field with no real application form, an auth URL path, or an explicit
"sign in to apply / you must be logged in" phrase.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# URL path/host signals of an auth wall.
_LOGIN_URL_RE = re.compile(
    r"(?:^|/)(?:login|log-in|signin|sign-in|sign_in|auth|authenticate|"
    r"sso|session/new|users/sign_in|account/login|accounts/login)(?:/|\?|$)",
    re.I,
)

# High-precision phrases that mean "you must authenticate to continue/apply".
_LOGIN_TEXT_MARKERS: tuple[str, ...] = (
    "sign in to apply",
    "log in to apply",
    "login to apply",
    "please sign in to continue",
    "please log in to continue",
    "you must be logged in",
    "you need to be signed in",
    "sign in to your account to apply",
    "create an account to apply",
    "log in to your account",
    "sign in to continue your application",
)

_GOOGLE_SIGNIN_MARKERS: tuple[str, ...] = (
    "sign in with google",
    "signin with google",
    "continue with google",
    "login with google",
    "log in with google",
    "accounts.google.com",
    "google-signin",
    "google_signin",
    "google oauth",
)


def login_domain(url: str | None) -> str:
    """Host (sans www) used as the login-gate key, e.g. 'naukri.com'."""
    if not url:
        return ""
    host = urlsplit(str(url)).netloc.lower()
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def url_looks_like_login(url: str | None) -> bool:
    if not url:
        return False
    parts = urlsplit(str(url))
    return bool(_LOGIN_URL_RE.search(parts.path) or _LOGIN_URL_RE.search(parts.query))


def detect_login_required(
    url: str | None,
    *,
    body_text: str | None = None,
    has_password_field: bool = False,
    application_field_count: int = 0,
) -> bool:
    """True when the page is a login wall blocking the application.

    Signals (any one is enough, but the password signal is qualified to avoid
    firing on apply forms that legitimately collect a password):
      * a password field AND no real application form (< 3 fillable fields)
      * an auth-looking URL with no application form
      * an explicit "sign in to apply" style phrase
    """
    blob = (body_text or "").lower()
    if any(marker in blob for marker in _LOGIN_TEXT_MARKERS):
        return True
    no_form = application_field_count < 3
    if has_password_field and no_form:
        return True
    if url_looks_like_login(url) and no_form:
        return True
    return False


def has_google_signin(body_text: str | None = None, *, html: str | None = None) -> bool:
    """True when the auth wall offers Google sign-in/OAuth."""
    blob = f"{body_text or ''}\n{html or ''}".lower()
    return any(marker in blob for marker in _GOOGLE_SIGNIN_MARKERS)
