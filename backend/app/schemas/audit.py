"""
Pydantic schemas for the Audit Trail API — Gate 12.

The audit trail is INSERT-only.  These schemas are read-only views.
"""

from __future__ import annotations

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    """Single immutable audit trail entry."""

    audit_id: str
    event_id: str | None
    action: str
    actor: str
    actor_role: str | None
    occurred_at: str
    details: dict | None   # deserialised from details_json; None if not present
    redacted: bool


class AuditListResponse(BaseModel):
    """Paginated list of audit entries."""

    items: list[AuditEntryResponse]
    total: int
    page: int
    page_size: int
    pages: int
