"""Tracks which user is making the current change.

The middleware sets this for every web request. Scripts, management commands and
tests can call ``set_current_user`` themselves. Only the user id is stored, so no
database query is needed to resolve it.
"""

from contextvars import ContextVar

_current_user_id = ContextVar("current_user_id", default=None)


def set_current_user(user):
    """Set the acting user (or None). Returns a token for ``reset_current_user``."""
    user_id = None
    if user is not None and getattr(user, "is_authenticated", False):
        user_id = user.pk
    return _current_user_id.set(user_id)


def reset_current_user(token):
    _current_user_id.reset(token)


def get_current_user_id():
    return _current_user_id.get()
