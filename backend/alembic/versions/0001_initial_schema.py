"""
Initial SentinelIQ database schema — Gate 3.

Creates all 23 domain tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # facilities
    # ------------------------------------------------------------------
    op.create_table(
        "facilities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # locations
    # ------------------------------------------------------------------
    op.create_table(
        "locations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_id", sa.String(36), sa.ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location_code", sa.String(128), nullable=False, unique=True),
        sa.Column("zone_type", sa.String(64), nullable=False, server_default="standard"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_locations_facility_id", "locations", ["facility_id"])
    op.create_index("ix_locations_location_code", "locations", ["location_code"])

    # ------------------------------------------------------------------
    # cameras
    # ------------------------------------------------------------------
    op.create_table(
        "cameras",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("location_id", sa.String(36), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_code", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cameras_location_id", "cameras", ["location_id"])

    # ------------------------------------------------------------------
    # roles
    # ------------------------------------------------------------------
    op.create_table(
        "roles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ------------------------------------------------------------------
    # user_roles
    # ------------------------------------------------------------------
    op.create_table(
        "user_roles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    # ------------------------------------------------------------------
    # access_events
    # ------------------------------------------------------------------
    op.create_table(
        "access_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("location_id", sa.String(128), nullable=False),
        sa.Column("facility_id", sa.String(36), nullable=True),
        sa.Column("badge_id", sa.String(128), nullable=True),
        sa.Column("person_ref", sa.String(255), nullable=True),
        sa.Column("access_type", sa.String(32), nullable=False),
        sa.Column("access_granted", sa.Boolean, nullable=False),
        sa.Column("occurred_at", sa.String(32), nullable=False),
        sa.Column("source_system", sa.String(64), nullable=False, server_default="mock"),
        sa.Column("raw_data", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_access_events_location_id", "access_events", ["location_id"])
    op.create_index("ix_access_events_occurred_at", "access_events", ["occurred_at"])
    op.create_index("ix_access_events_badge_id", "access_events", ["badge_id"])

    # ------------------------------------------------------------------
    # schedules
    # ------------------------------------------------------------------
    op.create_table(
        "schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_id", sa.String(36), nullable=True),
        sa.Column("location_id", sa.String(128), nullable=True),
        sa.Column("schedule_type", sa.String(32), nullable=False),
        sa.Column("person_ref", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("start_time", sa.String(32), nullable=False),
        sa.Column("end_time", sa.String(32), nullable=False),
        sa.Column("recurrence_rule", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("source_system", sa.String(64), nullable=False, server_default="mock"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_schedules_location_id", "schedules", ["location_id"])
    op.create_index("ix_schedules_schedule_type", "schedules", ["schedule_type"])

    # ------------------------------------------------------------------
    # deliveries
    # ------------------------------------------------------------------
    op.create_table(
        "deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_id", sa.String(36), nullable=True),
        sa.Column("location_id", sa.String(128), nullable=False),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("delivery_reference", sa.String(128), nullable=True),
        sa.Column("scheduled_start", sa.String(32), nullable=False),
        sa.Column("scheduled_end", sa.String(32), nullable=False),
        sa.Column("is_scheduled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("source_system", sa.String(64), nullable=False, server_default="mock"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_deliveries_location_id", "deliveries", ["location_id"])

    # ------------------------------------------------------------------
    # work_orders
    # ------------------------------------------------------------------
    op.create_table(
        "work_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_id", sa.String(36), nullable=True),
        sa.Column("location_id", sa.String(128), nullable=False),
        sa.Column("work_order_number", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("assigned_to", sa.String(255), nullable=True),
        sa.Column("scheduled_start", sa.String(32), nullable=False),
        sa.Column("scheduled_end", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("requires_after_hours", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("approved_by", sa.String(255), nullable=True),
        sa.Column("source_system", sa.String(64), nullable=False, server_default="mock"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_work_orders_location_id", "work_orders", ["location_id"])
    op.create_index("ix_work_orders_work_order_number", "work_orders", ["work_order_number"])

    # ------------------------------------------------------------------
    # security_rules
    # ------------------------------------------------------------------
    op.create_table(
        "security_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_id", sa.String(36), nullable=True),
        sa.Column("location_id", sa.String(128), nullable=True),
        sa.Column("rule_code", sa.String(128), nullable=False, unique=True),
        sa.Column("rule_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("restricted_after", sa.String(8), nullable=True),
        sa.Column("restricted_before", sa.String(8), nullable=True),
        sa.Column("applies_to_zones", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("effective_from", sa.String(32), nullable=True),
        sa.Column("effective_until", sa.String(32), nullable=True),
        sa.Column("policy_reference", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_security_rules_rule_code", "security_rules", ["rule_code"])

    # ------------------------------------------------------------------
    # risk_policies
    # ------------------------------------------------------------------
    op.create_table(
        "risk_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("effective_from", sa.String(32), nullable=True),
        sa.Column("thresholds_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # risk_policy_factors
    # ------------------------------------------------------------------
    op.create_table(
        "risk_policy_factors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("risk_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("factor_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("weight", sa.Float, nullable=False),
        sa.Column("direction", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_risk_policy_factors_policy_id", "risk_policy_factors", ["policy_id"])

    # ------------------------------------------------------------------
    # incident_history
    # ------------------------------------------------------------------
    op.create_table(
        "incident_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("facility_id", sa.String(36), nullable=True),
        sa.Column("location_id", sa.String(128), nullable=False),
        sa.Column("incident_code", sa.String(128), nullable=False, unique=True),
        sa.Column("incident_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=True),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("embedding_json", sa.Text, nullable=True),
        sa.Column("similarity_score", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_incident_history_location_id", "incident_history", ["location_id"])
    op.create_index("ix_incident_history_incident_type", "incident_history", ["incident_type"])
    op.create_index("ix_incident_history_occurred_at", "incident_history", ["occurred_at"])

    # ------------------------------------------------------------------
    # security_events (central domain entity)
    # ------------------------------------------------------------------
    op.create_table(
        "security_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("source_adapter", sa.String(64), nullable=False, server_default="simulator"),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_timestamp", sa.String(32), nullable=False),
        sa.Column("location_id", sa.String(128), nullable=False),
        sa.Column("facility_id", sa.String(36), nullable=True),
        sa.Column("camera_id", sa.String(128), nullable=True),
        sa.Column("zone", sa.String(128), nullable=True),
        sa.Column("detector_confidence", sa.Float, nullable=True),
        sa.Column("thumbnail_url", sa.String(512), nullable=True),
        sa.Column("raw_metadata", sa.Text, nullable=True),
        sa.Column("normalised_data", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("risk_level", sa.String(16), nullable=True),
        sa.Column("risk_score", sa.Float, nullable=True),
        sa.Column("confidence_level", sa.String(16), nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("agent_run_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_security_events_provider_event_id", "security_events", ["provider_event_id"])
    op.create_index("ix_security_events_location_timestamp", "security_events", ["location_id", "event_timestamp"])
    op.create_index("ix_security_events_status_risk", "security_events", ["status", "risk_level"])
    op.create_index("ix_security_events_event_type", "security_events", ["event_type"])

    # ------------------------------------------------------------------
    # event_evidence
    # ------------------------------------------------------------------
    op.create_table(
        "event_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_code", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="structured"),
        sa.Column("status", sa.String(32), nullable=False, server_default="verified"),
        sa.Column("retrieved_at", sa.String(32), nullable=False),
        sa.Column("source_timestamp", sa.String(32), nullable=True),
        sa.Column("relevance", sa.Text, nullable=True),
        sa.Column("content_json", sa.Text, nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_evidence_event_id", "event_evidence", ["event_id"])
    op.create_index("ix_event_evidence_evidence_code", "event_evidence", ["evidence_code"])

    # ------------------------------------------------------------------
    # risk_assessments
    # ------------------------------------------------------------------
    op.create_table(
        "risk_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("risk_policy_version", sa.String(32), nullable=False),
        sa.Column("risk_score", sa.Float, nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("risk_factors_json", sa.Text, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("confidence_level", sa.String(16), nullable=True),
        sa.Column("confidence_reductions_json", sa.Text, nullable=True),
        sa.Column("assessed_at", sa.String(32), nullable=False),
        sa.Column("agent_run_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_risk_assessments_event_id", "risk_assessments", ["event_id"])

    # ------------------------------------------------------------------
    # confidence_assessments
    # ------------------------------------------------------------------
    op.create_table(
        "confidence_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("confidence_level", sa.String(16), nullable=False),
        sa.Column("reductions_json", sa.Text, nullable=True),
        sa.Column("sources_available", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sources_required", sa.Integer, nullable=False, server_default="0"),
        sa.Column("assessed_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # recommendations
    # ------------------------------------------------------------------
    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("recommended_action", sa.Text, nullable=False),
        sa.Column("why_json", sa.Text, nullable=True),
        sa.Column("missing_evidence_json", sa.Text, nullable=True),
        sa.Column("limitations_json", sa.Text, nullable=True),
        sa.Column("requires_human_review", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("risk_score", sa.Float, nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("agent_run_id", sa.String(36), nullable=True),
        sa.Column("generated_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # operator_decisions
    # ------------------------------------------------------------------
    op.create_table(
        "operator_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommendation_id", sa.String(36), nullable=True),
        sa.Column("decided_by", sa.String(36), nullable=False),
        sa.Column("decided_by_role", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("is_override", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("prior_status", sa.String(32), nullable=True),
        sa.Column("risk_at_decision", sa.String(16), nullable=True),
        sa.Column("confidence_at_decision", sa.Float, nullable=True),
        sa.Column("decided_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_operator_decisions_event_id", "operator_decisions", ["event_id"])
    op.create_index("ix_operator_decisions_decided_by", "operator_decisions", ["decided_by"])

    # ------------------------------------------------------------------
    # escalations
    # ------------------------------------------------------------------
    op.create_table(
        "escalations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("escalated_by", sa.String(36), nullable=False),
        sa.Column("escalated_by_role", sa.String(64), nullable=False),
        sa.Column("destination", sa.String(64), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False, server_default="high"),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_acknowledgement"),
        sa.Column("acknowledged_by", sa.String(36), nullable=True),
        sa.Column("acknowledged_at", sa.String(32), nullable=True),
        sa.Column("escalated_at", sa.String(32), nullable=False),
        sa.Column("evidence_snapshot_json", sa.Text, nullable=True),
        sa.Column("recommendation_snapshot_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_escalations_event_id", "escalations", ["event_id"])

    # ------------------------------------------------------------------
    # agent_runs
    # ------------------------------------------------------------------
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("agent_version", sa.String(64), nullable=True),
        sa.Column("orchestrate_run_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("completed_at", sa.String(32), nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_runs_event_id", "agent_runs", ["event_id"])
    op.create_index("ix_agent_runs_agent_name", "agent_runs", ["agent_name"])

    # ------------------------------------------------------------------
    # tool_calls
    # ------------------------------------------------------------------
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="success"),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("completed_at", sa.String(32), nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("input_summary", sa.Text, nullable=True),
        sa.Column("output_evidence_ids", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tool_calls_agent_run_id", "tool_calls", ["agent_run_id"])
    op.create_index("ix_tool_calls_tool_name", "tool_calls", ["tool_name"])

    # ------------------------------------------------------------------
    # integration_health
    # ------------------------------------------------------------------
    op.create_table(
        "integration_health",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("last_checked_at", sa.String(32), nullable=True),
        sa.Column("last_successful_at", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("adapter_class", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # feedback
    # ------------------------------------------------------------------
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submitted_by", sa.String(36), nullable=False),
        sa.Column("recommendation_useful", sa.Boolean, nullable=True),
        sa.Column("recommendation_accurate", sa.Boolean, nullable=True),
        sa.Column("missing_context", sa.Text, nullable=True),
        sa.Column("outcome", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("submitted_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feedback_event_id", "feedback", ["event_id"])

    # ------------------------------------------------------------------
    # audit_events (append-only, no updated_at)
    # ------------------------------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("security_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("actor_role", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.String(32), nullable=False),
        sa.Column("details_json", sa.Text, nullable=True),
        sa.Column("redacted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_audit_events_event_id", "audit_events", ["event_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("audit_events")
    op.drop_table("feedback")
    op.drop_table("integration_health")
    op.drop_table("tool_calls")
    op.drop_table("agent_runs")
    op.drop_table("escalations")
    op.drop_table("operator_decisions")
    op.drop_table("recommendations")
    op.drop_table("confidence_assessments")
    op.drop_table("risk_assessments")
    op.drop_table("event_evidence")
    op.drop_table("security_events")
    op.drop_table("incident_history")
    op.drop_table("risk_policy_factors")
    op.drop_table("risk_policies")
    op.drop_table("security_rules")
    op.drop_table("work_orders")
    op.drop_table("deliveries")
    op.drop_table("schedules")
    op.drop_table("access_events")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("cameras")
    op.drop_table("locations")
    op.drop_table("facilities")
