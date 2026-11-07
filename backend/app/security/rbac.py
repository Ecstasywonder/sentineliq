"""
RBAC permission model — Gate 6.

Maps role names to sets of permission strings.
Permissions are checked at route level via the require_permission dependency.

Permission strings follow the pattern: <resource>:<action>
  events:read        -- view events and their assessments
  events:ingest      -- POST new events (system / integration role)
  events:decide      -- make operator decisions (accept/dismiss/close)
  events:escalate    -- escalate events
  events:override    -- override a prior decision (supervisor+)
  audit:read         -- view audit trail
  admin:users        -- manage users and roles
  admin:policy       -- manage risk policies
  admin:agents       -- manage agent configuration
"""

from __future__ import annotations

# Role -> permissions granted
_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "officer": frozenset(
        {
            "events:read",
            "events:decide",
            "events:escalate",
            "tools:read",
        }
    ),
    "supervisor": frozenset(
        {
            "events:read",
            "events:decide",
            "events:escalate",
            "events:override",
            "events:respond",
            "audit:read",
            "tools:read",
        }
    ),
    "response_team": frozenset(
        {
            "events:read",
            "events:respond",
            "tools:read",
        }
    ),
    "facility_manager": frozenset(
        {
            "events:read",
            "audit:read",
            "tools:read",
        }
    ),
    "security_admin": frozenset(
        {
            "events:read",
            "events:ingest",
            "events:decide",
            "events:escalate",
            "events:override",
            "events:respond",
            "audit:read",
            "admin:policy",
            "tools:read",
        }
    ),
    "audit_reviewer": frozenset(
        {
            "events:read",
            "audit:read",
            "tools:read",
        }
    ),
    "platform_admin": frozenset(
        {
            "events:read",
            "events:ingest",
            "events:decide",
            "events:escalate",
            "events:override",
            "events:respond",
            "audit:read",
            "admin:users",
            "admin:policy",
            "admin:agents",
            "tools:read",
        }
    ),
    "agent_admin": frozenset(
        {
            "events:read",
            "audit:read",
            "admin:agents",
            "tools:read",
        }
    ),
    "agent_tool_reader": frozenset({"tools:read"}),
    "event_ingestor": frozenset({"events:ingest"}),
}

SERVICE_PURPOSE_POLICIES: dict[str, tuple[str, frozenset[str]]] = {
    "orchestrate_tools": ("agent_tool_reader", frozenset({"tools:read"})),
    "event_ingestion": ("event_ingestor", frozenset({"events:ingest"})),
}


def permissions_for_roles(roles: list[str]) -> frozenset[str]:
    """Return the union of permissions for a list of role names."""
    result: set[str] = set()
    for role in roles:
        result |= _ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(result)


def has_permission(roles: list[str], permission: str) -> bool:
    """Return True if any of *roles* grants *permission*."""
    return permission in permissions_for_roles(roles)


def service_purpose_allows(purpose: str, roles: list[str], permission: str) -> bool:
    """Apply the immutable upper bound carried by a service-purpose token.

    Database role changes can revoke a service token, but cannot expand it
    beyond the purpose signed into the token.
    """
    policy = SERVICE_PURPOSE_POLICIES.get(purpose)
    if policy is None:
        return False
    required_role, allowed_permissions = policy
    return required_role in roles and permission in allowed_permissions
