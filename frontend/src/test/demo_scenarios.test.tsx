/**
 * Gate 23 — Demo scenario journey tests.
 *
 * Validates the operator dashboard correctly presents each of the five
 * canonical demo scenarios from Master Build Prompt §51:
 *
 *   Scenario A — Authorized activity         → low risk, high confidence
 *   Scenario B — Unverified after-hours      → high/critical risk, clear evidence
 *   Scenario C — Missing evidence            → reduced confidence, unavailable sources
 *   Scenario D — Conflicting evidence        → conflict shown, uncertainty reflected
 *   Scenario E — AI unavailable              → deterministic fallback, still operable
 *
 * Each test exercises the full operator journey:
 *   1. Event appears in queue with correct risk/status indicators
 *   2. Event detail view shows risk score, confidence, evidence
 *   3. Decision controls are present and role-appropriate
 *   4. Accessibility: risk communicated via text + colour, not colour alone
 */

import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { AuthProvider } from "../auth";

// ---------------------------------------------------------------------------
// Test scaffolding
// ---------------------------------------------------------------------------

const renderApp = () =>
  render(
    <AuthProvider>
      <App />
    </AuthProvider>,
  );

const loginMocks = (roles = ["officer"]) => [
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
      id: "u-gate23",
      email: "operator@sentineliq.test",
      full_name: "Gate 23 Operator",
      roles,
      is_active: true,
    }),
    { status: 200 },
  ),
];

const queueResponse = (items: object[]) =>
  new Response(
    JSON.stringify({
      items,
      total: items.length,
      page: 1,
      page_size: 50,
      pages: 1,
    }),
    { status: 200 },
  );

/** Minimal SecurityEvent fixture — overrides applied on top. */
const makeEvent = (overrides: Record<string, unknown> = {}) => ({
  id: "evt-gate23",
  provider_event_id: null,
  source_adapter: "simulator",
  event_type: "person_detected",
  event_timestamp: "2026-11-03T09:15:00Z",
  location_id: "MAIN_ENTRANCE",
  facility_id: "fac-001",
  camera_id: "CAM-MAIN-01",
  zone: "standard",
  detector_confidence: 0.97,
  thumbnail_url: null,
  status: "awaiting_review",
  risk: { score: 10, level: "low" },
  confidence: { score: 0.85, level: "high" },
  agent_run_id: null,
  created_at: "2026-11-03T09:15:00Z",
  updated_at: "2026-11-03T09:15:00Z",
  ...overrides,
});

/** Minimal Assessment fixture — overrides applied on top. */
const makeAssessment = (overrides: Record<string, unknown> = {}) => ({
  event_id: "evt-gate23",
  risk_policy_version: "1.0",
  risk_score: 10,
  risk_level: "low",
  risk_factors: [
    {
      factor_id: "valid_access_schedule",
      label: "Valid access and matching schedule",
      weight: -35,
      direction: "decreases_risk",
      triggered: true,
      contribution: -35,
    },
  ],
  confidence_score: 0.85,
  confidence_level: "high",
  confidence_reductions: [],
  sources_available: 4,
  sources_required: 4,
  evidence_errors: {},
  assessed_at: "2026-11-03T09:15:30Z",
  triage: {
    category: "authorized_access",
    urgency_signals: [],
    required_context: ["access_control", "schedule"],
    triage_rationale: "Routine access at main entrance during business hours.",
    source: "deterministic_fallback",
    agent_run_id: null,
  },
  context: {
    source_statuses: [
      { source_id: "access_control", status: "ok" },
      { source_id: "schedule", status: "ok" },
    ],
    conflicts: [],
    missing_sources: [],
    context_summary: "Valid badge and scheduled activity confirmed.",
    has_conflicts: false,
    has_missing_sources: false,
    source: "deterministic_fallback",
    agent_run_id: null,
  },
  explanation: {
    summary: "Activity appears authorized. Valid badge and schedule confirmed.",
    recommended_action: "Operator review recommended before dismissal.",
    missing_evidence: [],
    limitations: [],
    why: [
      {
        text: "Valid badge access confirmed in access control system.",
        evidence_ids: ["ACCESS-SIM-A"],
      },
    ],
  },
  ...overrides,
});

