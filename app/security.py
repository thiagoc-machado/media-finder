"""Session-backed CSRF protection for state-changing browser requests."""

import hmac
import secrets

from starlette.requests import Request

CSRF_SESSION_KEY = "_csrf_token"


def get_csrf_token(request: Request) -> str:
    """Return the per-session token, creating it lazily on the first page view."""

    token = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token(request: Request, supplied_token: str | None) -> bool:
    """Compare a submitted token in constant time."""

    expected = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(expected, str) or not isinstance(supplied_token, str):
        return False
    return hmac.compare_digest(expected, supplied_token)
