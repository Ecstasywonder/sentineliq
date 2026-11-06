import { type FormEvent, useEffect, useMemo, useState } from 'react'
import {
  ApiError,
  assessEvent,
  getAssessment,
  getEvent,
  getEvents,
  recordDecision,
  type Assessment,
  type RiskLevel,
  type SecurityEvent,
} from './api'
import { useAuth } from './auth'

const statuses = ['', 'normalised', 'assessing', 'awaiting_review', 'escalated', 'closed', 'dismissed']
const risks = ['', 'critical', 'high', 'medium', 'low']
const decisions = ['accept', 'reject', 'dismiss', 'request_context', 'escalate', 'override']

const riskLabel = (risk: RiskLevel | null) =>
  risk ? `${risk[0].toUpperCase()}${risk.slice(1)}` : 'Not assessed'

const humanize = (value: string) => value.replace(/_/g, ' ')

const formatTime = (value: string) =>
  new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  )

const errorMessage = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback

function Login(): React.JSX.Element {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')

    try {
      await signIn(email, password)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Unable to sign in. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <p className="eyebrow">SentinelIQ</p>
        <h1 id="login-title">Operator sign in</h1>
        <p>Use your authorised SentinelIQ account to review the security event queue.</p>
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
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="notice">All security decisions require human review and approval.</p>
      </section>
    </main>
  )
}

