import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearSession, getEvent, saveSession } from '../api'

const eventPayload = {
  id: 'event-1',
  provider_event_id: null,
  source_adapter: 'simulator',
  event_type: 'person_detected',
  event_timestamp: '2026-01-01T12:00:00Z',
  location_id: 'HQ',
  facility_id: null,
  camera_id: null,
  zone: null,
  detector_confidence: 0.9,
  thumbnail_url: null,
  status: 'awaiting_review',
  risk: { score: 75, level: 'high' },
  confidence: { score: 0.8, level: 'high' },
  agent_run_id: null,
  created_at: '2026-01-01T12:00:00Z',
  updated_at: '2026-01-01T12:00:00Z',
}

beforeEach(() => {
  clearSession()
  vi.restoreAllMocks()
})

describe('API authentication', () => {
  it('uses one refresh rotation for concurrent 401 responses', async () => {
    saveSession({ access_token: 'expired', refresh_token: 'refresh-1', expires_in: 900 })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: 'access-2',
        refresh_token: 'refresh-2',
        expires_in: 900,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(eventPayload), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(eventPayload), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const [first, second] = await Promise.all([
      getEvent('event-1'),
      getEvent('event-1'),
    ])

    expect(first.id).toBe('event-1')
    expect(second.id).toBe('event-1')
    const refreshCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).endsWith('/auth/refresh'),
    )
    expect(refreshCalls).toHaveLength(1)
  })
})
