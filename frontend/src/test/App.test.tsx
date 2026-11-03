import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from '../App'

describe('App', () => {
  it('renders the SentinelIQ heading', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('SentinelIQ')
  })

  it('renders the tagline', () => {
    render(<App />)
    expect(screen.getByText('AI Security Decision Intelligence')).toBeInTheDocument()
  })

  it('renders the human oversight notice', () => {
    render(<App />)
    expect(
      screen.getByText(/All security decisions require human review/i),
    ).toBeInTheDocument()
  })

  it('has accessible landmark regions', () => {
    render(<App />)
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
  })
})