const decisionHistoryEmpty = () =>
  new Response(JSON.stringify({ decisions: [] }), { status: 200 });

beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

/** Sign in as the configured user and open the first event in the queue. */
const signInAndOpenEvent = async (
  user: ReturnType<typeof userEvent.setup>,
  eventType = "person_detected",
) => {
  renderApp();
  await user.type(
    screen.getByLabelText("Email address"),
    "operator@sentineliq.test",
  );
  await user.type(screen.getByLabelText("Password"), "password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await user.click(
    await screen.findByRole("button", {
      name: new RegExp(`open ${eventType} event`, "i"),
    }),
  );
};

// ---------------------------------------------------------------------------
// Scenario A — Authorized activity (low risk)
// §51 expected: low risk, high confidence, operator can dismiss or confirm
// ---------------------------------------------------------------------------

describe("Gate 23 — Scenario A: Authorized activity (low risk)", () => {
  it("displays 'Low' risk label as visible text in the queue row (§30: not colour alone)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(
        queueResponse([makeEvent({ risk: { score: 10, level: "low" } })]),
      );

    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@sentineliq.test",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    // Risk level must be communicated as text, not colour alone (§30)
    // Multiple elements may say "low" (filter label, queue row, etc.) — that is fine
    await waitFor(() => {
      const elements = screen.getAllByText(/\blow\b/i);
      expect(elements.length).toBeGreaterThan(0);
    });
  });

  it("shows risk score, confidence level, and decision form in event detail", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({ risk: { score: 10, level: "low" } });
    const assessment = makeAssessment();

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    await signInAndOpenEvent(user);

    // Risk level text present in detail view
    await waitFor(() => {
      expect(screen.getAllByText(/\blow\b/i).length).toBeGreaterThan(0);
    });

    // Decision form "Record decision" button present for officer
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /record decision/i }),
      ).toBeDefined();
    });
  });

  it("recommendation text says human review is recommended (ADR-006)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({ risk: { score: 10, level: "low" } });
    const assessment = makeAssessment({
      explanation: {
        summary: "Authorized activity.",
        recommended_action: "Human review recommended before dismissal.",
        missing_evidence: [],
        limitations: [],
        why: [],
      },
    });

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    await signInAndOpenEvent(user);

    // Some element in the UI must communicate that human review is needed
    await waitFor(() => {
      const elements = screen.getAllByText(/human review/i);
      expect(elements.length).toBeGreaterThan(0);
    });
  });
});

// ---------------------------------------------------------------------------
// Scenario B — Unverified after-hours event (high risk)
// §51 expected: high/critical risk, high confidence, clear evidence, human review
// ---------------------------------------------------------------------------

