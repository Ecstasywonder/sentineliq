"""Top-level API v1 router — mounts all resource routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import audit as audit_router
from app.api.v1.endpoints import auth as auth_router
from app.api.v1.endpoints import decisions as decisions_router
from app.api.v1.endpoints import escalations as escalations_router
from app.api.v1.endpoints import events as events_router
from app.api.v1.endpoints import feedback as feedback_router
from app.api.v1.endpoints import health as health_router
from app.api.v1.endpoints import risk_policies as risk_policies_router
from app.api.v1.endpoints import tools as tools_router

api_v1_router = APIRouter()

# Health sub-router (additional API-level health detail)
api_v1_router.include_router(
    health_router.router,
    prefix="/system",
    tags=["System"],
)

# Auth — login, refresh, me
api_v1_router.include_router(
    auth_router.router,
    prefix="/auth",
    tags=["Auth"],
)

# Events — ingestion, queue, lifecycle, assessment (Gates 5, 8, 9)
api_v1_router.include_router(
    events_router.router,
    prefix="/events",
    tags=["Events"],
)

# Operator Decisions — record & retrieve human decisions (Gate 10)
# Mounted under /events so paths resolve to /events/{id}/decision(s)
api_v1_router.include_router(
    decisions_router.router,
    prefix="/events",
    tags=["Decisions"],
)

# Escalations — create, retrieve, update escalation records (Gate 11)
api_v1_router.include_router(
    escalations_router.router,
    prefix="/events",
    tags=["Escalations"],
)

# Audit Trail — read-only audit log (Gate 12)
# Routes: /api/v1/events/{id}/audit  and  /api/v1/audit
api_v1_router.include_router(
    audit_router.router,
    prefix="",
    tags=["Audit"],
)

# Feedback — operator quality feedback (Gate 13)
api_v1_router.include_router(
    feedback_router.router,
    prefix="/events",
    tags=["Feedback"],
)

# Context tools — evidence retrieval (Gate 7, ADR-005 read-only adapters)
api_v1_router.include_router(
    tools_router.router,
    prefix="/tools",
    tags=["Tools"],
)

# Risk Policies — read-only policy & factor inspection (Gate 9)
api_v1_router.include_router(
    risk_policies_router.router,
    prefix="/risk-policies",
    tags=["Risk Policies"],
)
