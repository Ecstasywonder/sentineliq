"""
Seed data for SentinelIQ MVP.

Loads the v1.0 risk policy, default roles, a demo facility,
locations, cameras, and mock contextual data.

Run via: python -m app.db.seed  (from backend/)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models import (
    Camera,
    Facility,
    IncidentHistory,
    IntegrationHealth,
    Location,
    RiskPolicy,
    RiskPolicyFactor,
    Role,
    SecurityRule,
    User,
    UserRole,
)
from app.security.passwords import hash_password

logger = structlog.get_logger(__name__)


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Seed definitions
# ---------------------------------------------------------------------------
ROLES = [
    {"name": "officer", "description": "Security Monitoring Officer"},
    {"name": "supervisor", "description": "Shift Supervisor"},
    {"name": "response_team", "description": "Response Team Member"},
    {"name": "facility_manager", "description": "Facility Manager"},
    {"name": "security_admin", "description": "Security Administrator"},
    {"name": "audit_reviewer", "description": "Compliance / Audit Reviewer"},
    {"name": "platform_admin", "description": "Platform Administrator"},
    {"name": "agent_admin", "description": "AI / Agent Administrator"},
    {"name": "agent_tool_reader", "description": "Orchestrate read-only tool identity"},
    {"name": "event_ingestor", "description": "Event ingestion service identity"},
]

FACILITY = {
    "id": "fac-001",
    "name": "Sentinel Demo Facility",
    "address": "1 Security Plaza, Demo City",
    "timezone": "America/New_York",
}

LOCATIONS = [
    {
        "id": "loc-001",
        "facility_id": "fac-001",
        "name": "Loading Dock 3",
        "location_code": "LOADING_DOCK_3",
        "zone_type": "restricted",
    },
    {
        "id": "loc-002",
        "facility_id": "fac-001",
        "name": "Main Entrance",
        "location_code": "MAIN_ENTRANCE",
        "zone_type": "standard",
    },
    {
        "id": "loc-003",
        "facility_id": "fac-001",
        "name": "Server Room",
        "location_code": "SERVER_ROOM",
        "zone_type": "high_security",
    },
    {
        "id": "loc-004",
        "facility_id": "fac-001",
        "name": "Car Park Level 1",
        "location_code": "CARPARK_L1",
        "zone_type": "standard",
    },
    {
        "id": "loc-005",
        "facility_id": "fac-001",
        "name": "Roof Access",
        "location_code": "ROOF_ACCESS",
        "zone_type": "restricted",
    },
]

CAMERAS = [
    {
        "id": "cam-001",
        "location_id": "loc-001",
        "camera_code": "CAM-DOCK-03",
        "name": "Dock 3 Camera A",
    },
    {
        "id": "cam-002",
        "location_id": "loc-002",
        "camera_code": "CAM-MAIN-01",
        "name": "Main Entrance Camera",
    },
    {
        "id": "cam-003",
        "location_id": "loc-003",
        "camera_code": "CAM-SRV-01",
        "name": "Server Room Camera",
    },
    {
        "id": "cam-004",
        "location_id": "loc-004",
        "camera_code": "CAM-PKL1-01",
        "name": "Carpark L1 Camera",
    },
    {
        "id": "cam-005",
        "location_id": "loc-005",
        "camera_code": "CAM-ROOF-01",
        "name": "Roof Access Camera",
    },
]

SECURITY_RULES = [
    {
        "id": _id(),
        "facility_id": None,
        "location_id": None,
        "rule_code": "SNTL-SOP-001-HUMAN-REVIEW",
        "rule_type": "standard_operating_procedure",
        "description": (
            "SentinelIQ recommends and humans decide. Operators must review the full evidence "
            "package, treat unavailable sources as uncertainty, and record an authorised human "
            "decision before any operational action."
        ),
        "policy_reference": "SNTL-SOP-001",
    },
    {
        "id": _id(),
        "facility_id": "fac-001",
        "location_id": "LOADING_DOCK_3",
        "rule_code": "SEC-POL-DOCK-001",
        "rule_type": "restricted_hours",
        "description": "Loading Dock 3 is restricted after 21:00 and before 06:00.",
        "restricted_after": "21:00",
        "restricted_before": "06:00",
        "policy_reference": "SEC-POL-DOCK-001",
    },
    {
        "id": _id(),
        "facility_id": "fac-001",
        "location_id": "SERVER_ROOM",
        "rule_code": "SEC-POL-SRV-001",
        "rule_type": "restricted_always",
        "description": "Server room requires explicit authorization at all times.",
        "policy_reference": "SEC-POL-SRV-001",
    },
    {
        "id": _id(),
        "facility_id": "fac-001",
        "location_id": "ROOF_ACCESS",
        "rule_code": "SEC-POL-ROOF-001",
        "rule_type": "restricted_hours",
        "description": "Roof access is restricted after 18:00.",
        "restricted_after": "18:00",
        "restricted_before": "07:00",
        "policy_reference": "SEC-POL-ROOF-001",
    },
]

RISK_POLICY = {
    "id": "pol-001",
    "version": "1.0",
    "name": "Default MVP Policy",
    "description": "Initial risk scoring policy for SentinelIQ MVP.",
    "is_active": True,
    "effective_from": "2026-11-03",
    "thresholds_json": json.dumps(
        {
            "low": {"min": 0, "max": 24},
            "medium": {"min": 25, "max": 49},
            "high": {"min": 50, "max": 74},
            "critical": {"min": 75, "max": None},
        }
    ),
}

RISK_FACTORS = [
    {
        "factor_id": "no_matching_badge",
        "label": "No matching authorised badge",
        "weight": 25.0,
        "direction": "increases_risk",
    },
    {
        "factor_id": "outside_schedule",
        "label": "Activity outside permitted schedule",
        "weight": 20.0,
        "direction": "increases_risk",
    },
    {
        "factor_id": "restricted_area",
        "label": "Restricted location at event time",
        "weight": 25.0,
        "direction": "increases_risk",
    },
    {
        "factor_id": "no_work_order",
        "label": "No approved work order",
        "weight": 15.0,
        "direction": "increases_risk",
    },
    {
        "factor_id": "recent_incidents",
        "label": "Relevant recent incidents",
        "weight": 10.0,
        "direction": "increases_risk",
    },
    {
        "factor_id": "forced_door_alarm",
        "label": "Forced door or security alarm",
        "weight": 40.0,
        "direction": "increases_risk",
    },
    {
        "factor_id": "approved_maintenance",
        "label": "Known approved maintenance",
        "weight": -30.0,
        "direction": "decreases_risk",
    },
    {
        "factor_id": "valid_access_schedule",
        "label": "Valid access and matching schedule",
        "weight": -35.0,
        "direction": "decreases_risk",
    },
]

INCIDENT_HISTORY = [
    {
        "id": _id(),
        "facility_id": "fac-001",
        "location_id": "LOADING_DOCK_3",
        "incident_code": "INC-18",
        "incident_type": "after_hours_presence",
        "severity": "medium",
        "occurred_at": "2026-10-15T23:12:00Z",
        "description": "Unverified activity detected at Loading Dock 3 after 23:00. Security officer investigated and found delivery driver who had arrived early. Situation resolved with no further action.",
        "resolved": True,
        "resolution_notes": "Early delivery — supplier notified to coordinate arrival times.",
    },
    {
        "id": _id(),
        "facility_id": "fac-001",
        "location_id": "LOADING_DOCK_3",
        "incident_code": "INC-29",
        "incident_type": "after_hours_presence",
        "severity": "high",
        "occurred_at": "2026-10-28T22:05:00Z",
        "description": "Person detected at Loading Dock 3 at 22:05. No badge access found. No scheduled delivery. Officer escalated to shift supervisor. Area confirmed clear after physical inspection.",
        "resolved": True,
        "resolution_notes": "Unauthorized access attempt. Supplier access protocol updated.",
    },
    {
        "id": _id(),
        "facility_id": "fac-001",
        "location_id": "SERVER_ROOM",
        "incident_code": "INC-14",
        "incident_type": "unauthorized_access_attempt",
        "severity": "critical",
        "occurred_at": "2026-09-11T14:30:00Z",
        "description": "Tailgating attempt detected at server room entrance. Badge reader triggered without corresponding authorized entry in access log.",
        "resolved": True,
        "resolution_notes": "Physical security review completed. Anti-tailgating measures reinforced.",
    },
]

INTEGRATION_HEALTH_RECORDS = [
    {
        "source_id": "access_control",
        "name": "Access Control System",
        "status": "healthy",
        "adapter_class": "MockAccessControlAdapter",
    },
    {
        "source_id": "schedule",
        "name": "Schedule Service",
        "status": "healthy",
        "adapter_class": "MockScheduleAdapter",
    },
    {
        "source_id": "location_policy",
        "name": "Location Policy Store",
        "status": "healthy",
        "adapter_class": "DatabasePolicyAdapter",
    },
    {
        "source_id": "incident_history",
        "name": "Incident History",
        "status": "healthy",
        "adapter_class": "DatabaseIncidentAdapter",
    },
    {
        "source_id": "work_orders",
        "name": "Work Order System",
        "status": "healthy",
        "adapter_class": "MockWorkOrderAdapter",
    },
    {
        "source_id": "delivery",
        "name": "Delivery Schedule",
        "status": "healthy",
        "adapter_class": "MockDeliveryAdapter",
    },
    {
        "source_id": "visitor",
        "name": "Visitor Management",
        "status": "unknown",
        "adapter_class": "MockVisitorAdapter",
    },
    {
        "source_id": "camera_metadata",
        "name": "Camera Metadata",
        "status": "healthy",
        "adapter_class": "DatabaseCameraAdapter",
    },
]


# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------
async def seed() -> None:
    """Idempotent seed — safe to run multiple times against an existing DB."""
    logger.info("seed.start")

    async with AsyncSessionLocal() as session:
        # Roles
        for r in ROLES:
            existing = await session.scalar(select(Role).where(Role.name == r["name"]))
            if existing is None:
                session.add(Role(id=_id(), **r))
            else:
                existing.description = r["description"]
        await session.commit()
        logger.info("seed.roles_done")

        # Facility
        existing_fac = await session.get(Facility, FACILITY["id"])
        if existing_fac is None:
            session.add(
                Facility(**FACILITY, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
            )
            await session.commit()
        logger.info("seed.facility_done")

        # Locations
        for loc_data in LOCATIONS:
            if await session.get(Location, loc_data["id"]) is None:
                session.add(
                    Location(**loc_data, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
                )
        await session.commit()
        logger.info("seed.locations_done")

        # Cameras
        for cam_data in CAMERAS:
            if await session.get(Camera, cam_data["id"]) is None:
                session.add(
                    Camera(**cam_data, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
                )
        await session.commit()
        logger.info("seed.cameras_done")

        # Security rules — keyed by rule_code (id is random, so check code)
        for rule_data in SECURITY_RULES:
            existing_rule = await session.scalar(
                select(SecurityRule).where(SecurityRule.rule_code == rule_data["rule_code"])
            )
            if existing_rule is None:
                session.add(
                    SecurityRule(
                        **rule_data, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
                    )
                )
        await session.commit()
        logger.info("seed.security_rules_done")

        # Risk policy
        if await session.get(RiskPolicy, RISK_POLICY["id"]) is None:
            session.add(
                RiskPolicy(
                    **RISK_POLICY, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
                )
            )
            await session.commit()

            for f in RISK_FACTORS:
                session.add(
                    RiskPolicyFactor(
                        id=_id(),
                        policy_id="pol-001",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                        **f,
                    )
                )
            await session.commit()
        logger.info("seed.risk_policy_done")

        # Incident history — keyed by incident_code
        for inc_data in INCIDENT_HISTORY:
            existing_inc = await session.scalar(
                select(IncidentHistory).where(
                    IncidentHistory.incident_code == inc_data["incident_code"]
                )
            )
            if existing_inc is None:
                session.add(
                    IncidentHistory(
                        **inc_data, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
                    )
                )
        await session.commit()
        logger.info("seed.incident_history_done")

        # Integration health — keyed by source_id
        for ih_data in INTEGRATION_HEALTH_RECORDS:
            existing_ih = await session.scalar(
                select(IntegrationHealth).where(IntegrationHealth.source_id == ih_data["source_id"])
            )
            if existing_ih is None:
                session.add(
                    IntegrationHealth(
                        id=_id(),
                        **ih_data,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
        await session.commit()
        logger.info("seed.integration_health_done")

        # Demo operator account — idempotent, only created if email is absent
        demo_email = "demo@sentineliq.dev"
        demo_password = "SentinelIQ-Demo-2026"
        demo_role_name = "officer"
        existing_demo = await session.scalar(select(User).where(User.email == demo_email))
        if existing_demo is None:
            demo_user = User(
                email=demo_email,
                full_name="Demo Operator",
                hashed_password=hash_password(demo_password),
                is_active=True,
                is_verified=True,
            )
            session.add(demo_user)
            await session.flush()  # get demo_user.id

            demo_role = await session.scalar(select(Role).where(Role.name == demo_role_name))
            if demo_role:
                session.add(
                    UserRole(user_id=demo_user.id, role_id=demo_role.id, granted_by="system:seed")
                )
            await session.commit()
            logger.info("seed.demo_user_created", email=demo_email)
        else:
            logger.info("seed.demo_user_already_exists", email=demo_email)

    logger.info("seed.complete")


if __name__ == "__main__":
    asyncio.run(seed())
