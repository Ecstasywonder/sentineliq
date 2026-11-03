# ADR-000 — Architecture Decision Record Process

**Date:** 2026-11-03  
**Status:** Accepted  
**Author:** IBM Bob (Principal Architect)  
**Deciders:** Project Owner, Principal Architect

---

## Context

SentinelIQ is a security-critical platform. Significant architectural decisions must be documented, reasoned about, and traceable. This ADR establishes the process and format for all future Architecture Decision Records in this project.

---

## Decision

All significant architectural decisions for SentinelIQ will be captured as Architecture Decision Records (ADRs) in `docs/adr/`.

### Naming Convention

```
ADR-NNN-short-title.md
```

Where `NNN` is a zero-padded three-digit sequence number.

### Statuses

| Status | Meaning |
|--------|---------|
| `Proposed` | Under discussion |
| `Accepted` | Adopted — in effect |
| `Deprecated` | Superseded but retained for history |
| `Superseded by ADR-NNN` | Replaced by a newer decision |

### Template

```markdown
# ADR-NNN — Title

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNN
**Author:** ...
**Deciders:** ...

## Context
[Why does this decision need to be made?]

## Decision
[What was decided?]

## Rationale
[Why this option over others?]

## Alternatives Considered
[What was not chosen and why?]

## Consequences
[What changes, risks, or trade-offs result?]

## Migration Impact
[What needs to change in existing code/data/process?]

## Test Impact
[What tests are needed or affected?]

## References
[Links to relevant standards, docs, or prior discussions]
```

---

## Triggers for Creating an ADR

Create an ADR for any change to:

- Technology selection (frameworks, databases, message brokers)
- Risk scoring model
- Agent instructions or tool permissions
- Human-review requirements
- Evidence source architecture
- Data model breaking changes
- Authorization model
- Production integration strategy
- Audit or retention policy
- Agent evaluation thresholds

---

## Consequences

- All significant decisions are traceable
- Future maintainers understand why decisions were made
- Reversals require explicit new ADRs
- ADRs are reviewed as part of each gate completion

---

## References

- [Documenting Architecture Decisions — Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- SentinelIQ Master Build Prompt, Section 50 (Change Management)
