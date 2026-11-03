import React from 'react'

/**
 * SentinelIQ root application component.
 * Shell only at Gate 2 — full dashboard built at Gate 16.
 */
function App(): React.JSX.Element {
  return (
    <div className="app">
      <header className="app-header" role="banner">
        <h1>SentinelIQ</h1>
        <p className="app-tagline">AI Security Decision Intelligence</p>
      </header>
      <main className="app-main" role="main">
        <div className="status-card" aria-label="System status">
          <h2>System Status</h2>
          <p>
            Application shell initialised. Operator dashboard coming in Gate 16.
          </p>
          <p className="notice">
            <strong>Note:</strong> This system provides supervised recommendations only.
            All security decisions require human review and approval.
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
