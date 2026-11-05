# ADR-005 — Adapter Pattern for Evidence Source Integrations

**Date:** 2026-11-03  
**Status:** Accepted  
**Author:** IBM Bob (Principal Architect)  
**Deciders:** Project Owner, Principal Architect

---

## Context

SentinelIQ needs to retrieve evidence from multiple external sources: access control, scheduling systems, visitor management, work order systems, and delivery systems. In MVP, these are simulated/mocked. In production, they will be real enterprise systems from various vendors.

The agent tool contracts (input schema, output schema) must remain stable when the underlying implementation changes from mock to real.

---

## Decision

All evidence source integrations use the **adapter pattern**.

Each integration type has:
1. A Python abstract base class defining the interface (domain contract)
2. A mock implementation for MVP
3. A stub for future real implementations

The Orchestrate tool functions call the SentinelIQ backend API. The backend routes through the adapter. The tool schema never changes when adapters are swapped.

```python
# Domain contract (abstract base class)
class AccessControlAdapter(ABC):
    @abstractmethod
    async def get_access_events(
        self,
        location_id: str,
        timestamp: datetime,
        window_minutes: int
    ) -> AccessControlResult:
        ...

# MVP implementation
class MockAccessControlAdapter(AccessControlAdapter):
    async def get_access_events(...) -> AccessControlResult:
        # Returns data from local seed data
        ...

# Future implementation
class EnterpriseAccessControlAdapter(AccessControlAdapter):
    async def get_access_events(...) -> AccessControlResult:
        # Calls real access control API
        ...
```

The active adapter is configured via environment variable:
```
ACCESS_CONTROL_ADAPTER=mock   # or: enterprise_lenel, enterprise_ccure
```

---

## Rationale

| Benefit | Detail |
|---------|--------|
| Agent contract stability | Tool schemas never change when adapters swap |
| Testability | Mock adapters enable deterministic tests |
| Vendor independence | Not coupled to any single enterprise vendor |
| Incremental production migration | Adapters can be swapped per source type |
| Failure isolation | Each adapter handles its own errors and availability |

---

## Alternatives Considered

| Alternative | Reason Not Selected |
|------------|---------------------|
| Direct API calls in tool functions | Couples tool contracts to specific vendor APIs |
| Generic HTTP adapter configured by URL | Loses type safety and domain-specific error handling |
| Single integration layer without abstraction | Cannot independently swap implementations |

---

## Consequences

- Each integration type in `backend/app/integrations/` has an abstract base class and a mock class
- The factory function reads from configuration to select the adapter
- All adapters must implement the exact domain contract interface
- New enterprise adapters are added without changing tool schemas or agent prompts
- Integration health is tracked per adapter

---

## Migration Impact

N/A — initial design decision. When real adapters are added, they must pass the same contract tests as mock adapters.

---

## Test Impact

- Contract tests verify that mock adapters conform to the domain interface
- Tests should be runnable with mock adapters and pass with future real adapters
- Error path tests: each adapter must correctly return an `unavailable` status on failure
