export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface SecurityEvent {
  id: string;
  provider_event_id: string | null;
  source_adapter: string;
  event_type: string;
  event_timestamp: string;
  location_id: string;
  facility_id: string | null;
  camera_id: string | null;
  zone: string | null;
  detector_confidence: number | null;
  thumbnail_url: string | null;
  status: string;
  risk: { score: number | null; level: RiskLevel | null };
  confidence: { score: number | null; level: string | null };
  agent_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface EventQueue {
  items: SecurityEvent[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface RiskFactor {
  factor_id: string;
  label: string;
  weight: number;
  direction: string;
  triggered: boolean;
  contribution: number;
}

export interface Assessment {
  assessment_id?: string;
  event_id: string;
  risk_policy_version: string;
  risk_score: number;
  risk_level: RiskLevel;
  risk_factors: RiskFactor[];
  confidence_score: number;
  confidence_level: string;
  confidence_reductions: Array<{
    reason: string;
    amount: number;
    source_id?: string;
    detail?: string;
  }>;
  sources_available: number;
  sources_required: number;
  evidence_errors: Record<string, string>;
  assessed_at: string;
  explanation?: {
    summary?: string;
    recommendation?: string;
    recommended_action?: string;
    missing_evidence?: string[];
    limitations?: string[];
    why?: Array<{ text: string; evidence_ids: string[] }>;
    citations?: Array<{ source_id?: string; label?: string }>;
  } | null;
}

export interface Decision {
  decision_id: string;
  event_id: string;
  decision: string;
  rationale: string | null;
  event_status: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  is_active: boolean;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim() || "/api/v1";
const normalizedBase = configuredBase.replace(/\/$/, "");
const apiBase = normalizedBase.endsWith("/api/v1")
  ? normalizedBase
  : `${normalizedBase}/api/v1`;
const storageKey = "sentineliq.auth";
const sessionClearedEvent = "sentineliq:session-cleared";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

let tokens: Tokens | null = readTokens();
let refreshPromise: Promise<boolean> | null = null;

function readTokens(): Tokens | null {
  try {
    const candidate: unknown = JSON.parse(
      sessionStorage.getItem(storageKey) ?? "null",
    );
    if (
      candidate &&
      typeof candidate === "object" &&
      "access_token" in candidate &&
      typeof candidate.access_token === "string" &&
      "refresh_token" in candidate &&
      typeof candidate.refresh_token === "string" &&
      "expires_in" in candidate &&
      typeof candidate.expires_in === "number"
    ) {
      return candidate as Tokens;
    }
  } catch {
    // Invalid browser state is treated as signed out.
  }
  return null;
}

function sameSession(left: Tokens | null, right: Tokens | null): boolean {
  return (
    left !== null &&
    right !== null &&
    left.access_token === right.access_token &&
    left.refresh_token === right.refresh_token
  );
}

export function hasSession(): boolean {
  tokens = readTokens();
  return tokens !== null;
}

export function currentSession(): Tokens | null {
  return tokens;
}

export function clearSession(): void {
  tokens = null;
  sessionStorage.removeItem(storageKey);
  window.dispatchEvent(new Event(sessionClearedEvent));
}

export function clearSessionIfCurrent(expected: Tokens | null): void {
  if (sameSession(tokens, expected)) clearSession();
}

export function saveSession(next: Tokens): void {
  tokens = next;
  sessionStorage.setItem(storageKey, JSON.stringify(next));
}

export function onSessionCleared(listener: () => void): () => void {
  window.addEventListener(sessionClearedEvent, listener);
  return () => window.removeEventListener(sessionClearedEvent, listener);
}

async function revokeRefreshToken(sessionToRevoke: Tokens): Promise<void> {
  // Logout is intentionally best effort. Its result must never change local
  // state: a later sign-in may already have replaced this session.
  await fetch(`${apiBase}/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ refresh_token: sessionToRevoke.refresh_token }),
  });
}

export function logout(): void {
  const sessionToRevoke = tokens;
  if (sessionToRevoke) {
    // Start revocation before local clearing, but never delay the operator's
    // sign-out on a slow or unavailable network.
    void revokeRefreshToken(sessionToRevoke).catch(() => undefined);
  }
  clearSessionIfCurrent(sessionToRevoke);
}

async function parseError(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      const message = (detail as { message: unknown }).message;
      if (typeof message === "string") return message;
    }
  }
  return response.statusText || "The request could not be completed.";
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const requestSession = tokens;
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (requestSession)
    headers.set("Authorization", `Bearer ${requestSession.access_token}`);

  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  if (
    response.status === 401 &&
    retry &&
    sameSession(tokens, requestSession) &&
    (await refreshSession())
  ) {
    return request<T>(path, init, false);
  }
  if (!response.ok)
    throw new ApiError(response.status, await parseError(response));
  return response.json() as Promise<T>;
}

async function rotateRefreshToken(): Promise<boolean> {
  const sessionToRefresh = tokens;
  if (!sessionToRefresh) return false;

  try {
    const response = await fetch(`${apiBase}/auth/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ refresh_token: sessionToRefresh.refresh_token }),
    });
    if (!response.ok) throw new Error("refresh failed");
    const refreshedSession = (await response.json()) as Tokens;
    if (!sameSession(tokens, sessionToRefresh)) return false;
    saveSession(refreshedSession);
    return true;
  } catch {
    clearSessionIfCurrent(sessionToRefresh);
    return false;
  }
}

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = rotateRefreshToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await fetch(`${apiBase}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok)
    throw new ApiError(response.status, await parseError(response));

  const loginSession = (await response.json()) as Tokens;
  saveSession(loginSession);
  try {
    return await request<User>("/auth/me");
  } catch (error) {
    clearSessionIfCurrent(loginSession);
    throw error;
  }
}

export const getCurrentUser = () => request<User>("/auth/me");

export const getEvents = (status: string, risk: string, page = 1) => {
  const params = new URLSearchParams({ page: String(page), page_size: "50" });
  if (status) params.set("status", status);
  if (risk) params.set("risk_level", risk);
  return request<EventQueue>(`/events?${params}`);
};

export const getEvent = (eventId: string) =>
  request<SecurityEvent>(`/events/${encodeURIComponent(eventId)}`);

export const getAssessment = (eventId: string) =>
  request<Assessment>(`/events/${encodeURIComponent(eventId)}/assessment`);

export const assessEvent = (eventId: string) =>
  request<Assessment>(`/events/${encodeURIComponent(eventId)}/assess`, {
    method: "POST",
    body: "{}",
  });

export const recordDecision = (
  eventId: string,
  decision: string,
  rationale: string,
) =>
  request<Decision>(`/events/${encodeURIComponent(eventId)}/decision`, {
    method: "POST",
    body: JSON.stringify({
      decision,
      rationale: rationale || null,
      is_override: decision === "override",
    }),
  });
