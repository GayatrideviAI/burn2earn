from .current_user import reset_current_user, set_current_user


class CurrentUserMiddleware:
    """Makes the logged-in user available to model saves and the audit log."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_user(getattr(request, "user", None))
        try:
            return self.get_response(request)
        finally:
            reset_current_user(token)
