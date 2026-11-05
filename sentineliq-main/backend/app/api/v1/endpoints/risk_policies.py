"""
Risk Policy API — Gate 9.

Routes:
    GET  /api/v1/risk-policies          List all risk policies (summary)
    GET  /api/v1/risk-policies/{id}     Retrieve a single policy with factors

These are read-only informational endpoints so operators and auditors can
inspect which policy version is active and what factors/weights it defines.
Write operations (create/update policy) are reserved for future gate work.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor
from app.schemas.assessment import (
    RiskPolicyFactorResponse,
    RiskPolicyListResponse,
    RiskPolicyResponse,
)
from app.schemas.events import ErrorDetail
from app.security.dependencies import require_permission

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/risk-policies — list
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=RiskPolicyListResponse,
    summary="List risk policies",
    dependencies=[Depends(require_permission("admin:policy"))],
    responses={
        200: {"description": "Policy list"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
    },
)
async def list_risk_policies(
    session: AsyncSession = Depends(get_db),
) -> RiskPolicyListResponse:
    """
    Return all risk policy versions ordered by version descending.

    Each item includes the policy metadata but not the full factor list —
    use GET /risk-policies/{id} for the factor breakdown.
    """
    stmt = select(RiskPolicy).order_by(RiskPolicy.version.desc())
    result = await session.execute(stmt)
    policies = list(result.scalars().all())

    items = [
        RiskPolicyResponse(
            id=p.id,
            version=p.version,
            name=p.name,
            description=p.description,
            is_active=p.is_active,
            effective_from=p.effective_from,
            factors=[],  # omitted in list view for performance
        )
        for p in policies
    ]

    return RiskPolicyListResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# GET /api/v1/risk-policies/{policy_id} — single policy + factors
# ---------------------------------------------------------------------------


@router.get(
    "/{policy_id}",
    response_model=RiskPolicyResponse,
    summary="Retrieve a risk policy with its factors",
    dependencies=[Depends(require_permission("admin:policy"))],
    responses={
        200: {"description": "Policy found"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Policy not found"},
    },
)
async def get_risk_policy(
    policy_id: str,
    session: AsyncSession = Depends(get_db),
) -> RiskPolicyResponse:
    """
    Retrieve a single risk policy by its UUID, including all active and
    inactive factor definitions and their weights.
    """
    policy: RiskPolicy | None = await session.get(RiskPolicy, policy_id)
    if policy is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="POLICY_NOT_FOUND",
                message=f"Risk policy '{policy_id}' not found.",
            ).model_dump(),
        )

    # Load factors
    stmt = (
        select(RiskPolicyFactor)
        .where(RiskPolicyFactor.policy_id == policy_id)
        .order_by(RiskPolicyFactor.weight.desc())
    )
    result = await session.execute(stmt)
    factors = list(result.scalars().all())

    return RiskPolicyResponse(
        id=policy.id,
        version=policy.version,
        name=policy.name,
        description=policy.description,
        is_active=policy.is_active,
        effective_from=policy.effective_from,
        factors=[
            RiskPolicyFactorResponse(
                factor_id=f.factor_id,
                label=f.label,
                weight=f.weight,
                direction=f.direction,
                is_active=f.is_active,
                description=f.description,
            )
            for f in factors
        ],
    )
