import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { AuthProvider } from "../auth";

const renderApp = () =>
  render(
    <AuthProvider>
      <App />
    </AuthProvider>,
  );

const queueResponse = (items: object[], pages = 1) =>
  new Response(
    JSON.stringify({
      items,
      total: items.length,
      page: 1,
      page_size: 50,
      pages,
    }),
    { status: 200 },
  );

const loginMocks = () => [
  new Response(
    JSON.stringify({
      access_token: "access",
      refresh_token: "refresh",
      expires_in: 900,
    }),
    { status: 200 },
  ),
  new Response(
    JSON.stringify({
      id: "u1",
      email: "operator@example.com",
      full_name: "Operator",
      roles: ["officer"],
      is_active: true,
    }),
    { status: 200 },
  ),
];

const supervisorLoginMocks = () => [
  new Response(
    JSON.stringify({
      access_token: "access",
      refresh_token: "refresh",
      expires_in: 900,
    }),
    { status: 200 },
  ),
  new Response(
    JSON.stringify({
      id: "u2",
      email: "supervisor@example.com",
      full_name: "Supervisor",
      roles: ["supervisor"],
      is_active: true,
    }),
    { status: 200 },
  ),
];

const makeEvent = (overrides: object = {}) => ({
  id: "e1",
  provider_event_id: null,
  source_adapter: "simulator",
  event_type: "unauthorised_access",
  event_timestamp: "2026-01-01T12:00:00Z",
  location_id: "HQ",
  facility_id: "FAC-01",
  camera_id: "CAM-01",
  zone: "Door A",
  detector_confidence: 0.9,
  thumbnail_url: null,
  status: "awaiting_review",
  risk: { score: 82, level: "critical" },
  confidence: { score: 0.8, level: "high" },
  agent_run_id: null,
  created_at: "2026-01-01T12:00:00Z",
  updated_at: "2026-01-01T12:00:00Z",
  ...overrides,
});

const makeAssessment = (overrides: object = {}) => ({
  event_id: "e1",
  risk_policy_version: "1.0",
  risk_score: 82,
  risk_level: "critical",
  risk_factors: [
    {
      factor_id: "restricted_area",
      label: "Restricted area",
      weight: 25,
      direction: "increase",
      triggered: true,
      contribution: 25,
    },
  ],
  confidence_score: 0.81,
  confidence_level: "high",
  confidence_reductions: [{ reason: "Badge source unavailable", amount: 0.12 }],
  sources_available: 3,
  sources_required: 4,
  evidence_errors: {},
  assessed_at: "2026-01-01T12:05:00Z",
  triage: {
    category: "restricted_area_access",
    urgency_signals: ["after_hours", "restricted_zone"],
    required_context: ["access_control", "schedule"],
    triage_rationale: "Access detected in restricted zone after hours.",
    source: "deterministic_fallback",
    agent_run_id: "run-triage-001",
  },
  context: {
    source_statuses: [{ source_id: "mock_access_control", status: "ok" }],
    conflicts: [],
    missing_sources: [],
    context_summary: "No schedule entry found for this time window.",
    has_conflicts: false,
    has_missing_sources: false,
    source: "deterministic_fallback",
    agent_run_id: "run-context-001",
  },
  explanation: {
    summary:
      "Restricted activity was detected after hours without matching access records.",
    recommended_action: "Escalate to the shift supervisor for manual review.",
    missing_evidence: ["Badge service status"],
    limitations: ["Schedule data may be incomplete."],
    why: [
      {
        text: "No matching badge activity was found in the configured time window.",
        evidence_ids: ["ACCESS-12"],
      },
    ],
  },
  ...overrides,
});

const decisionHistoryResponse = (decisions: object[] = []) =>
  new Response(JSON.stringify({ decisions }), { status: 200 });

beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

// Helper: sign in, load queue, open first event
const signInAndOpenEvent = async (
  fetchMock: ReturnType<typeof vi.fn>,
  user: ReturnType<typeof userEvent.setup>,
  email = "operator@example.com",
) => {
  renderApp();
  await user.type(screen.getByLabelText("Email address"), email);
  await user.type(screen.getByLabelText("Password"), "password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await user.click(
    await screen.findByRole("button", {
      name: /open unauthorised_access event/i,
    }),
  );
  void fetchMock;
};

