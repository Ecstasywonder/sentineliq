"""Gate 8 hybrid retrieval for incident narratives and policy/SOP text.

The service combines metadata filters, lexical overlap, and vector cosine
similarity. Stored incident embeddings are used when valid; otherwise a stable
domain-normalised local embedding is generated without executing or prompting
on document content. Returned content is explicitly labelled untrusted and has
a stable evidence ID for grounded citations.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.incident import IncidentHistory
from app.models.security_rule import SecurityRule
from app.schemas.knowledge import (
    KnowledgeSearchMeta,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_EMBEDDING_DIMENSIONS = 192
_MAX_INCIDENT_CANDIDATES = 200
_MAX_POLICY_CANDIDATES = 200
_EMBEDDING_BATCH_SIZE = 32
_INSTRUCTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|your|the)\s+instructions?\b", re.I),
    re.compile(r"\b(system|assistant|developer)\s*:\s*", re.I),
    re.compile(r"\b(mark|classify|set)\b.{0,40}\b(risk|event)\b.{0,20}\b(low|safe|clear)\b", re.I),
    re.compile(r"\bdo\s+not\s+follow\b.{0,30}\binstructions?\b", re.I),
)

_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"

logger = structlog.get_logger(__name__)

# Domain concepts make the local fallback more useful than raw token hashing
# while remaining deterministic and auditable. Production can replace this
# provider with watsonx embeddings without changing the retrieval contract.
_CONCEPTS = {
    "badge": "access_credential",
    "keycard": "access_credential",
    "credential": "access_credential",
    "unauthorized": "access_violation",
    "unverified": "access_violation",
    "forced": "forced_entry",
    "broken": "forced_entry",
    "pried": "forced_entry",
    "night": "after_hours",
    "overnight": "after_hours",
    "late": "after_hours",
    "delivery": "delivery_activity",
    "courier": "delivery_activity",
    "supplier": "delivery_activity",
    "vehicle": "vehicle_activity",
    "truck": "vehicle_activity",
    "van": "vehicle_activity",
    "camera": "video_detection",
    "person": "person_detection",
    "individual": "person_detection",
    "policy": "security_policy",
    "procedure": "security_policy",
    "sop": "security_policy",
}


class KnowledgeRetrievalService:
    """Read-only hybrid retriever over existing incident and policy records."""

    embedding_provider = "domain_hash_v1"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._embedding_provider = self.embedding_provider

    async def search(
        self,
        query: str,
        *,
        facility_id: str | None = None,
        location_id: str | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        occurred_from: str | None = None,
        occurred_to: str | None = None,
        include_incidents: bool = True,
        include_policies: bool = True,
        limit: int = 10,
    ) -> KnowledgeSearchResponse:
        bounded_query = self._bounded_text(query, 500)
        query_tokens = self._tokens(bounded_query)
        candidates: list[KnowledgeSearchResult] = []

        incidents: list[IncidentHistory] = []
        policies: list[SecurityRule] = []

        if include_incidents:
            incidents = await self._load_incidents(
                facility_id=facility_id,
                location_id=location_id,
                event_type=event_type,
                severity=severity,
                occurred_from=occurred_from,
                occurred_to=occurred_to,
                candidate_limit=min(max(limit * 20, 100), _MAX_INCIDENT_CANDIDATES),
            )

        if include_policies:
            policies = await self._load_policies(
                facility_id=facility_id,
                location_id=location_id,
                candidate_limit=_MAX_POLICY_CANDIDATES,
            )

        searchable_incidents = [self._incident_searchable(row) for row in incidents]
        searchable_policies = [self._policy_searchable(row) for row in policies]
        vectors = await self._semantic_vectors(
            [bounded_query, *searchable_incidents, *searchable_policies]
        )
        query_vector = vectors[0]
        incident_vectors = vectors[1 : 1 + len(incidents)]
        policy_vectors = vectors[1 + len(incidents) :]

        candidates.extend(
            self._incident_result(row, query_tokens, query_vector, vector, searchable)
            for row, vector, searchable in zip(
                incidents, incident_vectors, searchable_incidents, strict=True
            )
        )
        candidates.extend(
            self._policy_result(row, query_tokens, query_vector, vector, searchable)
            for row, vector, searchable in zip(
                policies, policy_vectors, searchable_policies, strict=True
            )
        )

        candidates.sort(
            key=lambda item: (item.relevance_score, item.semantic_score, item.evidence_id),
            reverse=True,
        )
        results = candidates[: max(1, min(limit, 50))]
        filters = {
            key: value
            for key, value in {
                "facility_id": facility_id,
                "location_id": location_id,
                "event_type": event_type,
                "severity": severity,
                "occurred_from": occurred_from,
                "occurred_to": occurred_to,
                "include_incidents": include_incidents,
                "include_policies": include_policies,
            }.items()
            if value is not None
        }
        return KnowledgeSearchResponse(
            meta=KnowledgeSearchMeta(
                query=bounded_query,
                embedding_provider=self._embedding_provider,
                result_count=len(results),
                retrieved_at=datetime.now(UTC).isoformat(),
                filters=filters,
            ),
            results=results,
        )

    async def _load_incidents(
        self,
        *,
        facility_id: str | None,
        location_id: str | None,
        event_type: str | None,
        severity: str | None,
        occurred_from: str | None,
        occurred_to: str | None,
        candidate_limit: int,
    ) -> list[IncidentHistory]:
        stmt = select(IncidentHistory)
        if facility_id:
            stmt = stmt.where(IncidentHistory.facility_id == facility_id)
        if location_id:
            stmt = stmt.where(IncidentHistory.location_id == location_id)
        if event_type:
            stmt = stmt.where(IncidentHistory.incident_type == event_type)
        if severity:
            stmt = stmt.where(IncidentHistory.severity == severity)
        if occurred_from:
            stmt = stmt.where(IncidentHistory.occurred_at >= occurred_from)
        if occurred_to:
            stmt = stmt.where(IncidentHistory.occurred_at <= occurred_to)
        stmt = stmt.order_by(IncidentHistory.occurred_at.desc()).limit(candidate_limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _load_policies(
        self,
        *,
        facility_id: str | None,
        location_id: str | None,
        candidate_limit: int,
    ) -> list[SecurityRule]:
        stmt = select(SecurityRule).where(SecurityRule.is_active.is_(True))
        if facility_id:
            stmt = stmt.where(
                or_(SecurityRule.facility_id == facility_id, SecurityRule.facility_id.is_(None))
            )
        if location_id:
            stmt = stmt.where(
                or_(SecurityRule.location_id == location_id, SecurityRule.location_id.is_(None))
            )
        stmt = stmt.order_by(SecurityRule.rule_code.asc()).limit(candidate_limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def _incident_result(
        self,
        row: IncidentHistory,
        query_tokens: set[str],
        query_vector: list[float],
        document_vector: list[float],
        searchable: str,
    ) -> KnowledgeSearchResult:
        content = self._bounded_text(
            " ".join(
                item
                for item in (row.description, row.outcome or "", row.resolution_notes or "")
                if item
            ),
            2000,
        )
        lexical = self._lexical_score(query_tokens, self._tokens(searchable))
        stored_vector = self._stored_embedding(row.embedding_json)
        if stored_vector is not None and len(stored_vector) == len(query_vector):
            document_vector = stored_vector
        semantic = self._cosine(query_vector, document_vector)
        recency = self._recency_score(row.occurred_at)
        relevance = self._clamp(0.40 * lexical + 0.50 * semantic + 0.10 * recency)
        return KnowledgeSearchResult(
            evidence_id=f"incident:{row.id}",
            source_type="incident",
            source_id=str(row.id),
            title=self._bounded_text(
                f"{row.incident_code}: {row.incident_type}", 256
            ),
            content=content,
            prompt_injection_detected=self._has_instruction_text(content),
            relevance_score=round(relevance, 6),
            lexical_score=round(lexical, 6),
            semantic_score=round(semantic, 6),
            metadata={
                "facility_id": row.facility_id,
                "location_id": row.location_id,
                "event_type": row.incident_type,
                "severity": row.severity,
                "occurred_at": row.occurred_at,
                "resolved": row.resolved,
                "incident_code": row.incident_code,
            },
        )

    def _policy_result(
        self,
        row: SecurityRule,
        query_tokens: set[str],
        query_vector: list[float],
        document_vector: list[float],
        searchable: str,
    ) -> KnowledgeSearchResult:
        content = self._bounded_text(row.description, 2000)
        lexical = self._lexical_score(query_tokens, self._tokens(searchable))
        semantic = self._cosine(query_vector, document_vector)
        relevance = self._clamp(0.45 * lexical + 0.55 * semantic)
        return KnowledgeSearchResult(
            evidence_id=f"policy:{row.id}",
            source_type="policy",
            source_id=str(row.id),
            title=self._bounded_text(row.policy_reference or row.rule_code, 256),
            content=content,
            prompt_injection_detected=self._has_instruction_text(content),
            relevance_score=round(relevance, 6),
            lexical_score=round(lexical, 6),
            semantic_score=round(semantic, 6),
            metadata={
                "facility_id": row.facility_id,
                "location_id": row.location_id,
                "rule_code": row.rule_code,
                "rule_type": row.rule_type,
                "policy_reference": row.policy_reference,
            },
        )

    @staticmethod
    def _incident_searchable(row: IncidentHistory) -> str:
        return " ".join(
            item
            for item in (
                row.incident_type,
                row.severity,
                row.location_id,
                row.description,
                row.outcome or "",
                row.resolution_notes or "",
            )
            if item
        )

    @staticmethod
    def _policy_searchable(row: SecurityRule) -> str:
        return " ".join(
            filter(
                None,
                (row.rule_code, row.rule_type, row.policy_reference, row.description),
            )
        )

    async def _semantic_vectors(self, texts: list[str]) -> list[list[float]]:
        """Use watsonx embeddings when configured; fail closed to local vectors."""
        settings = get_settings()
        if settings.enable_semantic_search and settings.watsonx_active:
            try:
                token = await self._watsonx_iam_token(
                    settings.effective_watsonx_api_key,
                    min(settings.agent_invoke_timeout, 15.0),
                )
                url = (
                    f"{settings.effective_watsonx_base_url.rstrip('/')}"
                    f"/ml/v1/text/embeddings?version={settings.watsonx_api_version}"
                )
                vectors: list[list[float]] = []
                async with httpx.AsyncClient(timeout=settings.agent_invoke_timeout) as client:
                    for offset in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
                        batch = texts[offset : offset + _EMBEDDING_BATCH_SIZE]
                        response = await client.post(
                            url,
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "inputs": [
                                    self._bounded_text(text, 2000) for text in batch
                                ],
                                "model_id": settings.watsonx_embedding_model_id,
                                "space_id": settings.effective_watsonx_space_id,
                                "parameters": {"truncate_input_tokens": 512},
                            },
                        )
                        response.raise_for_status()
                        results = response.json().get("results") or []
                        if len(results) != len(batch):
                            raise ValueError(
                                "watsonx embeddings response cardinality was invalid"
                            )
                        vectors.extend(
                            self._normalise_vector(item.get("embedding"))
                            for item in results
                        )
                if len(vectors) != len(texts) or any(not vector for vector in vectors):
                    raise ValueError("watsonx embeddings response cardinality was invalid")
                self._embedding_provider = f"watsonx:{settings.watsonx_embedding_model_id}"
                return vectors
            except Exception as exc:  # noqa: BLE001 - retrieval must degrade safely
                logger.warning(
                    "knowledge_retrieval.embedding_fallback",
                    provider="watsonx",
                    error=str(exc)[:256],
                )

        self._embedding_provider = self.embedding_provider
        return [self.embed(text) for text in texts]

    @staticmethod
    async def _watsonx_iam_token(api_key: str, timeout: float) -> str:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _IAM_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
            )
            response.raise_for_status()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("IAM token response did not include access_token")
        return token

    @staticmethod
    def _normalise_vector(raw: Any) -> list[float]:
        if not isinstance(raw, list) or not raw:
            return []
        try:
            vector = [float(value) for value in raw]
        except (TypeError, ValueError):
            return []
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else []

    @classmethod
    def embed(cls, text: str) -> list[float]:
        vector = [0.0] * _EMBEDDING_DIMENSIONS
        tokens = cls._tokens(text)
        if not tokens:
            return vector
        for token in tokens:
            concept = _CONCEPTS.get(token, token)
            for feature, weight in ((token, 0.35), (concept, 1.0)):
                digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
                bucket = int.from_bytes(digest[:4], "big") % _EMBEDDING_DIMENSIONS
                sign = 1.0 if digest[4] & 1 else -1.0
                vector[bucket] += weight * sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else vector

    @staticmethod
    def _stored_embedding(raw: str | None) -> list[float] | None:
        if not raw:
            return None
        try:
            values = json.loads(raw)
            if not isinstance(values, list) or not values:
                return None
            vector = [float(value) for value in values]
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else None

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(_TOKEN_RE.findall(str(text).lower()))

    @staticmethod
    def _lexical_score(query: set[str], document: set[str]) -> float:
        if not query or not document:
            return 0.0
        return len(query & document) / len(query)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        # Negative/orthogonal similarity is not relevance. Clamping preserves
        # a meaningful zero baseline instead of assigning unrelated records a
        # misleading 0.5 semantic score.
        return KnowledgeRetrievalService._clamp(
            sum(a * b for a, b in zip(left, right, strict=True))
        )

    @staticmethod
    def _recency_score(occurred_at: str) -> float:
        try:
            parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age_days = max((datetime.now(UTC) - parsed).total_seconds() / 86400, 0)
            return 1 / (1 + age_days / 365)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _has_instruction_text(text: str) -> bool:
        return any(pattern.search(text) for pattern in _INSTRUCTION_PATTERNS)

    @staticmethod
    def _bounded_text(value: Any, limit: int) -> str:
        return "".join(ch for ch in str(value or "") if ch.isprintable())[:limit]

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(float(value), 1.0))