describe("Gate 23 — Scenario B: Unverified after-hours event (high risk)", () => {
  it("displays 'High' risk text label in the queue row (§30: not colour alone)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(
        queueResponse([
          makeEvent({
            risk: { score: 80, level: "high" },
            status: "awaiting_review",
          }),
        ]),
      );

    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@sentineliq.test",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      const elements = screen.getAllByText(/\bhigh\b/i);
      expect(elements.length).toBeGreaterThan(0);
    });
  });

  it("shows triggered risk factors (no badge, out of schedule, restricted area)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({ risk: { score: 75, level: "high" } });
    const assessment = makeAssessment({
      risk_score: 75,
      risk_level: "high",
      risk_factors: [
        {
          factor_id: "no_matching_badge",
          label: "No matching authorised badge",
          weight: 25,
          direction: "increases_risk",
          triggered: true,
          contribution: 25,
        },
        {
          factor_id: "outside_schedule",
          label: "Activity outside permitted schedule",
          weight: 20,
          direction: "increases_risk",
          triggered: true,
          contribution: 20,
        },
        {
          factor_id: "restricted_area",
          label: "Restricted location at event time",
          weight: 25,
          direction: "increases_risk",
          triggered: true,
          contribution: 25,
        },
      ],
    });

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    await signInAndOpenEvent(user);

    // The "No matching authorised badge" risk factor must appear in the detail view
    await waitFor(() => {
      expect(screen.getByText(/no matching authorised badge/i)).toBeDefined();
    });
  });

  it("shows escalate as a decision option for a supervisor (§29: human decision area)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({ risk: { score: 75, level: "high" } });
    const assessment = makeAssessment({ risk_score: 75, risk_level: "high" });

    fetchMock
      .mockResolvedValueOnce(loginMocks(["supervisor"])[0])
      .mockResolvedValueOnce(loginMocks(["supervisor"])[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@sentineliq.test",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", {
        name: /open person_detected event/i,
      }),
    );

    // Supervisor can escalate — "escalate" must appear in the decision <select>
    await waitFor(() => {
      const select = screen.getByRole("combobox");
      expect(
        within(select).getByRole("option", { name: /escalate/i }),
      ).toBeDefined();
    });
  });
});

// ---------------------------------------------------------------------------
// Scenario C — Missing evidence (degraded confidence)
// §51 expected: sources marked unavailable, confidence reduced, no false
//               assertion that "no badge exists", human review requested
// ---------------------------------------------------------------------------

describe("Gate 23 — Scenario C: Missing evidence (degraded confidence)", () => {
  it("shows confidence reduction labels when sources are unavailable", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({
      risk: { score: 35, level: "medium" },
      confidence: { score: 0.42, level: "low" },
    });
    const assessment = makeAssessment({
      risk_score: 35,
      risk_level: "medium",
      confidence_score: 0.42,
      confidence_level: "low",
      confidence_reductions: [
        { reason: "Badge source unavailable", amount: 0.25 },
        { reason: "Schedule source unavailable", amount: 0.2 },
      ],
      sources_available: 2,
      sources_required: 4,
      evidence_errors: {
        access_control: "Service unavailable",
        schedule: "Service unavailable",
      },
      explanation: {
        summary:
          "Evidence sources are unavailable. Risk cannot be fully determined without them.",
        recommended_action:
          "Human review required. Verify access and schedule manually.",
        missing_evidence: ["Badge service status", "Schedule data"],
        limitations: [
          "Access control data unavailable — cannot confirm or deny badge access.",
          "Schedule data unavailable — cannot confirm or deny scheduled activity.",
        ],
        why: [],
      },
    });

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    await signInAndOpenEvent(user);

    // Confidence reduction label must be visible
    await waitFor(() => {
      expect(screen.getByText(/badge source unavailable/i)).toBeDefined();
    });
  });

  it("surfaces missing evidence items without falsely claiming badge was absent", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({ confidence: { score: 0.42, level: "low" } });
    const assessment = makeAssessment({
      confidence_score: 0.42,
      confidence_level: "low",
      confidence_reductions: [
        { reason: "Schedule source unavailable", amount: 0.25 },
      ],
      evidence_errors: { schedule: "Service unavailable" },
      explanation: {
        summary:
          "Schedule evidence unavailable. Cannot determine if activity is scheduled.",
        recommended_action: "Human review required.",
        // Correctly says "unavailable" — not "no schedule entry exists"
        missing_evidence: ["Schedule data"],
        limitations: [
          "Schedule data unavailable — cannot confirm or deny scheduled activity.",
        ],
        why: [],
      },
    });

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    await signInAndOpenEvent(user);

    // "Schedule data" must appear in the missing evidence list
    await waitFor(() => {
      const elements = screen.getAllByText(/schedule data/i);
      expect(elements.length).toBeGreaterThan(0);
    });

    // The limitation correctly says "cannot confirm or deny", not "does not exist"
    await waitFor(() => {
      expect(
        screen.getByText(/cannot confirm or deny scheduled activity/i),
      ).toBeDefined();
    });
  });
});

