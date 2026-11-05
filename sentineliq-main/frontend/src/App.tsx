import { useEffect, useState } from 'react';

interface SecurityEvent {
  id: string | number;
  title: string;
  camera_location: string;
  severity: string;
  timestamp: string;
  description: string;
  status: string;
}

function App() {
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE_URL = "http://127.0.0.1:8000/api/v1";

  // Fetch events from FastAPI backend
  const fetchTriageFeed = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/events/`, {
        headers: {
          "Content-Type": "application/json"
        }
      });
      if (!response.ok) {
        throw new Error(`Server returned status ${response.status}`);
      }
      const data = await response.json();
      setEvents(Array.isArray(data) ? data : data.items || []);
      setError(null);
    } catch (err: any) {
      console.error("Error fetching events:", err);
      setError("Failed to connect to backend triage feed. Ensure FastAPI server is running.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTriageFeed();
  }, []);

  // Handle operator decision (Approve / Escalate / Investigate)
  const handleDecision = async (eventId: string | number, decisionType: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/escalations/${eventId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          action: decisionType,
          operator_notes: `Processed via Gate 16 Operator Dashboard as ${decisionType}`
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to submit operator decision");
      }

      alert(`Successfully submitted decision: ${decisionType} for event ID ${eventId}`);
      fetchTriageFeed();
    } catch (err: any) {
      console.error("Decision error:", err);
      alert(`Error processing decision: ${err.message}`);
    }
  };

  return (
    <div style={{ fontFamily: 'Segoe UI, Tahoma, Geneva, Verdana, sans-serif', minHeight: '100vh', backgroundColor: '#f4f6f9', padding: '20px' }}>
      {/* Header */}
      <header style={{ backgroundColor: '#1e293b', color: '#fff', padding: '20px 30px', borderRadius: '8px', marginBottom: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '24px' }}>SentinelIQ</h1>
          <p style={{ margin: '5px 0 0 0', color: '#94a3b8', fontSize: '14px' }}>AI Security Decision Intelligence | Gate 16 Operator Dashboard</p>
        </div>
        <button 
          onClick={fetchTriageFeed}
          style={{ backgroundColor: '#3b82f6', color: '#fff', border: 'none', padding: '10px 16px', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' }}
        >
          Refresh Feed
        </button>
      </header>

      {/* Safety Notice */}
      <div style={{ backgroundColor: '#eff6ff', borderLeft: '4px solid #3b82f6', padding: '15px', borderRadius: '4px', marginBottom: '20px', color: '#1e40af' }}>
        <strong>Supervised Operations Notice:</strong> This system provides AI-assisted recommendations only. Security personnel act as the final adjudicators for all escalations and incident reviews.
      </div>

      {/* Main Content / Triage Queue */}
      <main style={{ backgroundColor: '#fff', padding: '25px', borderRadius: '8px', boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
        <h2 style={{ marginTop: 0, borderBottom: '2px solid #e2e8f0', paddingBottom: '10px', fontSize: '18px', color: '#334155' }}>
          Live Triage & Incident Feed
        </h2>

        {loading && <p style={{ color: '#64748b' }}>Loading real-time security events from backend...</p>}
        {error && <p style={{ color: '#ef4444', backgroundColor: '#fef2f2', padding: '10px', borderRadius: '4px' }}>{error}</p>}

        {!loading && !error && events.length === 0 && (
          <div style={{ textAlign: 'center', padding: '40px', color: '#64748b' }}>
            <p>No active security events found in the queue.</p>
            <p style={{ fontSize: '13px' }}>You can seed or add test events via Swagger UI at <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">http://127.0.0.1:8000/docs</a>.</p>
          </div>
        )}

        {!loading && events.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '14px' }}>
              <thead>
                <tr style={{ backgroundColor: '#f8fafc', color: '#475569', borderBottom: '2px solid #e2e8f0' }}>
                  <th style={{ padding: '12px' }}>ID</th>
                  <th style={{ padding: '12px' }}>Incident / Title</th>
                  <th style={{ padding: '12px' }}>Location</th>
                  <th style={{ padding: '12px' }}>Severity</th>
                  <th style={{ padding: '12px' }}>Timestamp</th>
                  <th style={{ padding: '12px' }}>Status</th>
                  <th style={{ padding: '12px', textAlign: 'center' }}>Operator Actions</th>
                </tr>
              </thead>
              <tbody>
                {events.map((evt) => (
                  <tr key={evt.id} style={{ borderBottom: '1px solid #e2e8f0' }}>
                    <td style={{ padding: '12px', fontWeight: 'bold' }}>#{evt.id}</td>
                    <td style={{ padding: '12px' }}>{evt.title || evt.description || 'Security Alert'}</td>
                    <td style={{ padding: '12px' }}>{evt.camera_location || 'Gate 16 Warehouse'}</td>
                    <td style={{ padding: '12px' }}>
                      <span style={{ 
                        padding: '4px 8px', 
                        borderRadius: '4px', 
                        fontSize: '12px', 
                        fontWeight: 'bold',
                        backgroundColor: evt.severity === 'high' ? '#fee2e2' : '#fef3c7',
                        color: evt.severity === 'high' ? '#991b1b' : '#92400e'
                      }}>
                        {evt.severity || 'Normal'}
                      </span>
                    </td>
                    <td style={{ padding: '12px', color: '#64748b' }}>{new Date(evt.timestamp || Date.now()).toLocaleTimeString()}</td>
                    <td style={{ padding: '12px' }}>{evt.status || 'Pending'}</td>
                    <td style={{ padding: '12px', textAlign: 'center' }}>
                      <button 
                        onClick={() => handleDecision(evt.id, 'investigate')}
                        style={{ backgroundColor: '#f59e0b', color: '#fff', border: 'none', padding: '6px 10px', borderRadius: '4px', cursor: 'pointer', marginRight: '5px', fontSize: '12px' }}
                      >
                        Investigate
                      </button>
                      <button 
                        onClick={() => handleDecision(evt.id, 'escalate')}
                        style={{ backgroundColor: '#ef4444', color: '#fff', border: 'none', padding: '6px 10px', borderRadius: '4px', cursor: 'pointer', marginRight: '5px', fontSize: '12px' }}
                      >
                        Escalate
                      </button>
                      <button 
                        onClick={() => handleDecision(evt.id, 'dismiss')}
                        style={{ backgroundColor: '#10b981', color: '#fff', border: 'none', padding: '6px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
                      >
                        Dismiss
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;