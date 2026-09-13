"""Domain exceptions mapped to HTTP responses in ``app.main``."""

from __future__ import annotations


class FleetBeatError(Exception):
    """Base class for expected, user-facing failures."""

    status_code = 400
    code = "error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(FleetBeatError):
    status_code = 404
    code = "not_found"


class ConflictError(FleetBeatError):
    status_code = 409
    code = "conflict"


class ValidationError(FleetBeatError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(FleetBeatError):
    status_code = 401
    code = "authentication_failed"


class PermissionDeniedError(FleetBeatError):
    status_code = 403
    code = "permission_denied"


class PasswordChangeRequiredError(FleetBeatError):
    """The account must set a new password before it can do anything else.

    Section 4a requires a seeded or reset account to change its password on
    first login. Enforcing that only in the UI would leave the temporary
    password valid against the API forever.
    """

    status_code = 403
    code = "password_change_required"


class RateLimitedError(FleetBeatError):
    status_code = 429
    code = "rate_limited"