function EventQueue({ onOpen }: { onOpen: (eventId: string) => void }): React.JSX.Element {
  const [status, setStatus] = useState('awaiting_review')
  const [risk, setRisk] = useState('')
  const [sort, setSort] = useState('priority')
  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')

    try {
      const result = await getEvents(status, risk)
      setEvents(result.items)
      setTotal(result.total)
    } catch (e) {
      setError(errorMessage(e, 'The event queue could not be loaded.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [status, risk])

  const orderedEvents = useMemo(
    () =>
      [...events].sort((left, right) => {
        if (sort === 'newest') {
          return Date.parse(right.event_timestamp) - Date.parse(left.event_timestamp)
        }
        if (sort === 'oldest') {
          return Date.parse(left.event_timestamp) - Date.parse(right.event_timestamp)
        }
        return 0
      }),
    [events, sort],
  )

  return (
    <section aria-labelledby="queue-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Operations</p>
          <h1 id="queue-title">Security event queue</h1>
          <p>
            {loading
              ? 'Loading events…'
              : `${total} event${total === 1 ? '' : 's'} match the current filters.`}
          </p>
        </div>
        <button className="secondary" onClick={() => void load()} disabled={loading}>
          Refresh queue
        </button>
      </div>

      <div className="filters" aria-label="Event filters">
        <label>
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            {statuses.map((value) => (
              <option key={value} value={value}>
                {value ? humanize(value) : 'All statuses'}
              </option>
            ))}
          </select>
        </label>

        <label>
          Risk level
          <select value={risk} onChange={(event) => setRisk(event.target.value)}>
            {risks.map((value) => (
              <option key={value} value={value}>
                {value ? `${riskLabel(value as RiskLevel)} risk` : 'All risk levels'}
              </option>
            ))}
          </select>
        </label>

        <label>
          Order
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="priority">Risk priority</option>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
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
      ) : orderedEvents.length === 0 ? (
        <div className="empty">
          <h2>No events found</h2>
          <p>There are no events matching these filters. Change a filter or refresh the queue.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Security events, ordered by the selected order</caption>
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
              {orderedEvents.map((item) => (
                <tr key={item.id}>
                  <td>
                    <span className={`badge risk-${item.risk.level ?? 'unknown'}`}>
                      {riskLabel(item.risk.level)}
                    </span>
                    <small>
                      {item.risk.score === null ? 'Score unavailable' : `Score ${item.risk.score.toFixed(2)}`}
                    </small>
                  </td>
                  <td>
                    <strong>{humanize(item.event_type)}</strong>
                    <small>{item.source_adapter}</small>
                  </td>
                  <td>
                    {item.location_id}
                    <small>{item.zone ?? item.facility_id ?? 'Location detail unavailable'}</small>
                  </td>
                  <td>
                    {item.confidence.score === null
                      ? 'Unavailable'
                      : `${Math.round(item.confidence.score * 100)}%`}
                    <small>{item.confidence.level ?? 'Not assessed'}</small>
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
    </section>
  )
}

function EventDetail({ eventId, onBack }: { eventId: string; onBack: () => void }): React.JSX.Element {
  const [event, setEvent] = useState<SecurityEvent | null>(null)
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [assessing, setAssessing] = useState(false)
  const [decision, setDecision] = useState('accept')
  const [rationale, setRationale] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const load = async () => {
    setLoading(true)
    setError('')

    try {
      const [nextEvent, nextAssessment] = await Promise.all([
        getEvent(eventId),
        getAssessment(eventId).catch((e: unknown) =>
          e instanceof ApiError && e.status === 404 ? null : Promise.reject(e),
        ),
      ])
      setEvent(nextEvent)
      setAssessment(nextAssessment)
    } catch (e) {
      setError(errorMessage(e, 'The event could not be loaded.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [eventId])

  const runAssessment = async () => {
    setAssessing(true)
    setActionError('')

    try {
      const nextAssessment = await assessEvent(eventId)
      setAssessment(nextAssessment)
      setEvent(await getEvent(eventId))
    } catch (e) {
      setActionError(errorMessage(e, 'Assessment could not be completed.'))
    } finally {
      setAssessing(false)
    }
  }

  const submitDecision = async (form: FormEvent) => {
    form.preventDefault()
    setSubmitting(true)
    setActionError('')

    try {
      await recordDecision(eventId, decision, rationale)
      setRationale('')
      await load()
    } catch (e) {
      setActionError(errorMessage(e, 'Decision could not be recorded.'))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <section className="loading" role="status">
        Loading event details…
      </section>
    )
  }

  if (error || !event) {
    return (
      <section className="error-panel" role="alert">
        <p>{error || 'Event not found.'}</p>
        <button onClick={onBack}>Return to queue</button>
      </section>
    )
  }

  const explanation = assessment?.explanation
  const recommendation = explanation?.recommended_action ?? explanation?.recommendation ?? 'No recommendation has been generated yet.'
  const whyReasons = explanation?.why ?? []
  const missingEvidence = explanation?.missing_evidence ?? []
  const riskFactors = assessment?.risk_factors ?? []
  const confidenceReductions = assessment?.confidence_reductions ?? []
  const timeline = [
    { label: 'Event received', value: formatTime(event.event_timestamp) },
    { label: 'Assessment ready', value: assessment ? formatTime(assessment.assessed_at) : 'Pending' },
    { label: 'Operator review', value: event.status === 'closed' ? 'Completed' : 'Required' },
  ]

  return (
    <section aria-labelledby="detail-title">
      <button className="back secondary" onClick={onBack}>
        ← Back to queue
      </button>

      <div className="section-heading">
        <div>
          <p className="eyebrow">Event detail</p>
          <h1 id="detail-title">{humanize(event.event_type)}</h1>
          <p>{event.id}</p>
        </div>
        <button className="secondary" onClick={() => void runAssessment()} disabled={assessing}>
          {assessing ? 'Assessing…' : 'Run assessment'}
        </button>
      </div>

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
              <dd>{event.zone ?? 'Not provided'}</dd>
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
          <h2>Assessment</h2>
          {assessment ? (
            <dl>
              <div>
                <dt>Risk</dt>
                <dd>{riskLabel(assessment.risk_level)}</dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>{`${Math.round(assessment.confidence_score * 100)}%`}</dd>
              </div>
              <div>
                <dt>Score</dt>
                <dd>{assessment.risk_score}</dd>
              </div>
              <div>
                <dt>Summary</dt>
                <dd>{assessment.explanation?.summary ?? 'No explanation available yet.'}</dd>
              </div>
            </dl>
          ) : (
            <p>No assessment has been run yet.</p>
          )}
        </div>
      </div>

      {assessment && (
        <>
          <section className="panel">
            <h2>Risk and confidence</h2>
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
                  {assessment.sources_available} of {assessment.sources_required} sources available
                </dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>{assessment.confidence_level} · {Math.round(assessment.confidence_score * 100)}%</dd>
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
                        ? `${factor.contribution > 0 ? '+' : ''}${factor.contribution.toFixed(1)} risk points`
                        : 'Not triggered'}
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
                    <strong>{item.amount > 0 ? `-${item.amount.toFixed(2)}` : item.amount.toFixed(2)}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No confidence reductions were recorded.</p>
            )}
          </section>

          <section className="panel">
            <h2>Evidence and recommendation</h2>
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
                      {reason.evidence_ids && reason.evidence_ids.length > 0 && (
                        <small> Evidence: {reason.evidence_ids.join(', ')}</small>
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
          </section>

          <section className="panel">
            <h2>Decision timeline</h2>
            <ol className="timeline">
              {timeline.map((item) => (
                <li key={item.label}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}

      {actionError && (
        <div className="error-panel" role="alert">
          <p>{actionError}</p>
        </div>
      )}

      <form className="decision-form" onSubmit={submitDecision}>
        <h2>Human review decision</h2>
        <label>
          Decision
          <select value={decision} onChange={(event) => setDecision(event.target.value)}>
            {decisions.map((item) => (
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
            onChange={(event) => setRationale(event.target.value)}
            placeholder="Explain the operator decision for this event."
          />
        </label>

        <button type="submit" disabled={submitting}>
          {submitting ? 'Recording decision…' : 'Record decision'}
        </button>
      </form>
    </section>
  )
}

export default function App(): React.JSX.Element {
  const { user, loading, signOut } = useAuth()
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)

  if (loading) {
    return <div className="app-shell"><p className="loading" role="status">Loading session…</p></div>
  }

  if (!user) {
    return <Login />
  }

  return (
    <div className="app-shell">
      <header className="topbar" role="banner">
        <div>
          <p className="eyebrow">SentinelIQ</p>
          <h1>Security operations</h1>
        </div>
        <div className="topbar-actions">
          <span>{user.full_name}</span>
          <button className="secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      {selectedEventId ? (
        <EventDetail eventId={selectedEventId} onBack={() => setSelectedEventId(null)} />
      ) : (
        <EventQueue onOpen={setSelectedEventId} />
      )}
    </div>
  )
}
