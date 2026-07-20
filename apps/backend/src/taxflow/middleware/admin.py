"""Admin-token guard for the operator-global ``/admin/*`` endpoints (Task 2b).

Unlike the per-client routers (which authenticate via ``get_current_client`` and
scope every query by ``client_id``), the admin endpoints expose operator-global
aggregates and are gated by a single shared secret in the ``X-Admin-Token``
header, compared with :func:`secrets.compare_digest` against
``settings.ADMIN_API_TOKEN``.

Decision #2484:
  - Token UNSET (``ADMIN_API_TOKEN == ""``) → the feature is disabled: return
    **404** so the endpoints are invisible (never leak that they exist).
  - Token set but the header is missing/mismatched → **401**.
"""

import secrets

from fastapi import HTTPException, Request

from taxflow.config import settings


async def require_admin(request: Request) -> None:
    """FastAPI dependency enforcing the admin token. 404 when the feature is
    disabled (token unset), 401 on a missing/incorrect ``X-Admin-Token``."""
    expected = settings.ADMIN_API_TOKEN
    if not expected:
        # Feature disabled — the endpoint should look like it doesn't exist.
        raise HTTPException(status_code=404, detail="Not Found")

    provided = request.headers.get("x-admin-token", "")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token")
