"""Fixed-role, code-defined RBAC permission matrix (Phase 1).

Three roles (Owner/Reviewer/Staff), a small hardcoded permission set. This is
deliberately NOT a dynamic/DB-driven roles-and-permissions system - the
product decision was fixed roles with a code-defined matrix, since a 2-3
person firm doesn't need custom roles, and this is far simpler to reason
about and test. Adding a new permission or role is a code change + deploy.

Pure module, no I/O - safe to import from anywhere (middleware, routers,
tests) without pulling in the DB layer.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    REVIEWER = "reviewer"
    STAFF = "staff"


# Which roles hold each permission. A permission not listed here is granted to
# no one (has_permission returns False), so a typo'd permission name fails
# closed rather than silently allowing everyone.
PERMISSIONS: dict[str, set[Role]] = {
    "billing.manage": {Role.OWNER},
    "staff.manage": {Role.OWNER},
    "documents.approve": {Role.OWNER, Role.REVIEWER},
    "ato_response.approve": {Role.OWNER, Role.REVIEWER},
    "verification.resolve": {Role.OWNER, Role.REVIEWER},
    "work.delete_any": {Role.OWNER},
    "query.ask": {Role.OWNER, Role.REVIEWER, Role.STAFF},
    "documents.draft": {Role.OWNER, Role.REVIEWER, Role.STAFF},
}


def has_permission(role: str, permission: str) -> bool:
    """Whether ``role`` (a raw string, e.g. from a ``users.role`` DB column)
    holds ``permission``. Unknown role strings and unknown permission names
    both fail closed (False), never raise."""
    try:
        role_enum = Role(role)
    except ValueError:
        return False
    return role_enum in PERMISSIONS.get(permission, set())
