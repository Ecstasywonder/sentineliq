# ADR-003 — Deterministic Risk Engine (Not LLM-Scored Risk)

**Date:** 2026-11-03  
**Status:** Accepted  
**Author:** IBM Bob (Principal Architect)  
**Deciders:** Project Owner, Principal Architect

---

## Context

A core requirement of SentinelIQ is that risk assessments are transparent, reproducible, and auditable. The system must be able to answer: "Why did SentinelIQ produce this risk level?" with a traceable, policy-driven answer.

An alternative approach would be to ask an LLM to produce a risk score directly from the evidence text. This is explicitly prohibited by the product specification.

---

## Decision

Risk scoring is implemented as **deterministic application logic** in the SentinelIQ backend. The LLM/agent layer does not produce risk scores.

The risk engine:
1. Receives a normalised evidence package
2. Evaluates each configured risk factor against the evidence
3. Sums factor weights (with both positive and negative contributions)
4. Maps the total score to a risk level using configured thresholds
5. Returns a structured result with each contributing factor, its weight, and its evidence IDs

All factor weights and thresholds are stored in the `risk_policies` and `risk_policy_factors` database tables. No values are hard-coded in application logic.

Every assessment records the `risk_policy_version` that was active.

---

## Rationale

| Requirement | Deterministic Engine | LLM Scoring |
|------------|---------------------|-------------|
| Reproducibility | ✅ Same inputs → same score | ❌ Non-deterministic |
| Auditability | ✅ Every factor traceable | ❌ Opaque |
| Policy governance | ✅ Versioned, admin-controlled | ❌ Embedded in prompt |
| Explainability | ✅ Factor list with weights | ❌ "The model thinks..." |
| Model independence | ✅ No model needed | ❌ Model-dependent |
| Regulatory defensibility | ✅ Traceable policy | ❌ Black-box |

---

## Alternatives Considered

| Alternative | Reason Not Selected |
|------------|---------------------|
| LLM produces risk score in free text | Non-reproducible, not auditable, violates product spec |
| LLM produces a structured score object | Still non-deterministic; model changes affect scores |
| Rules engine (Drools-style) | Viable; overkill for MVP; application logic is simpler and sufficient |

---

## Consequences

- The Risk Engine is a Python service in `backend/app/services/risk_engine.py`
- Risk policy changes require a new policy version record (not a code change)
- The Explanation Agent receives the structured risk output as input; it does not generate the score
- Unit tests for the risk engine are deterministic and comprehensive

---

## Migration Impact

N/A — initial design decision.

---

## Test Impact

Risk engine has 100% unit test coverage as a target. Tests use fixture evidence packages and assert exact scores.