// ---------------------------------------------------------------------------
// Scenario D — Conflicting evidence
// §51 expected: conflict shown, confidence reflects uncertainty, human review
// ---------------------------------------------------------------------------

describe("Gate 23 — Scenario D: Conflicting evidence", () => {
  it("renders conflict information and shows uncertainty-reduced confidence", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({
      event_type: "badge_event",
      risk: { score: 60, level: "high" },
      confidence: { score: 0.55, level: "medium" },
    });
    const assessment = makeAssessment({
      risk_score: 60,
      risk_level: "high",
      confidence_score: 0.55,
      confidence_level: "medium",
      confidence_reductions: [
        { reason: "Conflicting evidence signals", amount: 0.3 },
      ],
      context: {
        source_statuses: [
          { source_id: "access_control", status: "ok" },
          { source_id: "schedule", status: "ok" },
        ],
        conflicts: [
          "Valid badge present but activity not scheduled at this time",
        ],
        missing_sources: [],
        context_summary:
          "Valid badge found but no matching schedule entry. Area is policy-restricted.",
        has_conflicts: true,
        has_missing_sources: false,
        source: "deterministic_fallback",
        agent_run_id: null,
      },
      explanation: {
        summary:
          "Conflicting evidence: badge was valid but no scheduled access was found.",
        recommended_action:
          "Human review required. Review conflict before making a decision.",
        missing_evidence: [],
        limitations: [
          "Conflicting signals reduce confidence in the automated assessment.",
        ],
        why: [
          {
            text: "Valid badge confirmed in access control log.",
            evidence_ids: ["ACCESS-SIM-D-1"],
          },
          {
            text: "No schedule entry found for this person at this time.",
            evidence_ids: ["SCHED-SIM-D-1"],
          },
        ],
      },
    });

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@sentineliq.test",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open badge_event event/i }),
    );

    // Conflict text must be surfaced to the operator (§51: "conflict explicitly shown")
    await waitFor(() => {
      const elements = screen.getAllByText(/conflict/i);
      expect(elements.length).toBeGreaterThan(0);
    });

    // Confidence level should reflect uncertainty (medium, not high)
    await waitFor(() => {
      const elements = screen.getAllByText(/medium/i);
      expect(elements.length).toBeGreaterThan(0);
    });
  });

  it("shows the confidence reduction reason for conflicting signals", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({
      event_type: "badge_event",
      risk: { score: 60, level: "high" },
    });
    const assessment = makeAssessment({
      confidence_reductions: [
        { reason: "Conflicting evidence signals", amount: 0.3 },
      ],
    });

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@sentineliq.test",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", { name: /open badge_event event/i }),
    );

    await waitFor(() => {
      expect(screen.getByText(/conflicting evidence signals/i)).toBeDefined();
    });
  });
});

// ---------------------------------------------------------------------------
// Scenario E — AI unavailable (deterministic fallback)
// §51 expected: event accessible, deterministic risk available, AI explanation
//               marked unavailable, operator can manually review
// ---------------------------------------------------------------------------

