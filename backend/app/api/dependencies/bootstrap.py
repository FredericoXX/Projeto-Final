from fastapi import Header

from app.core.config import settings
from app.core.exceptions import AuthenticationError

BOOTSTRAP_TOKEN_HEADER = "X-Bootstrap-Token"


def require_bootstrap_token(x_bootstrap_token: str | None = Header(default=None)) -> None:
    """Gates bootstrap-only endpoints — creating an institution, registering
    its first admin, and (de)activating an institution via
    PATCH /bootstrap/institutions/{id}/status — until a real platform_admin
    role exists. A missing or misconfigured BOOTSTRAP_TOKEN fails closed
    rather than leaving the endpoint open."""
    if not settings.bootstrap_token or x_bootstrap_token != settings.bootstrap_token:
        raise AuthenticationError("Invalid or missing bootstrap token.")
