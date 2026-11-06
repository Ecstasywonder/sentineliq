import { beforeEach, describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { AuthProvider } from '../auth'

const renderApp = () => render(<AuthProvider><App /></AuthProvider>)

beforeEach(() => {
  sessionStorage.clear()
  vi.restoreAllMocks()
})

describe('App', () => {
  it('renders an accessible sign-in form when unauthenticated', () => {
    renderApp()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Operator sign in')
    expect(screen.getByLabelText('Email address')).toBeRequired()
  })

  it('shows an authentication failure without exposing a technical error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: 'Invalid email or password.' } }), { status: 401 })))
    const user = userEvent.setup(); renderApp()
    await user.type(screen.getByLabelText('Email address'), 'operator@example.com')
    await user.type(screen.getByLabelText('Password'), 'bad-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
  })

  it('renders the human oversight notice', () => {
    renderApp()
    expect(
      screen.getByText(/All security decisions require human review/i),
    ).toBeInTheDocument()
  })

  it('renders queue data using the API event schema after login', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'access', refresh_token: 'refresh', expires_in: 900 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'u1', email: 'operator@example.com', full_name: 'Operator', roles: ['operator'], is_active: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'e1', provider_event_id: null, source_adapter: 'simulator', event_type: 'unauthorised_access', event_timestamp: '2026-01-01T12:00:00Z', location_id: 'HQ', facility_id: null, camera_id: null, zone: 'Door A', detector_confidence: .9, thumbnail_url: null, status: 'awaiting_review', risk: { score: .9, level: 'critical' }, confidence: { score: .8, level: 'high' }, agent_run_id: null, created_at: '2026-01-01T12:00:00Z', updated_at: '2026-01-01T12:00:00Z' }], total: 1, page: 1, page_size: 50, pages: 1 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock); const user = userEvent.setup(); renderApp()
    await user.type(screen.getByLabelText('Email address'), 'operator@example.com'); await user.type(screen.getByLabelText('Password'), 'password'); await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('unauthorised access')).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByRole('banner')).toBeInTheDocument()
  })

  it('opens an event detail view and makes assessment availability clear', async () => {
    const event = { id: 'e1', provider_event_id: null, source_adapter: 'simulator', event_type: 'unauthorised_access', event_timestamp: '2026-01-01T12:00:00Z', location_id: 'HQ', facility_id: null, camera_id: null, zone: 'Door A', detector_confidence: .9, thumbnail_url: null, status: 'awaiting_review', risk: { score: .9, level: 'critical' }, confidence: { score: .8, level: 'high' }, agent_run_id: null, created_at: '2026-01-01T12:00:00Z', updated_at: '2026-01-01T12:00:00Z' }
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'access', refresh_token: 'refresh', expires_in: 900 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'u1', email: 'operator@example.com', full_name: 'Operator', roles: ['operator'], is_active: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [event], total: 1, page: 1, page_size: 50, pages: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Assessment bundle not found.' }), { status: 404 })))
    const user = userEvent.setup(); renderApp()
    await user.type(screen.getByLabelText('Email address'), 'operator@example.com')
    await user.type(screen.getByLabelText('Password'), 'password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.click(await screen.findByRole('button', { name: /open unauthorised_access event/i }))
    expect(await screen.findByRole('heading', { name: 'unauthorised access' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run assessment' })).toBeInTheDocument()
  })

  it('shows supporting evidence and a recommendation in the event decision interface', async () => {
    const event = { id: 'e1', provider_event_id: null, source_adapter: 'simulator', event_type: 'unauthorised_access', event_timestamp: '2026-01-01T12:00:00Z', location_id: 'HQ', facility_id: null, camera_id: null, zone: 'Door A', detector_confidence: .9, thumbnail_url: null, status: 'awaiting_review', risk: { score: .9, level: 'critical' }, confidence: { score: .8, level: 'high' }, agent_run_id: null, created_at: '2026-01-01T12:00:00Z', updated_at: '2026-01-01T12:00:00Z' }
    const assessment = {
      event_id: 'e1',
      risk_policy_version: '1.0',
      risk_score: 82,
      risk_level: 'critical',
      risk_factors: [{ factor_id: 'restricted_area', label: 'Restricted area', weight: 25, direction: 'increase', triggered: true, contribution: 25 }],
      confidence_score: 0.81,
      confidence_level: 'high',
      confidence_reductions: [{ reason: 'Badge source unavailable', amount: 0.12 }],
      sources_available: 3,
      sources_required: 4,
      evidence_errors: {},
      assessed_at: '2026-01-01T12:05:00Z',
      explanation: {
        summary: 'Restricted activity was detected after hours without matching access records.',
        recommended_action: 'Escalate to the shift supervisor for manual review.',
        missing_evidence: ['Badge service status'],
        why: [{ text: 'No matching badge activity was found in the configured time window.', evidence_ids: ['ACCESS-12'] }],
      },
    }

    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'access', refresh_token: 'refresh', expires_in: 900 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'u1', email: 'operator@example.com', full_name: 'Operator', roles: ['operator'], is_active: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [event], total: 1, page: 1, page_size: 50, pages: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(event), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(assessment), { status: 200 })))

    const user = userEvent.setup(); renderApp()
    await user.type(screen.getByLabelText('Email address'), 'operator@example.com')
    await user.type(screen.getByLabelText('Password'), 'password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.click(await screen.findByRole('button', { name: /open unauthorised_access event/i }))

    expect(await screen.findByText(/Escalate to the shift supervisor/i)).toBeInTheDocument()
    expect(screen.getByText('Badge service status')).toBeInTheDocument()
    expect(screen.getByText('Decision timeline')).toBeInTheDocument()
  })
})
