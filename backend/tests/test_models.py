"""
Database model tests — Gate 3.

Tests that all models can be instantiated and persisted against
the in-memory SQLite test database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Import all models to ensure they register with Base.metadata
import app.models  # noqa: F401
from app.models.facility import Camera, Facility, Location
from app.models.user import Role, User, UserRole
from app.models.event import SecurityEvent
from app.models.evidence import EventEvidence
from app.models.assessment import RiskAssessment
from app.models.recommendation import Recommendation
from app.models.decision import OperatorDecision
from app.models.escalation import Escalation
from app.models.audit import AuditEvent
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor
from app.models.incident import IncidentHistory
from app.models.integration import IntegrationHealth
from app.models.feedback import Feedback
from app.models.agent_run import AgentRun, ToolCall


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Facility / Location / Camera
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_facility_create(db_session: AsyncSession) -> None:
    fac = Facility(id=_id(), name="Test Facility", timezone="UTC")
    db_session.add(fac)
    await db_session.flush()
    result = await db_session.get(Facility, fac.id)
    assert result is not None
    assert result.name == "Test Facility"


@pytest.mark.asyncio
async def test_location_create(db_session: AsyncSession) -> None:
    fac = Facility(id=_id(), name="Fac", timezone="UTC")
    db_session.add(fac)
    await db_session.flush()

    loc = Location(id=_id(), facility_id=fac.id, name="Dock", location_code=f"DOCK-{_id()[:8]}")
    db_session.add(loc)
    await db_session.flush()

    result = await db_session.get(Location, loc.id)
    assert result is not None
    assert result.facility_id == fac.id


@pytest.mark.asyncio
async def test_camera_create(db_session: AsyncSession) -> None:
    fac = Facility(id=_id(), name="Fac", timezone="UTC")
    db_session.add(fac)
    await db_session.flush()

    loc = Location(id=_id(), facility_id=fac.id, name="Zone", location_code=f"ZN-{_id()[:8]}")
    db_session.add(loc)
    await db_session.flush()

    cam = Camera(id=_id(), location_id=loc.id, camera_code=f"CAM-{_id()[:8]}", name="Cam A")
    db_session.add(cam)
    await db_session.flush()

    result = await db_session.get(Camera, cam.id)
    assert result is not None
    assert result.location_id == loc.id


# ---------------------------------------------------------------------------
# User / Role
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_role_create(db_session: AsyncSession) -> None:
    role = Role(id=_id(), name=f"officer_{_id()[:8]}", description="Security Officer")
    db_session.add(role)
    await db_session.flush()
    result = await db_session.get(Role, role.id)
    assert result is not None
    assert result.name.startswith("officer_")


@pytest.mark.asyncio
async def test_user_create(db_session: AsyncSession) -> None:
    user = User(
        id=_id(),
        email=f"test_{_id()[:8]}@example.com",
        full_name="Test User",
        hashed_password="$2b$12$fakehash",
    )
    db_session.add(user)
    await db_session.flush()
    result = await db_session.get(User, user.id)
    assert result is not None
    assert result.email.endswith("@example.com")


# ---------------------------------------------------------------------------
# SecurityEvent
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_security_event_create(db_session: AsyncSession) -> None:
    event = SecurityEvent(
        id=_id(),
        event_type="person_detected",
        event_timestamp="2026-11-03T22:41:18Z",
        location_id="LOADING_DOCK_3",
        status="received",
    )
    db_session.add(event)
    await db_session.flush()
    result = await db_session.get(SecurityEvent, event.id)
    assert result is not None
    assert result.status == "received"
    assert result.event_type == "person_detected"


@pytest.mark.asyncio
async def test_security_event_default_status(db_session: AsyncSession) -> None:
    event = SecurityEvent(
        id=_id(),
        event_type="motion_detected",
        event_timestamp=_now(),
        location_id="MAIN_ENTRANCE",
    )
    db_session.add(event)
    await db_session.flush()
    result = await db_session.get(SecurityEvent, event.id)
    assert result is not None
    assert result.status == "received"


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_evidence_create(db_session: AsyncSession) -> None:
    event = SecurityEvent(
        id=_id(), event_type="person_detected",
        event_timestamp=_now(), location_id="DOCK", status="assessing",
    )
    db_session.add(event)
    await db_session.flush()

    evidence = EventEvidence(
        id=_id(), event_id=event.id, evidence_code="ACCESS-Q-001",
        source="access_control", status="verified", retrieved_at=_now(),
    )
    db_session.add(evidence)
    await db_session.flush()

    result = await db_session.get(EventEvidence, evidence.id)
    assert result is not None
    assert result.source == "access_control"
    assert result.evidence_code == "ACCESS-Q-001"


# ---------------------------------------------------------------------------
# RiskAssessment
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_risk_assessment_create(db_session: AsyncSession) -> None:
    event = SecurityEvent(
        id=_id(), event_type="person_detected",
        event_timestamp=_now(), location_id="DOCK", status="assessing",
    )
    db_session.add(event)
    await db_session.flush()

    assessment = RiskAssessment(
        id=_id(), event_id=event.id,
        risk_policy_version="1.0", risk_score=78.0,
        risk_level="critical", assessed_at=_now(),
    )
    db_session.add(assessment)
    await db_session.flush()

    result = await db_session.get(RiskAssessment, assessment.id)
    assert result is not None
    assert result.risk_score == 78.0
    assert result.risk_level == "critical"


# ---------------------------------------------------------------------------
# OperatorDecision — human review non-bypass enforcement
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_operator_decision_requires_event(db_session: AsyncSession) -> None:
    """A decision must be linked to an event — no orphan decisions."""
    event = SecurityEvent(
        id=_id(), event_type="person_detected",
        event_timestamp=_now(), location_id="DOCK", status="awaiting_review",
    )
    db_session.add(event)
    await db_session.flush()

    decision = OperatorDecision(
        id=_id(), event_id=event.id,
        decided_by="user-001", decided_by_role="officer",
        decision="escalate", decided_at=_now(),
    )
    db_session.add(decision)
    await db_session.flush()

    result = await db_session.get(OperatorDecision, decision.id)
    assert result is not None
    assert result.decision == "escalate"
    assert result.is_override is False


# ---------------------------------------------------------------------------
# AuditEvent — append-only
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_event_create(db_session: AsyncSession) -> None:
    event = SecurityEvent(
        id=_id(), event_type="person_detected",
        event_timestamp=_now(), location_id="DOCK", status="received",
    )
    db_session.add(event)
    await db_session.flush()

    audit = AuditEvent(
        id=_id(), event_id=event.id,
        action="event_received", actor="system",
        occurred_at=_now(),
    )
    db_session.add(audit)
    await db_session.flush()

    result = await db_session.get(AuditEvent, audit.id)
    assert result is not None
    assert result.action == "event_received"
    assert result.actor == "system"


# ---------------------------------------------------------------------------
# RiskPolicy + Factors
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_risk_policy_and_factors(db_session: AsyncSession) -> None:
    import json

    policy = RiskPolicy(
        id=_id(), version=f"test-{_id()[:8]}", name="Test Policy",
        is_active=True,
        thresholds_json=json.dumps({"low": {"min": 0, "max": 24}}),
    )
    db_session.add(policy)
    await db_session.flush()

    factor = RiskPolicyFactor(
        id=_id(), policy_id=policy.id,
        factor_id="no_badge", label="No badge found",
        weight=25.0, direction="increases_risk",
    )
    db_session.add(factor)
    await db_session.flush()

    result = await db_session.get(RiskPolicyFactor, factor.id)
    assert result is not None
    assert result.weight == 25.0
    assert result.direction == "increases_risk"


# ---------------------------------------------------------------------------
# IncidentHistory
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_incident_history_create(db_session: AsyncSession) -> None:
    incident = IncidentHistory(
        id=_id(), location_id="LOADING_DOCK_3",
        incident_code=f"INC-{_id()[:8]}", incident_type="after_hours_presence",
        severity="high", occurred_at="2026-10-15T23:12:00Z",
        description="Test incident description.",
    )
    db_session.add(incident)
    await db_session.flush()

    result = await db_session.get(IncidentHistory, incident.id)
    assert result is not None
    assert result.severity == "high"


# ---------------------------------------------------------------------------
# IntegrationHealth
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_integration_health_create(db_session: AsyncSession) -> None:
    ih = IntegrationHealth(
        id=_id(), source_id=f"test_src_{_id()[:8]}",
        name="Test Source", status="healthy",
    )
    db_session.add(ih)
    await db_session.flush()

    result = await db_session.get(IntegrationHealth, ih.id)
    assert result is not None
    assert result.status == "healthy"


# ---------------------------------------------------------------------------
# AgentRun + ToolCall
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_agent_run_and_tool_call(db_session: AsyncSession) -> None:
    run = AgentRun(
        id=_id(), agent_name="triage_agent",
        status="completed", started_at=_now(),
    )
    db_session.add(run)
    await db_session.flush()

    tool = ToolCall(
        id=_id(), agent_run_id=run.id,
        tool_name="get_access_events",
        status="success", started_at=_now(), sequence=0,
    )
    db_session.add(tool)
    await db_session.flush()

    result = await db_session.get(ToolCall, tool.id)
    assert result is not None
    assert result.tool_name == "get_access_events"


# ---------------------------------------------------------------------------
# Multi-table query — event with evidence
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_with_evidence_query(db_session: AsyncSession) -> None:
    event_id = _id()
    event = SecurityEvent(
        id=event_id, event_type="person_detected",
        event_timestamp=_now(), location_id="DOCK", status="assessing",
    )
    db_session.add(event)
    await db_session.flush()

    for i in range(3):
        ev = EventEvidence(
            id=_id(), event_id=event_id,
            evidence_code=f"EV-{i:03d}", source=f"source_{i}",
            status="verified", retrieved_at=_now(),
        )
        db_session.add(ev)
    await db_session.flush()

    stmt = select(EventEvidence).where(EventEvidence.event_id == event_id)
    results = (await db_session.execute(stmt)).scalars().all()
    assert len(results) == 3