describe("App", () => {
  // ── Gate 16: Application shell ──────────────────────────────────────────

  it("renders an accessible sign-in form when unauthenticated", () => {
    renderApp();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Operator sign in",
    );
    expect(screen.getByLabelText("Email address")).toBeRequired();
  });

  it("shows an authentication failure without exposing a technical error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: { message: "Invalid email or password." },
          }),
          { status: 401 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@example.com",
    );
    await user.type(screen.getByLabelText("Password"), "bad-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid email or password.",
    );
  });

  it("renders the human oversight notice", () => {
    renderApp();
    expect(
      screen.getByText(/All security decisions require human review/i),
    ).toBeInTheDocument();
  });

  it("renders queue data using the API event schema after login", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              makeEvent({ event_type: "unauthorised_access", status: "awaiting_review" }),
            ],
            total: 1,
            page: 1,
            page_size: 50,
            pages: 1,
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@example.com",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("unauthorised access")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Primary navigation" }),
    ).toBeInTheDocument();
  });

  it("renders an unavailable timestamp instead of crashing on malformed event data", async () => {
    const event = makeEvent({ event_timestamp: "not-a-date" });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event])),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@example.com",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
  });

  it("ignores a stale queue response after the filters change", async () => {
    let resolveFirst: ((response: Response) => void) | undefined;
    let resolveSecond: ((response: Response) => void) | undefined;
    const firstResponse = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const secondResponse = new Promise<Response>((resolve) => {
      resolveSecond = resolve;
    });
    const staleEvent = makeEvent({ id: "stale", event_type: "stale_event", status: "awaiting_review" });
    const currentEvent = makeEvent({ id: "current", event_type: "current_event", status: "normalised" });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockImplementationOnce(() => firstResponse)
      .mockImplementationOnce(() => secondResponse);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@example.com",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await user.selectOptions(screen.getByLabelText("Status"), "normalised");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));

    resolveSecond?.(queueResponse([currentEvent]));
    expect(await screen.findByText("current event")).toBeInTheDocument();
    resolveFirst?.(queueResponse([staleEvent]));
    await waitFor(() =>
      expect(screen.queryByText("stale event")).not.toBeInTheDocument(),
    );
  });

  // ── Gate 16: Event detail ───────────────────────────────────────────────

  it("opens an event detail view and makes assessment availability clear", async () => {
    const event = makeEvent({ status: "normalised", risk: { score: null, level: null }, confidence: { score: null, level: null } });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "Assessment bundle not found." }), { status: 404 }),
        )
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );
    expect(
      await screen.findByRole("heading", { name: "unauthorised access" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeInTheDocument();
  });

  it("shows extended metadata fields in the event detail view", async () => {
    const event = makeEvent({ status: "normalised", risk: { score: null, level: null }, confidence: { score: null, level: null } });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
        )
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );
    const user = userEvent.setup();
    await signInAndOpenEvent(vi.fn(), user);
    expect(await screen.findByText("FAC-01")).toBeInTheDocument();
    expect(screen.getByText("CAM-01")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument(); // detector confidence
  });

  it("shows supporting evidence and a recommendation in the event decision interface", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(await screen.findByText(/Escalate to the shift supervisor/i)).toBeInTheDocument();
    expect(screen.getByText("Badge service status")).toBeInTheDocument();
    expect(screen.getByText("Decision timeline")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "override" })).not.toBeInTheDocument();
  });

  it("shows limitations when present in the explanation", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(await screen.findByText("Schedule data may be incomplete.")).toBeInTheDocument();
  });

  it("keeps assessment and decision controls hidden for read-only roles", async () => {
    const event = makeEvent({ status: "normalised", risk: { score: null, level: null }, confidence: { score: null, level: null } });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(supervisorLoginMocks()[0])
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ id: "u1", email: "reviewer@example.com", full_name: "Reviewer", roles: ["audit_reviewer"], is_active: true }),
            { status: 200 },
          ),
        )
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "Assessment bundle not found." }), { status: 404 }),
        )
        // No assessment → DecisionHistoryPanel never mounts → no decisions fetch.
        // audit_reviewer has canAudit=true so EventAuditPanel mounts and calls getEventAudit.
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ items: [], total: 0, page: 1, page_size: 50, pages: 1 }),
            { status: 200 },
          ),
        ),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "reviewer@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(
      await screen.findByText(/cannot run assessments or record decisions/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run assessment" })).not.toBeInTheDocument();
  });

  // ── Gate 17: Agent activity panel ──────────────────────────────────────

  it("shows the Agent activity panel with triage and context results", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(await screen.findByText("Agent activity")).toBeInTheDocument();
    expect(screen.getByText("Triage result")).toBeInTheDocument();
    expect(screen.getByText("restricted area access")).toBeInTheDocument();
    expect(screen.getByText("Context result")).toBeInTheDocument();
    expect(screen.getByText("No schedule entry found for this time window.")).toBeInTheDocument();
  });

  it("hides Agent activity panel when assessment has no triage/context", async () => {
    const event = makeEvent();
    const assessment = makeAssessment({ triage: null, context: null });

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    await screen.findByRole("heading", { name: "unauthorised access" });
    expect(screen.queryByText("Agent activity")).not.toBeInTheDocument();
  });

  // ── Gate 17: Coordinator review panel ──────────────────────────────────

  it("shows the Coordinator review panel button for reviewable events", async () => {
    const event = makeEvent({ status: "awaiting_review" });
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(await screen.findByText("Coordinator review")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Request coordinator review" }),
    ).toBeInTheDocument();
  });

  it("loads and shows coordinator review result when button is clicked", async () => {
    const event = makeEvent({ status: "awaiting_review" });
    const assessment = makeAssessment();
    const coordinatorReview = {
      event_id: "e1",
      assessment_ready: true,
      summary: "Assessment is complete and ready for human review.",
      missing_evidence: [],
      human_review_required: true,
      source: "deterministic_fallback",
      agent_run_id: "run-coord-001",
    };

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse())
        .mockResolvedValueOnce(new Response(JSON.stringify(coordinatorReview), { status: 200 })),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Request coordinator review" }),
    );

    expect(
      await screen.findByText("Assessment is complete and ready for human review."),
    ).toBeInTheDocument();
    expect(screen.getByText(/human review required/i)).toBeInTheDocument();
  });

  it("shows coordinator review error with retry button on failure", async () => {
    const event = makeEvent({ status: "awaiting_review" });
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse())
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "Service unavailable" }), { status: 503 }),
        ),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Request coordinator review" }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("hides the Coordinator panel for non-reviewable event statuses", async () => {
    const event = makeEvent({ status: "normalised", risk: { score: null, level: null }, confidence: { score: null, level: null } });

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
        )
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    await screen.findByRole("heading", { name: "unauthorised access" });
    expect(screen.queryByText("Coordinator review")).not.toBeInTheDocument();
  });

  // ── Gate 17: Escalation panel ───────────────────────────────────────────

  it("shows the Escalation panel for escalated events", async () => {
    const event = makeEvent({ status: "escalated" });
    const assessment = makeAssessment();
    const escalation = {
      id: "esc-001",
      event_id: "e1",
      reason: "Requires supervisor approval for zone access.",
      escalated_by: "officer@example.com",
      escalated_to: "supervisor@example.com",
      status: "open",
      notes: "Verified by camera footage.",
      created_at: "2026-01-01T13:00:00Z",
      updated_at: "2026-01-01T13:00:00Z",
    };

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse())
        .mockResolvedValueOnce(new Response(JSON.stringify(escalation), { status: 200 })),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(await screen.findByText("Escalation")).toBeInTheDocument();
    expect(
      screen.getByText("Requires supervisor approval for zone access."),
    ).toBeInTheDocument();
    expect(screen.getByText("officer@example.com")).toBeInTheDocument();
    expect(screen.getByText("Verified by camera footage.")).toBeInTheDocument();
  });

  it("hides the Escalation panel for non-escalated events", async () => {
    const event = makeEvent({ status: "awaiting_review" });
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    await screen.findByText("Decision timeline");
    expect(screen.queryByText("Escalation")).not.toBeInTheDocument();
  });

  // ── Gate 17: Decision history panel ────────────────────────────────────

  it("shows decision history within the timeline panel", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();
    const decisions = [
      { decision_id: "d1", event_id: "e1", decision: "escalate", rationale: "Needs supervisor review.", event_status: "escalated" },
    ];

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse(decisions)),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(await screen.findByText("Needs supervisor review.")).toBeInTheDocument();
  });

  it("shows 'No decisions' message when history is empty", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(
      await screen.findByText("No decisions have been recorded for this event."),
    ).toBeInTheDocument();
  });

  // ── Gate 18: Audit trail navigation ────────────────────────────────────

  it("shows the Audit trail nav link for roles with audit:read", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(supervisorLoginMocks()[0])
        .mockResolvedValueOnce(supervisorLoginMocks()[1])
        .mockResolvedValueOnce(queueResponse([])),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "supervisor@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("button", { name: "Audit trail" }),
    ).toBeInTheDocument();
  });

  it("hides the Audit trail nav link for officer role", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([])),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByRole("button", { name: "Refresh queue" });
    expect(screen.queryByRole("button", { name: "Audit trail" })).not.toBeInTheDocument();
  });

  it("renders the audit trail page when Audit trail nav is clicked", async () => {
    const auditResponse = {
      items: [
        {
          audit_id: "aud-001",
          event_id: "e1",
          action: "risk_assessed",
          actor: "system:assessment_service",
          actor_role: null,
          occurred_at: "2026-01-01T12:05:00Z",
          details: { risk_score: 82, risk_level: "critical" },
          redacted: false,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      pages: 1,
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(supervisorLoginMocks()[0])
        .mockResolvedValueOnce(supervisorLoginMocks()[1])
        .mockResolvedValueOnce(queueResponse([]))
        .mockResolvedValueOnce(new Response(JSON.stringify(auditResponse), { status: 200 })),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "supervisor@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(await screen.findByRole("button", { name: "Audit trail" }));

    expect(
      await screen.findByRole("heading", { name: "Audit trail", level: 1 }),
    ).toBeInTheDocument();
    expect(await screen.findByText("risk assessed")).toBeInTheDocument();
    expect(screen.getByText("system:assessment_service")).toBeInTheDocument();
  });

  // ── Gate 18: Event audit panel in EventDetail ───────────────────────────

  it("shows the event audit trail panel for supervisor role in event detail", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();
    const auditResponse = {
      items: [
        {
          audit_id: "aud-002",
          event_id: "e1",
          action: "risk_assessed",
          actor: "system:assessment_service",
          actor_role: null,
          occurred_at: "2026-01-01T12:05:00Z",
          details: null,
          redacted: false,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      pages: 1,
    };

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(supervisorLoginMocks()[0])
        .mockResolvedValueOnce(supervisorLoginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse())
        .mockResolvedValueOnce(new Response(JSON.stringify(auditResponse), { status: 200 })),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "supervisor@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(await screen.findByText("Complete event audit trail")).toBeInTheDocument();
    expect(await screen.findByText("risk assessed")).toBeInTheDocument();
  });

  it("hides the event audit trail panel for officer role", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    await screen.findByText("Decision timeline");
    expect(screen.queryByText("Complete event audit trail")).not.toBeInTheDocument();
  });

  it("shows audit entry details when Show details is clicked", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();
    const auditResponse = {
      items: [
        {
          audit_id: "aud-003",
          event_id: "e1",
          action: "human_decision",
          actor: "officer@example.com",
          actor_role: "officer",
          occurred_at: "2026-01-01T13:00:00Z",
          details: { decision: "escalate", rationale: "Needs review" },
          redacted: false,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      pages: 1,
    };

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(supervisorLoginMocks()[0])
        .mockResolvedValueOnce(supervisorLoginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse())
        .mockResolvedValueOnce(new Response(JSON.stringify(auditResponse), { status: 200 })),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "supervisor@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    const detailsBtn = await screen.findByRole("button", { name: "Show details" });
    await user.click(detailsBtn);
    expect(screen.getByText(/Needs review/)).toBeInTheDocument();
  });

  // ── Gate 18: Risk-policy reference panel ───────────────────────────────

  it("shows the risk-policy reference button for security_admin role", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ access_token: "a", refresh_token: "r", expires_in: 900 }), { status: 200 }),
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ id: "u3", email: "admin@example.com", full_name: "Admin", roles: ["security_admin"], is_active: true }),
            { status: 200 },
          ),
        )
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "admin@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    expect(await screen.findByText("Risk-policy reference")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Load policy details" }),
    ).toBeInTheDocument();
  });

  it("hides the risk-policy reference panel for officer role", async () => {
    const event = makeEvent();
    const assessment = makeAssessment();

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(queueResponse([event]))
        .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 }))
        .mockResolvedValueOnce(decisionHistoryResponse()),
    );

    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByLabelText("Email address"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open unauthorised_access event/i }),
    );

    await screen.findByText("Decision timeline");
    expect(screen.queryByText("Risk-policy reference")).not.toBeInTheDocument();
  });
});
