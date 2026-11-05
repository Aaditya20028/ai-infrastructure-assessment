import hashlib
import hmac

from .models import Settings


def authenticate(headers: list[str], settings: Settings) -> str | None:
    if len(headers) != 1:
        return None
    parts = headers[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].isascii():
        return None
    tenant = None
    for key, configured_tenant in settings.api_keys.items():
        if hmac.compare_digest(parts[1], key):
            tenant = configured_tenant
    return hashlib.sha256(("task4:" + tenant).encode()).hexdigest() if tenant is not None else None
