import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearSession, getEvent, login, logout, saveSession } from "../api";

const eventPayload = {
  id: "event-1",
  provider_event_id: null,
  source_adapter: "simulator",
  event_type: "person_detected",
  event_timestamp: "2026-01-01T12:00:00Z",
  location_id: "HQ",
  facility_id: null,
  camera_id: null,
  zone: null,
  detector_confidence: 0.9,
  thumbnail_url: null,
  status: "awaiting_review",
  risk: { score: 75, level: "high" },
  confidence: { score: 0.8, level: "high" },
  agent_run_id: null,
  created_at: "2026-01-01T12:00:00Z",
  updated_at: "2026-01-01T12:00:00Z",
};

beforeEach(() => {
  clearSession();
  vi.restoreAllMocks();
});

describe("API authentication", () => {
  it("revokes the refresh family best-effort while signing out locally immediately", () => {
    let resolveLogout: ((response: Response) => void) | undefined;
    const logoutResponse = new Promise<Response>((resolve) => {
      resolveLogout = resolve;
    });
    saveSession({
      access_token: "access-before-logout",
      refresh_token: "refresh-before-logout",
      expires_in: 900,
    });
    const fetchMock = vi.fn().mockImplementationOnce(() => logoutResponse);
    vi.stubGlobal("fetch", fetchMock);

    logout();

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/auth\/logout$/),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ refresh_token: "refresh-before-logout" }),
      }),
    );
    expect(sessionStorage.getItem("sentineliq.auth")).toBeNull();

    saveSession({
      access_token: "new-access",
      refresh_token: "new-refresh",
      expires_in: 900,
    });
    resolveLogout?.(new Response(null, { status: 204 }));

    expect(sessionStorage.getItem("sentineliq.auth")).toContain("new-access");
  });

  it("still clears locally if refresh-family revocation cannot start", () => {
    saveSession({
      access_token: "access-before-logout",
      refresh_token: "refresh-before-logout",
      expires_in: 900,
    });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    logout();

    expect(sessionStorage.getItem("sentineliq.auth")).toBeNull();
  });

  it("uses one refresh rotation for concurrent 401 responses", async () => {
    saveSession({
      access_token: "expired",
      refresh_token: "refresh-1",
      expires_in: 900,
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access-2",
            refresh_token: "refresh-2",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(eventPayload), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(eventPayload), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const [first, second] = await Promise.all([
      getEvent("event-1"),
      getEvent("event-1"),
    ]);

    expect(first.id).toBe("event-1");
    expect(second.id).toBe("event-1");
    const refreshCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).endsWith("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it("clears a failed login session without clearing a newer session", async () => {
    let rejectProfile: ((reason?: unknown) => void) | undefined;
    let resolveProfileStarted: (() => void) | undefined;
    const profileRequest = new Promise<Response>((_, reject) => {
      rejectProfile = reject;
    });
    const profileStarted = new Promise<void>((resolve) => {
      resolveProfileStarted = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "login-access",
            refresh_token: "login-refresh",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockImplementationOnce(() => {
        resolveProfileStarted?.();
        return profileRequest;
      });
    vi.stubGlobal("fetch", fetchMock);

    const pendingLogin = login("operator@example.com", "password");
    await profileStarted;
    saveSession({
      access_token: "new-access",
      refresh_token: "new-refresh",
      expires_in: 900,
    });
    rejectProfile?.(new Error("profile unavailable"));

    await expect(pendingLogin).rejects.toThrow("profile unavailable");
    expect(sessionStorage.getItem("sentineliq.auth")).toContain("new-access");
  });

  it("does not let a completed refresh overwrite a newer login session", async () => {
    let resolveRefresh: ((response: Response) => void) | undefined;
    const refreshResponse = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    saveSession({
      access_token: "old-access",
      refresh_token: "old-refresh",
      expires_in: 900,
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockImplementationOnce(() => refreshResponse);
    vi.stubGlobal("fetch", fetchMock);

    const pendingRequest = getEvent("event-1");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    saveSession({
      access_token: "new-access",
      refresh_token: "new-refresh",
      expires_in: 900,
    });
    resolveRefresh?.(
      new Response(
        JSON.stringify({
          access_token: "stale-refreshed-access",
          refresh_token: "stale-refreshed-refresh",
          expires_in: 900,
        }),
        { status: 200 },
      ),
    );

    await expect(pendingRequest).rejects.toMatchObject({ status: 401 });
    expect(sessionStorage.getItem("sentineliq.auth")).toContain("new-access");
  });
});