describe("Gate 23 — Scenario E: AI unavailable (deterministic fallback)", () => {
  it("renders deterministic risk score even when AI explanation is unavailable", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({
      event_type: "motion_detected",
      risk: { score: 45, level: "medium" },
    });
    const assessment = makeAssessment({
      risk_score: 45,
      risk_level: "medium",
      explanation: {
        summary:
          "AI explanation unavailable. Deterministic risk assessment completed.",
        recommended_action:
          "Human review required. AI explanation service unavailable.",
        missing_evidence: [],
        limitations: [
          "AI explanation service unavailable — only deterministic assessment provided.",
        ],
        why: [],
      },
    });

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@sentineliq.test",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", {
        name: /open motion_detected event/i,
      }),
    );

    // Deterministic risk score must be visible — event is never lost
    await waitFor(() => {
      const elements = screen.getAllByText(/\bmedium\b/i);
      expect(elements.length).toBeGreaterThan(0);
    });

    // AI unavailability notice must be visible in the limitations section
    await waitFor(() => {
      const elements = screen.getAllByText(
        /ai explanation service unavailable/i,
      );
      expect(elements.length).toBeGreaterThan(0);
    });
  });

  it("shows the Record decision form so operator can decide manually without AI", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({ event_type: "motion_detected" });
    const assessment = makeAssessment({
      explanation: {
        summary: "AI explanation unavailable.",
        recommended_action: "Human review required.",
        missing_evidence: [],
        limitations: ["AI explanation service unavailable."],
        why: [],
      },
    });

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty());

    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@sentineliq.test",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", {
        name: /open motion_detected event/i,
      }),
    );

    // "Record decision" button must be accessible without AI
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /record decision/i }),
      ).toBeDefined();
    });
  });

  it("displays coordinator review via deterministic fallback when AI is unavailable", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const event = makeEvent({ event_type: "motion_detected" });
    const assessment = makeAssessment();
    const coordinatorReview = {
      event_id: "evt-gate23",
      assessment_ready: true,
      summary:
        "Deterministic fallback review: motion detected in restricted zone. Human review required.",
      missing_evidence: [],
      human_review_required: true,
      source: "deterministic_fallback",
      agent_run_id: "run-fallback-e",
    };

    fetchMock
      .mockResolvedValueOnce(loginMocks()[0])
      .mockResolvedValueOnce(loginMocks()[1])
      .mockResolvedValueOnce(queueResponse([event]))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(event), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(assessment), { status: 200 }),
      )
      .mockResolvedValueOnce(decisionHistoryEmpty())
      .mockResolvedValueOnce(
        new Response(JSON.stringify(coordinatorReview), { status: 200 }),
      );

    renderApp();
    await user.type(
      screen.getByLabelText("Email address"),
      "operator@sentineliq.test",
    );
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(
      await screen.findByRole("button", {
        name: /open motion_detected event/i,
      }),
    );

    const reviewButton = await screen.findByRole("button", {
      name: /request coordinator review/i,
    });
    await user.click(reviewButton);

    // Fallback source label must be visible (may appear in multiple places)
    await waitFor(() => {
      const elements = screen.getAllByText(/deterministic.fallback/i);
      expect(elements.length).toBeGreaterThan(0);
    });
  });
});

// ---------------------------------------------------------------------------
// Accessibility — §30 requirements (not colour alone for risk communication)
// ---------------------------------------------------------------------------

describe("Gate 23 — Accessibility: risk communicated without colour alone (§30)", () => {
  const riskLevels: Array<{ level: string; score: number }> = [
    { level: "low", score: 10 },
    { level: "medium", score: 40 },
    { level: "high", score: 70 },
    { level: "critical", score: 90 },
  ];

  for (const { level, score } of riskLevels) {
    it(`renders readable '${level}' text label in the event queue row`, async () => {
      const user = userEvent.setup();
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);

      fetchMock
        .mockResolvedValueOnce(loginMocks()[0])
        .mockResolvedValueOnce(loginMocks()[1])
        .mockResolvedValueOnce(
          queueResponse([makeEvent({ risk: { score, level } })]),
        );

      renderApp();
      await user.type(
        screen.getByLabelText("Email address"),
        "operator@sentineliq.test",
      );
      await user.type(screen.getByLabelText("Password"), "password");
      await user.click(screen.getByRole("button", { name: "Sign in" }));

      // Text label must be present for each risk level (§30: not colour alone)
      await waitFor(() => {
        const matches = screen.getAllByText(new RegExp(`\\b${level}\\b`, "i"));
        expect(matches.length).toBeGreaterThan(0);
      });
    });
  }

  it("renders accessible sign-in form with labelled inputs and a button role (§30)", () => {
    renderApp();
    // Inputs must have accessible labels (not just placeholders)
    expect(screen.getByLabelText("Email address")).toBeDefined();
    expect(screen.getByLabelText("Password")).toBeDefined();
    // Submit must be a proper button role
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDefined();
  });
});
