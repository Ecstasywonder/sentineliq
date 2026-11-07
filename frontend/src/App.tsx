import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ApiError,
  assessEvent,
  getAssessment,
  getCoordinatorReview,
  getDecisionHistory,
  getEscalation,
  getEventAudit,
  getEventEscalationDetail,
  getGlobalAudit,
  getEvent,
  getEvents,
  getRiskPolicies,
  getRiskPolicy,
  recordDecision,
  type Assessment,
  type AuditEntry,
  type AuditList,
  type CoordinatorReview,
  type Decision,
  type Escalation,
  type EscalationDetail,
  type RiskLevel,
  type RiskPolicyDetail,
  type SecurityEvent,
} from "./api";
import { useAuth } from "./auth";

const statuses = [
  "",
  "received",
  "normalised",
  "assessing",
  "awaiting_review",
  "context_incomplete",
  "escalated",
  "closed",
  "dismissed",
  "failed",
];
const risks = ["", "critical", "high", "medium", "low"];
const standardDecisions = ["accept", "reject", "dismiss", "request_context"];
const decisionRoles = new Set([
  "officer",
  "supervisor",
  "security_admin",
  "platform_admin",
]);
const escalationRoles = new Set([
  "officer",
  "supervisor",
  "security_admin",
  "platform_admin",
]);
const overrideRoles = new Set([
  "supervisor",
  "security_admin",
  "platform_admin",
]);

const riskLabel = (risk: RiskLevel | null) =>
  risk ? `${risk[0].toUpperCase()}${risk.slice(1)}` : "Not assessed";

const humanize = (value: string) => value.replace(/_/g, " ");

const formatTime = (value: string) => {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.valueOf())) return "Unavailable";

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(timestamp);
};

const errorMessage = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

// ---------------------------------------------------------------------------
// Shared RBAC helpers
// ---------------------------------------------------------------------------

const auditRoles = new Set([
  "supervisor",
  "facility_manager",
  "security_admin",
  "audit_reviewer",
  "agent_admin",
  "platform_admin",
]);

const policyRoles = new Set(["security_admin", "platform_admin"]);

// ---------------------------------------------------------------------------
// Gate 18 — Audit and history panels
// ---------------------------------------------------------------------------

/** Render one audit entry row in a consistent format. */
function AuditEntryRow({ entry }: { entry: AuditEntry }): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="audit-entry">
      <div className="audit-entry-header">
        <span className="audit-action">{humanize(entry.action)}</span>
        <span className="audit-actor">{entry.actor}</span>
        {entry.actor_role && (
          <span className="audit-role">{humanize(entry.actor_role)}</span>
        )}
        <span className="audit-time">{formatTime(entry.occurred_at)}</span>
        {entry.details && !entry.redacted && (
          <button
            className="secondary small"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? "Hide details" : "Show details"}
          </button>
        )}
        {entry.redacted && <span className="audit-redacted">Redacted</span>}
      </div>
      {expanded && entry.details && (
        <pre className="audit-details">
          {JSON.stringify(entry.details, null, 2)}
        </pre>
      )}
    </li>
  );
}

/** Paginated audit trail list — used by both EventAuditPanel and AuditPage. */
function AuditTrailList({
  load,
  title,
}: {
  load: (page: number) => Promise<AuditList>;
  title: string;
}): React.JSX.Element {
  const [data, setData] = useState<AuditList | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetch = useCallback(
    async (p: number) => {
      setLoading(true);
      setError("");
      try {
        const result = await load(p);
        setData(result);
        setPage(p);
      } catch (e) {
        setError(errorMessage(e, "Audit trail could not be loaded."));
      } finally {
        setLoading(false);
      }
    },
    [load],
  );

  useEffect(() => {
    void fetch(1);
  }, [fetch]);

  return (
    <div>
      <div className="section-heading">
        <div>
          <h2>{title}</h2>
          {data && (
            <p>
              {data.total} entr{data.total === 1 ? "y" : "ies"} · page {page}{" "}
              of {data.pages}
            </p>
          )}
        </div>
        <button
          className="secondary"
          onClick={() => void fetch(page)}
          disabled={loading}
        >
          Refresh
        </button>
      </div>

      {loading && (
        <p className="loading" role="status">
          Loading audit trail…
        </p>
      )}
      {error && (
        <div className="error-panel" role="alert">
          <p>{error}</p>
          <button className="secondary" onClick={() => void fetch(page)}>
            Try again
          </button>
        </div>
      )}
      {data && data.items.length === 0 && !loading && (
        <p>No audit entries found.</p>
      )}
      {data && data.items.length > 0 && (
        <ul className="audit-list" aria-label="Audit trail entries">
          {data.items.map((entry) => (
            <AuditEntryRow key={entry.audit_id} entry={entry} />
          ))}
        </ul>
      )}
      {data && data.pages > 1 && !loading && (
        <nav className="pagination" aria-label="Audit trail pages">
          <button
            className="secondary"
            disabled={page <= 1}
            onClick={() => void fetch(page - 1)}
          >
            Previous
          </button>
          <span aria-live="polite">
            Page {page} of {data.pages}
          </span>
          <button
            className="secondary"
            disabled={page >= data.pages}
            onClick={() => void fetch(page + 1)}
          >
            Next
          </button>
        </nav>
      )}
    </div>
  );
}

