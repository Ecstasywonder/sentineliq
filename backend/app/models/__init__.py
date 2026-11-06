"""
SQLAlchemy ORM models for SentinelIQ.

Import order matters for FK resolution — base entities first.
All models are imported here so Alembic can detect them via Base.metadata.
"""

from app.models.access import AccessEvent  # noqa: F401
from app.models.agent_run import AgentRun, ToolCall  # noqa: F401
from app.models.assessment import ConfidenceAssessment, RiskAssessment  # noqa: F401
from app.models.audit import AuditEvent  # noqa: F401
from app.models.decision import OperatorDecision  # noqa: F401
from app.models.delivery import Delivery  # noqa: F401
from app.models.escalation import Escalation  # noqa: F401
from app.models.event import SecurityEvent  # noqa: F401
from app.models.evidence import EventEvidence  # noqa: F401
from app.models.facility import Camera, Facility, Location  # noqa: F401
from app.models.feedback import Feedback  # noqa: F401
from app.models.incident import IncidentHistory  # noqa: F401
from app.models.integration import IntegrationHealth  # noqa: F401
from app.models.recommendation import Recommendation  # noqa: F401
from app.models.refresh_token import RefreshToken, RefreshTokenFamily  # noqa: F401
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor  # noqa: F401
from app.models.schedule import Schedule  # noqa: F401
from app.models.security_rule import SecurityRule  # noqa: F401
from app.models.user import Role, User, UserRole  # noqa: F401
from app.models.work_order import WorkOrder  # noqa: F401
