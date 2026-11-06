"""Schemas for Gate 8 hybrid incident and policy retrieval."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class KnowledgeSearchResult(BaseModel):
    """One citable, explicitly untrusted retrieval result."""

    evidence_id: str = Field(..., description="Stable citation ID for this source record")
    source_type: Literal["incident", "policy", "sop"]
    source_id: str
    title: str = Field(..., max_length=256)
    content: str = Field(..., max_length=2000)
    trust_boundary: Literal["untrusted_evidence"] = "untrusted_evidence"
    prompt_injection_detected: bool = False
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    lexical_score: float = Field(..., ge=0.0, le=1.0)
    semantic_score: float = Field(..., ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchMeta(BaseModel):
    query: str
    retrieval_mode: Literal["hybrid"] = "hybrid"
    embedding_provider: str
    result_count: int = Field(..., ge=0)
    retrieved_at: str
    filters: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    meta: KnowledgeSearchMeta
    results: list[KnowledgeSearchResult]