/** Event-scoped audit panel embedded in EventDetail. */
function EventAuditPanel({
  eventId,
  canAudit,
}: {
  eventId: string;
  canAudit: boolean;
}): React.JSX.Element | null {
  const load = useCallback(
    (p: number) => getEventAudit(eventId, p),
    [eventId],
  );
  if (!canAudit) return null;
  return (
    <section className="panel" aria-labelledby="audit-panel-title">
      <h2 id="audit-panel-title">Complete event audit trail</h2>
      <p className="notice">
        This immutable trail records every system and operator action taken on
        this event. Entries cannot be modified or deleted.
      </p>
      <AuditTrailList load={load} title="Event audit entries" />
    </section>
  );
}

/** Escalation detail panel — full EscalationDetail from backend (Gate 11 schema). */
function EscalationDetailPanel({
  eventId,
  isEscalated,
}: {
  eventId: string;
  isEscalated: boolean;
}): React.JSX.Element | null {
  const [detail, setDetail] = useState<EscalationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isEscalated) return;
    setLoading(true);
    getEventEscalationDetail(eventId)
      .then((r) => {
        setDetail(r);
        setLoaded(true);
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) {
          setLoaded(true);
        } else {
          setError(
            errorMessage(e, "Escalation details could not be retrieved."),
          );
        }
      })
      .finally(() => setLoading(false));
  }, [eventId, isEscalated]);

  if (!isEscalated) return null;

  return (
    <section className="panel" aria-labelledby="escalation-detail-title">
      <h2 id="escalation-detail-title">Escalation history</h2>
      {loading && (
        <p className="loading" role="status">
          Loading escalation…
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loaded && !detail && !error && (
        <p>No escalation record found for this event.</p>
      )}
      {detail && (
        <dl>
          <div>
            <dt>Destination</dt>
            <dd>{humanize(detail.destination)}</dd>
          </div>
          <div>
            <dt>Priority</dt>
            <dd>{humanize(detail.priority)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{humanize(detail.status)}</dd>
          </div>
          {detail.note && (
            <div>
              <dt>Note</dt>
              <dd>{detail.note}</dd>
            </div>
          )}
          <div>
            <dt>Escalated by</dt>
            <dd>
              {detail.escalated_by}{" "}
              <small>({humanize(detail.escalated_by_role)})</small>
            </dd>
          </div>
          <div>
            <dt>Escalated at</dt>
            <dd>{formatTime(detail.escalated_at)}</dd>
          </div>
          {detail.acknowledged_by && (
            <div>
              <dt>Acknowledged by</dt>
              <dd>
                {detail.acknowledged_by}
                {detail.acknowledged_at && (
                  <> at {formatTime(detail.acknowledged_at)}</>
                )}
              </dd>
            </div>
          )}
        </dl>
      )}
    </section>
  );
}

/** Risk policy reference panel — shows active policy and factor table. */
function RiskPolicyPanel({
  policyVersion,
  canPolicy,
}: {
  policyVersion: string;
  canPolicy: boolean;
}): React.JSX.Element | null {
  const [policy, setPolicy] = useState<RiskPolicyDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // Find the policy by version from the list
      const list = await getRiskPolicies();
      const found = list.items.find((p) => p.version === policyVersion);
      if (found) {
        const full = await getRiskPolicy(found.id);
        setPolicy(full);
      }
    } catch (e) {
      setError(errorMessage(e, "Risk policy could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [policyVersion]);

  if (!canPolicy) return null;

  return (
    <section className="panel" aria-labelledby="policy-panel-title">
      <h2 id="policy-panel-title">Risk-policy reference</h2>
      <p>
        Policy version applied to this assessment:{" "}
        <strong>{policyVersion}</strong>
      </p>

      {!policy && !loading && !error && (
        <button className="secondary" onClick={() => void load()}>
          Load policy details
        </button>
      )}
      {loading && (
        <p className="loading" role="status">
          Loading risk policy…
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {policy && (
        <>
          <dl>
            <div>
              <dt>Name</dt>
              <dd>{policy.name}</dd>
            </div>
            {policy.description && (
              <div>
                <dt>Description</dt>
                <dd>{policy.description}</dd>
              </div>
            )}
            <div>
              <dt>Effective from</dt>
              <dd>{formatTime(policy.effective_from)}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{policy.is_active ? "Active" : "Inactive"}</dd>
            </div>
          </dl>
          {policy.factors.length > 0 && (
            <>
              <h3>Risk factors</h3>
              <ul className="factors">
                {policy.factors.map((f) => (
                  <li key={f.factor_id}>
                    <span>
                      {f.label}
                      {f.description && (
                        <small> — {f.description}</small>
                      )}
                    </span>
                    <strong>
                      {f.direction === "increase" ? "+" : "−"}
                      {f.weight} pts
                      {!f.is_active && " (inactive)"}
                    </strong>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}

/** Full-page audit trail for roles with audit:read. */
function AuditPage(): React.JSX.Element {
  const [actionFilter, setActionFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [filterKey, setFilterKey] = useState(0);

  const load = useCallback(
    (p: number) => getGlobalAudit(p, actionFilter, actorFilter),
    [filterKey], // intentional: re-run only on filterKey bump, not on every keystroke
  );

  const applyFilters = () => setFilterKey((k) => k + 1);

  return (
    <section aria-labelledby="audit-page-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Administration</p>
          <h1 id="audit-page-title">Audit trail</h1>
          <p>
            Immutable record of all system and operator actions. Cannot be
            modified.
          </p>
        </div>
      </div>

      <div className="filters" aria-label="Audit filters">
        <label>
          Action
          <input
            type="text"
            value={actionFilter}
            placeholder="e.g. risk_assessed"
            onChange={(e) => setActionFilter(e.target.value)}
          />
        </label>
        <label>
          Actor
          <input
            type="text"
            value={actorFilter}
            placeholder="e.g. operator@example.com"
            onChange={(e) => setActorFilter(e.target.value)}
          />
        </label>
        <button onClick={applyFilters}>Apply filters</button>
      </div>

      <AuditTrailList load={load} title="All audit entries" />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Gate 17 sub-panels
// ---------------------------------------------------------------------------

function AgentPanel({
  assessment,
}: {
  assessment: Assessment;
}): React.JSX.Element | null {
  const triage = assessment.triage;
  const context = assessment.context;
  if (!triage && !context) return null;

  return (
    <section className="panel" aria-labelledby="agent-panel-title">
      <h2 id="agent-panel-title">Agent activity</h2>

      {triage && (
        <>
          <h3>Triage result</h3>
          <dl>
            <div>
              <dt>Category</dt>
              <dd>{humanize(triage.category)}</dd>
            </div>
            <div>
              <dt>Urgency signals</dt>
              <dd>
                {triage.urgency_signals.length > 0
                  ? triage.urgency_signals.map(humanize).join(", ")
                  : "None"}
              </dd>
            </div>
            <div>
              <dt>Required context</dt>
              <dd>
                {triage.required_context.length > 0
                  ? triage.required_context.map(humanize).join(", ")
                  : "None"}
              </dd>
            </div>
            <div>
              <dt>Triage rationale</dt>
              <dd>{triage.triage_rationale}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{humanize(triage.source)}</dd>
            </div>
            {triage.agent_run_id && (
              <div>
                <dt>Run ID</dt>
                <dd>
                  <code>{triage.agent_run_id}</code>
                </dd>
              </div>
            )}
          </dl>
        </>
      )}

      {context && (
        <>
          <h3>Context result</h3>
          <dl>
            <div>
              <dt>Summary</dt>
              <dd>{context.context_summary || "No summary available."}</dd>
            </div>
            <div>
              <dt>Conflicts detected</dt>
              <dd>
                {context.has_conflicts ? (
                  <ul>
                    {context.conflicts.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                ) : (
                  "None"
                )}
              </dd>
            </div>
            {context.has_missing_sources && (
              <div>
                <dt>Missing sources</dt>
                <dd>
                  <ul>
                    {context.missing_sources.map((s, i) => (
                      <li key={i}>{humanize(s)}</li>
                    ))}
                  </ul>
                </dd>
              </div>
            )}
            <div>
              <dt>Source</dt>
              <dd>{humanize(context.source)}</dd>
            </div>
            {context.agent_run_id && (
              <div>
                <dt>Run ID</dt>
                <dd>
                  <code>{context.agent_run_id}</code>
                </dd>
              </div>
            )}
          </dl>
        </>
      )}
    </section>
  );
}

function CoordinatorPanel({
  eventId,
  reviewable,
}: {
  eventId: string;
  reviewable: boolean;
}): React.JSX.Element {
  const [review, setReview] = useState<CoordinatorReview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const runReview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await getCoordinatorReview(eventId);
      setReview(result);
    } catch (e) {
      setError(errorMessage(e, "Coordinator review could not be retrieved."));
    } finally {
      setLoading(false);
    }
  }, [eventId]);

  if (!reviewable) return <></>;

  return (
    <section className="panel" aria-labelledby="coordinator-panel-title">
      <h2 id="coordinator-panel-title">Coordinator review</h2>
      <p className="notice">
        The Coordinator provides a read-only review. It does not change event
        state or produce an operational decision. Human review remains required.
      </p>

      {!review && !loading && !error && (
        <button className="secondary" onClick={() => void runReview()}>
          Request coordinator review
        </button>
      )}

      {loading && (
        <p className="loading" role="status">
          Requesting coordinator review…
        </p>
      )}

      {error && (
        <div className="error-panel" role="alert">
          <p>{error}</p>
          <button className="secondary" onClick={() => void runReview()}>
            Retry
          </button>
        </div>
      )}

      {review && (
        <dl>
          <div>
            <dt>Summary</dt>
            <dd>{review.summary}</dd>
          </div>
          <div>
            <dt>Assessment ready</dt>
            <dd>{review.assessment_ready ? "Yes" : "No"}</dd>
          </div>
          {review.missing_evidence.length > 0 && (
            <div>
              <dt>Missing evidence</dt>
              <dd>
                <ul>
                  {review.missing_evidence.map((item, i) => (
                    <li key={i}>{humanize(item)}</li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
          <div>
            <dt>Human review required</dt>
            <dd>Yes — all operational decisions require human approval.</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{humanize(review.source)}</dd>
          </div>
          {review.agent_run_id && (
            <div>
              <dt>Run ID</dt>
              <dd>
                <code>{review.agent_run_id}</code>
              </dd>
            </div>
          )}
        </dl>
      )}
    </section>
  );
}

function EscalationPanel({
  eventId,
  isEscalated,
}: {
  eventId: string;
  isEscalated: boolean;
}): React.JSX.Element | null {
  const [escalation, setEscalation] = useState<Escalation | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isEscalated) return;
    setLoading(true);
    getEscalation(eventId)
      .then((result) => {
        setEscalation(result);
        setLoaded(true);
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) {
          setLoaded(true);
        } else {
          setError(
            errorMessage(e, "Escalation details could not be retrieved."),
          );
        }
      })
      .finally(() => setLoading(false));
  }, [eventId, isEscalated]);

  if (!isEscalated) return null;

  return (
    <section className="panel" aria-labelledby="escalation-panel-title">
      <h2 id="escalation-panel-title">Escalation</h2>

      {loading && (
        <p className="loading" role="status">
          Loading escalation details…
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loaded && !escalation && !error && (
        <p>No escalation record was found for this event.</p>
      )}
      {escalation && (
        <dl>
          <div>
            <dt>Reason</dt>
            <dd>{escalation.reason}</dd>
          </div>
          <div>
            <dt>Escalated by</dt>
            <dd>{escalation.escalated_by}</dd>
          </div>
          {escalation.escalated_to && (
            <div>
              <dt>Escalated to</dt>
              <dd>{escalation.escalated_to}</dd>
            </div>
          )}
          <div>
            <dt>Status</dt>
            <dd>{humanize(escalation.status)}</dd>
          </div>
          {escalation.notes && (
            <div>
              <dt>Notes</dt>
              <dd>{escalation.notes}</dd>
            </div>
          )}
          <div>
            <dt>Escalated at</dt>
            <dd>{formatTime(escalation.created_at)}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

function DecisionHistoryPanel({
  eventId,
}: {
  eventId: string;
}): React.JSX.Element {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getDecisionHistory(eventId)
      .then((result) => setDecisions(result.decisions ?? []))
      .catch((e: unknown) =>
        setError(errorMessage(e, "Decision history could not be loaded.")),
      )
      .finally(() => setLoading(false));
  }, [eventId]);

  if (loading) {
    return (
      <p className="loading" role="status">
        Loading decision history…
      </p>
    );
  }

  if (error) {
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  }

  if (decisions.length === 0) {
    return <p>No decisions have been recorded for this event.</p>;
  }

  return (
    <ol className="timeline">
      {decisions.map((d) => (
        <li key={d.decision_id}>
          <span>{humanize(d.decision)}</span>
          <strong>{d.rationale ?? "No rationale provided."}</strong>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------

function Login(): React.JSX.Element {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");

    try {
      await signIn(email, password);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <p className="eyebrow">SentinelIQ</p>
        <h1 id="login-title">Operator sign in</h1>
        <p>
          Use your authorised SentinelIQ account to review the security event
          queue.
        </p>
        <form onSubmit={submit}>
          <label htmlFor="email">Email address</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="notice">
          All security decisions require human review and approval.
        </p>
      </section>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Event queue (Gate 16)
// ---------------------------------------------------------------------------

function EventQueue({
  onOpen,
}: {
  onOpen: (eventId: string) => void;
}): React.JSX.Element {
  const [status, setStatus] = useState("awaiting_review");
  const [risk, setRisk] = useState("");
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestGeneration = useRef(0);

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current;
    setLoading(true);
    setError("");

    try {
      const result = await getEvents(status, risk, page);
      if (generation !== requestGeneration.current) return;
      setEvents(result.items);
      setTotal(result.total);
      setPages(result.pages);
    } catch (e) {
      if (generation !== requestGeneration.current) return;
      setError(errorMessage(e, "The event queue could not be loaded."));
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, [page, risk, status]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section aria-labelledby="queue-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Operations</p>
          <h1 id="queue-title">Security event queue</h1>
          <p>
            {loading
              ? "Loading events…"
              : `${total} event${total === 1 ? "" : "s"} match the current filters. Page ${page} of ${pages}.`}
          </p>
        </div>
        <button
          className="secondary"
          onClick={() => void load()}
          disabled={loading}
        >
          Refresh queue
        </button>
      </div>

      <div className="filters" aria-label="Event filters">
        <label>
          Status
          <select
            value={status}
            onChange={(event) => {
              setPage(1);
              setStatus(event.target.value);
            }}
          >
            {statuses.map((value) => (
              <option key={value} value={value}>
                {value ? humanize(value) : "All statuses"}
              </option>
            ))}
          </select>
        </label>

        <label>
          Risk level
          <select
            value={risk}
            onChange={(event) => {
              setPage(1);
              setRisk(event.target.value);
            }}
          >
            {risks.map((value) => (
              <option key={value} value={value}>
                {value
                  ? `${riskLabel(value as RiskLevel)} risk`
                  : "All risk levels"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? (
        <div className="error-panel" role="alert">
          <p>Could not load the event queue: {error}</p>
          <button onClick={() => void load()}>Try again</button>
        </div>
      ) : loading ? (
        <p className="loading" role="status">
          Loading the event queue…
        </p>
      ) : events.length === 0 ? (
        <div className="empty">
          <h2>No events found</h2>
          <p>
            There are no events matching these filters. Change a filter or
            refresh the queue.
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">
              Security events returned by the service. Risk indicates review
              priority.
            </caption>
            <thead>
              <tr>
                <th>Risk</th>
                <th>Event</th>
                <th>Location</th>
                <th>Confidence</th>
                <th>Status</th>
                <th>Received</th>
                <th>
                  <span className="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {events.map((item) => (
                <tr key={item.id}>
                  <td>
                    <span
                      className={`badge risk-${item.risk.level ?? "unknown"}`}
                    >
                      {riskLabel(item.risk.level)}
                    </span>
                    <small>
                      {item.risk.score === null
                        ? "Score unavailable"
                        : `Score ${item.risk.score.toFixed(1)} / 200`}
                    </small>
                  </td>
                  <td>
                    <strong>{humanize(item.event_type)}</strong>
                    <small>{item.source_adapter}</small>
                  </td>
                  <td>
                    {item.location_id}
                    <small>
                      {item.zone ??
                        item.facility_id ??
                        "Location detail unavailable"}
                    </small>
                  </td>
                  <td>
                    {item.confidence.score === null
                      ? "Unavailable"
                      : `${Math.round(item.confidence.score * 100)}%`}
                    <small>{item.confidence.level ?? "Not assessed"}</small>
                  </td>
                  <td>
                    <span className="status">{humanize(item.status)}</span>
                  </td>
                  <td>{formatTime(item.event_timestamp)}</td>
                  <td>
                    <button
                      className="secondary"
                      aria-label={`Open ${item.event_type} event`}
                      onClick={() => onOpen(item.id)}
                    >
                      Open <span aria-hidden="true">→</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && pages > 1 && (
        <nav className="pagination" aria-label="Event queue pages">
          <button
            className="secondary"
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            Previous
          </button>
          <span aria-live="polite">
            Page {page} of {pages}
          </span>
          <button
            className="secondary"
            type="button"
            disabled={page >= pages}
            onClick={() => setPage((current) => Math.min(pages, current + 1))}
          >
            Next
          </button>
        </nav>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Event detail (Gates 16 + 17)
// ---------------------------------------------------------------------------

function EventDetail({
  eventId,
  onBack,
  roles,
}: {
  eventId: string;
  onBack: () => void;
  roles: string[];
}): React.JSX.Element {
  const [event, setEvent] = useState<SecurityEvent | null>(null);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [assessing, setAssessing] = useState(false);
  const [decision, setDecision] = useState("accept");
  const [rationale, setRationale] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const [nextEvent, nextAssessment] = await Promise.all([
        getEvent(eventId),
        getAssessment(eventId).catch((e: unknown) =>
          e instanceof ApiError && e.status === 404 ? null : Promise.reject(e),
        ),
      ]);
      setEvent(nextEvent);
      setAssessment(nextAssessment);
    } catch (e) {
      setError(errorMessage(e, "The event could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [eventId]);

  useEffect(() => {
    void load();
  }, [load]);

  const runAssessment = async () => {
    setAssessing(true);
    setActionError("");

    try {
      const nextAssessment = await assessEvent(eventId);
      setAssessment(nextAssessment);
      setEvent(await getEvent(eventId));
    } catch (e) {
      setActionError(errorMessage(e, "Assessment could not be completed."));
    } finally {
      setAssessing(false);
    }
  };

  const submitDecision = async (form: FormEvent) => {
    form.preventDefault();
    setSubmitting(true);
    setActionError("");

    try {
      await recordDecision(eventId, decision, rationale);
      setRationale("");
      await load();
    } catch (e) {
      setActionError(errorMessage(e, "Decision could not be recorded."));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <section className="loading" role="status">
        Loading event details…
      </section>
    );
  }

  if (error || !event) {
    return (
      <section className="error-panel" role="alert">
        <p>{error || "Event not found."}</p>
        <button onClick={onBack}>Return to queue</button>
      </section>
    );
  }

  const explanation = assessment?.explanation;
  const recommendation =
    explanation?.recommended_action ??
    explanation?.recommendation ??
    "No recommendation has been generated yet.";
  const whyReasons = explanation?.why ?? [];
  const missingEvidence = explanation?.missing_evidence ?? [];
  const limitations = explanation?.limitations ?? [];
  const riskFactors = assessment?.risk_factors ?? [];
  const confidenceReductions = assessment?.confidence_reductions ?? [];
  const evidenceErrors = assessment?.evidence_errors ?? {};
  const timeline = [
    { label: "Event received", value: formatTime(event.event_timestamp) },
    {
      label: "Assessment ready",
      value: assessment ? formatTime(assessment.assessed_at) : "Pending",
    },
    {
      label: "Operator review",
      value: event.status === "closed" ? "Completed" : "Required",
    },
  ];
  const mayDecide = roles.some((role) => decisionRoles.has(role));
  const mayEscalate = roles.some((role) => escalationRoles.has(role));
  const mayOverride = roles.some((role) => overrideRoles.has(role));
  const canAudit = roles.some((role) => auditRoles.has(role));
  const canPolicy = roles.some((role) => policyRoles.has(role));
  const availableDecisions = [
    ...standardDecisions,
    ...(mayEscalate ? ["escalate"] : []),
    ...(mayOverride ? ["override"] : []),
  ];
  const canAssess =
    mayDecide &&
    (event.status === "normalised" || event.status === "context_incomplete");
  const canDecide =
    mayDecide &&
    assessment !== null &&
    (event.status === "awaiting_review" || event.status === "escalated");
  const isReviewable =
    event.status === "awaiting_review" || event.status === "escalated";
  const isEscalated = event.status === "escalated";

  return (
    <section aria-labelledby="detail-title">
      <button className="back secondary" onClick={onBack}>
        ← Back to queue
      </button>

      {/* ── Event header ─────────────────────────────────────────────── */}
      <div className="section-heading">
        <div>
          <p className="eyebrow">Event detail</p>
          <h1 id="detail-title">{humanize(event.event_type)}</h1>
          <p>{event.id}</p>
        </div>
        {canAssess && (
          <button
            className="secondary"
            onClick={() => void runAssessment()}
            disabled={assessing}
          >
            {assessing
              ? "Assessing…"
              : event.status === "context_incomplete"
                ? "Retry assessment"
                : "Run assessment"}
          </button>
        )}
      </div>

      {/* ── Metadata + assessment overview ───────────────────────────── */}
      <div className="meta-grid">
        <div>
          <h2>Event metadata</h2>
          <dl>
            <div>
              <dt>Location</dt>
              <dd>{event.location_id}</dd>
            </div>
            <div>
              <dt>Zone</dt>
              <dd>{event.zone ?? "Not provided"}</dd>
            </div>
            <div>
              <dt>Facility</dt>
              <dd>{event.facility_id ?? "Not provided"}</dd>
            </div>
            <div>
              <dt>Camera</dt>
              <dd>{event.camera_id ?? "Not provided"}</dd>
            </div>
            <div>
              <dt>Detector confidence</dt>
              <dd>
                {event.detector_confidence !== null
                  ? `${Math.round(event.detector_confidence * 100)}%`
                  : "Not provided"}
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{humanize(event.status)}</dd>
            </div>
            <div>
              <dt>Received</dt>
              <dd>{formatTime(event.event_timestamp)}</dd>
            </div>
          </dl>
        </div>

        <div>
          <h2>Assessment overview</h2>
          {assessment ? (
            <dl>
              <div>
                <dt>Risk</dt>
                <dd>{riskLabel(assessment.risk_level)}</dd>
              </div>
              <div>
                <dt>Score</dt>
                <dd>{assessment.risk_score.toFixed(1)}</dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>{`${Math.round(assessment.confidence_score * 100)}%`}</dd>
              </div>
              <div>
                <dt>Policy version</dt>
                <dd>{assessment.risk_policy_version}</dd>
              </div>
              <div>
                <dt>Summary</dt>
                <dd>
                  {assessment.explanation?.summary ??
                    "No explanation available yet."}
                </dd>
              </div>
            </dl>
          ) : (
            <p>No assessment has been run yet.</p>
          )}
        </div>
      </div>

      {/* ── Assessment panels ─────────────────────────────────────────── */}
      {assessment && (
        <>
          {/* Risk and confidence */}
          <section className="panel" aria-labelledby="risk-panel-title">
            <h2 id="risk-panel-title">Risk and confidence</h2>
            <dl>
              <div>
                <dt>Risk level</dt>
                <dd>{riskLabel(assessment.risk_level)}</dd>
              </div>
              <div>
                <dt>Policy version</dt>
                <dd>{assessment.risk_policy_version}</dd>
              </div>
              <div>
                <dt>Evidence coverage</dt>
                <dd>
                  {assessment.sources_available} of{" "}
                  {assessment.sources_required} sources available
                </dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>
                  {assessment.confidence_level} ·{" "}
                  {Math.round(assessment.confidence_score * 100)}%
                </dd>
              </div>
            </dl>

            <h3>Deterministic risk factors</h3>
            {riskFactors.length > 0 ? (
              <ul className="factors">
                {riskFactors.map((factor) => (
                  <li key={factor.factor_id}>
                    <span>{factor.label}</span>
                    <strong>
                      {factor.triggered
                        ? `${factor.contribution > 0 ? "+" : ""}${factor.contribution.toFixed(1)} risk points`
                        : "Not triggered"}
                    </strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No risk-factor details were returned for this assessment.</p>
            )}

            <h3>Confidence reductions</h3>
            {confidenceReductions.length > 0 ? (
              <ul className="factors">
                {confidenceReductions.map((item, index) => (
                  <li key={`${item.reason}-${index}`}>
                    <span>{item.reason}</span>
                    <strong>
                      {item.amount > 0
                        ? `-${item.amount.toFixed(2)}`
                        : item.amount.toFixed(2)}
                    </strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No confidence reductions were recorded.</p>
            )}
          </section>

          {/* Evidence and recommendation */}
          <section className="panel" aria-labelledby="evidence-panel-title">
            <h2 id="evidence-panel-title">Evidence and recommendation</h2>
            <p>
              <strong>Recommendation:</strong> {recommendation}
            </p>

            {whyReasons.length > 0 && (
              <>
                <h3>Evidence-backed rationale</h3>
                <ul>
                  {whyReasons.map((reason, index) => (
                    <li key={`${reason.text}-${index}`}>
                      {reason.text}
                      {reason.evidence_ids &&
                        reason.evidence_ids.length > 0 && (
                          <small>
                            {" "}
                            Evidence: {reason.evidence_ids.join(", ")}
                          </small>
                        )}
                    </li>
                  ))}
                </ul>
              </>
            )}

            {missingEvidence.length > 0 ? (
              <>
                <h3>Missing evidence</h3>
                <ul>
                  {missingEvidence.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p>No missing evidence is flagged for this assessment.</p>
            )}

            {limitations.length > 0 && (
              <>
                <h3>Limitations</h3>
                <ul>
                  {limitations.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </>
            )}

            {Object.keys(evidenceErrors).length > 0 && (
              <>
                <h3>Evidence retrieval errors</h3>
                <ul>
                  {Object.entries(evidenceErrors).map(([source, msg]) => (
                    <li key={source}>
                      <strong>{humanize(source)}:</strong> {msg}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          {/* Agent activity panel (Gate 17) */}
          <AgentPanel assessment={assessment} />

          {/* Decision timeline */}
          <section className="panel" aria-labelledby="timeline-panel-title">
            <h2 id="timeline-panel-title">Decision timeline</h2>
            <ol className="timeline">
              {timeline.map((item) => (
                <li key={item.label}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </li>
              ))}
            </ol>

            {/* Decision history — loaded only when assessment exists */}
            <h3>Decision history</h3>
            <DecisionHistoryPanel eventId={eventId} />
          </section>
        </>
      )}

      {/* ── Coordinator review panel (Gate 17) ───────────────────────── */}
      <CoordinatorPanel eventId={eventId} reviewable={isReviewable} />

      {/* ── Escalation panel (Gate 17) ───────────────────────────────── */}
      <EscalationPanel eventId={eventId} isEscalated={isEscalated} />

      {/* ── Escalation history detail (Gate 18) ──────────────────────── */}
      <EscalationDetailPanel eventId={eventId} isEscalated={isEscalated} />

      {/* ── Risk-policy reference (Gate 18) ──────────────────────────── */}
      {assessment && (
        <RiskPolicyPanel
          policyVersion={assessment.risk_policy_version}
          canPolicy={canPolicy}
        />
      )}

      {/* ── Event audit trail (Gate 18) ───────────────────────────────── */}
      <EventAuditPanel eventId={eventId} canAudit={canAudit} />

      {/* ── Action error ─────────────────────────────────────────────── */}
      {actionError && (
        <div className="error-panel" role="alert">
          <p>{actionError}</p>
        </div>
      )}

      {/* ── Human review decision form ────────────────────────────────── */}
      {canDecide ? (
        <form className="decision-form" onSubmit={submitDecision}>
          <h2>Human review decision</h2>
          <label>
            Decision
            <select
              value={decision}
              onChange={(event) => setDecision(event.target.value)}
            >
              {availableDecisions.map((item) => (
                <option key={item} value={item}>
                  {humanize(item)}
                </option>
              ))}
            </select>
          </label>

          <label>
            Rationale
            <textarea
              value={rationale}
              maxLength={2000}
              onChange={(event) => setRationale(event.target.value)}
              placeholder="Explain the operator decision for this event."
            />
          </label>

          <button type="submit" disabled={submitting}>
            {submitting ? "Recording decision…" : "Record decision"}
          </button>
        </form>
      ) : (
        <p className="notice">
          {mayDecide
            ? "A human decision can be recorded only after assessment reaches the review queue."
            : "Your role can view this event but cannot run assessments or record decisions."}
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// App shell
// ---------------------------------------------------------------------------

export default function App(): React.JSX.Element {
  const { user, loading, signOut } = useAuth();
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [page, setPage] = useState<"queue" | "audit">("queue");

  if (loading) {
    return (
      <div className="app-shell">
        <p className="loading" role="status">
          Loading session…
        </p>
      </div>
    );
  }

  if (!user) {
    return <Login />;
  }

  const canViewAudit = user.roles.some((r) => auditRoles.has(r));

  // Navigating to queue resets event selection
  const goQueue = () => {
    setPage("queue");
    setSelectedEventId(null);
  };
  const goAudit = () => {
    setPage("audit");
    setSelectedEventId(null);
  };

  return (
    <div className="app-shell">
      <header className="topbar" role="banner">
        <div>
          <p className="eyebrow">SentinelIQ</p>
          <h1>Security operations</h1>
        </div>
        <div className="topbar-actions">
          <nav aria-label="Primary navigation">
            <button
              className="nav-link"
              type="button"
              aria-current={
                page === "queue" && !selectedEventId ? "page" : undefined
              }
              onClick={goQueue}
            >
              Event queue
            </button>
            {canViewAudit && (
              <button
                className="nav-link"
                type="button"
                aria-current={page === "audit" ? "page" : undefined}
                onClick={goAudit}
              >
                Audit trail
              </button>
            )}
            {selectedEventId && <span aria-current="page">Event detail</span>}
          </nav>
          <span>{user.full_name}</span>
          <button className="secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      {page === "audit" ? (
        <AuditPage />
      ) : selectedEventId ? (
        <EventDetail
          eventId={selectedEventId}
          onBack={() => setSelectedEventId(null)}
          roles={user.roles}
        />
      ) : (
        <EventQueue onOpen={(id) => { setSelectedEventId(id); setPage("queue"); }} />
      )}
    </div>
  );
}
