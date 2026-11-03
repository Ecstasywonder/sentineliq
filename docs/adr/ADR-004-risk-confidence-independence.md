# ADR-004 — Risk and Confidence Are Independent Models

**Date:** 2026-11-03  
**Status:** Accepted  
**Author:** IBM Bob (Principal Architect)  
**Deciders:** Project Owner, Principal Architect

---

## Context

Security events can have high risk signals with low available evidence (e.g. after-hours restricted area, but badge system is down) or low risk signals with high evidence completeness (e.g. scheduled maintenance, all sources confirm).

Conflating risk and confidence into a single score would produce misleading results:
- A HIGH RISK / LOW CONFIDENCE event might be under-prioritised if confidence pulls the combined score down
- A LOW RISK / HIGH CONFIDENCE event might appear uncertain when it is actually well-understood

---

## Decision

SentinelIQ models **risk** and **confidence** as independent values, stored separately, displayed separately, and never merged into a single score.

**Risk** answers: "How serious are the risk signals in the available evidence?"

**Confidence** answers: "How complete and reliable is the available evidence?"

Both are computed by the SentinelIQ backend (deterministic logic), not by the LLM.

Both appear as separate fields in:
- The assessment API response
- The operator dashboard
- The audit record
- The explanation output

---

## Rationale

This is a non-negotiable product requirement. Without independent risk/confidence modelling:
- Operators cannot distinguish between "truly low risk" and "we just don't know"
- Missing evidence silently becomes implicit evidence of safety
- The product fails its core safety guarantee

---

## Alternatives Considered

| Alternative | Reason Not Selected |
|------------|---------------------|
| Single combined score | Violates product spec; misleading to operators |
| LLM provides both as free text | Non-deterministic, not policy-governed |
| Risk only, no confidence | Operator has no signal about evidence completeness |

---

## Consequences

- Database tables `risk_assessments` and `confidence_assessments` are separate (or risk_assessment stores both as distinct fields)
- API response always includes both `risk_score`/`risk_level` AND `confidence_score`/`confidence_level`
- UI displays both prominently and distinctly — never merged
- Missing evidence always appears in `confidence_reductions`, never in risk factors
- Tests must verify the independent behaviour of both

---

## Migration Impact

N/A — initial design decision.

---

## Test Impact

- Test: HIGH RISK / LOW CONFIDENCE scenario (missing sources)
- Test: LOW RISK / HIGH CONFIDENCE scenario (all sources confirm normal)
- Test: Available sources returning no risk signals do not affect confidence
- Test: Unavailable sources do not increase risk score
