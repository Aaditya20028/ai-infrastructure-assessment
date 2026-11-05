"""Verify opaque configured tokens before deriving any role."""

import hmac

from .config import Role, Settings


class AuthenticationError(Exception):
    pass


def authenticate(headers: list[str], settings: Settings) -> Role:
    if len(headers) != 1:
        raise AuthenticationError
    parts = headers[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].isascii():
        raise AuthenticationError
    role = None
    # Scan all entries instead of early-returning a matching credential.
    for token, configured_role in settings.token_roles.items():
        if hmac.compare_digest(parts[1], token):
            role = configured_role
    if role is None:
        raise AuthenticationError
    return role
