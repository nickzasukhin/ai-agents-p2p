import { useEffect, useState, useRef } from 'react'
import { fetchRecentEvents, subscribeToEvents, type AgentEvent } from '../api'
import { timeAgo } from './ErrorBoundary'

type Props = {
  wsEvents?: AgentEvent[]
  wsConnected?: boolean
}

const eventIcons: Record<string, string> = {
  match_found: '\u{1F3AF}',
  negotiation_started: '\u{1F91D}',
  negotiation_received: '\u{1F4E9}',
  negotiation_update: '\u{1F504}',
  negotiation_accepted: '\u2705',
  negotiation_rejected: '\u274C',
  negotiation_timeout: '\u23F0',
  match_confirmed: '\u{1F389}',
  match_declined: '\u{1F6AB}',
  agent_discovered: '\u{1F50D}',
  discovery_cycle: '\u{1F4E1}',
  system_error: '\u26A0\uFE0F',
  project_created: '\u{1F4CB}',
  project_recruiting: '\u{1F4E2}',
  project_active: '\u{1F680}',
  project_stalled: '\u23F8\uFE0F',
  project_completed: '\u{1F3C6}',
  project_suggestion: '\u{1F4A1}',
}

const eventLabels: Record<string, string> = {
  match_found: 'Match Found',
  negotiation_started: 'Negotiation Started',
  negotiation_received: 'Proposal Received',
  negotiation_update: 'Negotiation Update',
  negotiation_accepted: 'Accepted',
  negotiation_rejected: 'Rejected',
  negotiation_timeout: 'Timed Out',
  match_confirmed: 'Confirmed!',
  match_declined: 'Declined',
  agent_discovered: 'Agent Discovered',
  discovery_cycle: 'Discovery',
  system_error: 'Error',
  project_created: 'Project Created',
  project_recruiting: 'Recruiting',
  project_active: 'Project Active',
  project_stalled: 'Project Stalled',
  project_completed: 'Project Done',
  project_suggestion: 'Suggestion',
}

export default function EventFeed({ wsEvents, wsConnected }: Props) {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [live, setLive] = useState(false)
  const feedRef = useRef<HTMLDivElement>(null)

  // Use WS-pushed events when available
  useEffect(() => {
    if (wsEvents && wsEvents.length > 0) {
      setLive(true)
      setEvents(wsEvents)
    }
  }, [wsEvents])

  useEffect(() => {
    // Load recent events on mount
    fetchRecentEvents()
      .then(d => setEvents(d.events || []))
      .catch(() => {})

    // Only use SSE if WebSocket is not connected
    if (wsConnected) return

    const es = subscribeToEvents((event) => {
      setLive(true)
      setEvents(prev => {
        const newEvents = [...prev, event as AgentEvent]
        return newEvents.slice(-50)
      })
    })

    return () => es.close()
  }, [wsConnected])

  useEffect(() => {
    // Auto-scroll to bottom
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight
    }
  }, [events])

  return (
    <div className="event-panel animate-in">
      <div className="panel-header">
        <h3>
          Events
          {live && <span className="live-dot" />}
        </h3>
        <span className="event-count">{events.length}</span>
      </div>

      <div className="event-feed" ref={feedRef}>
        {events.length === 0 ? (
          <div className="empty-state">
            <p>No events yet. Start discovery to see activity.</p>
          </div>
        ) : (
          events.map((e, i) => (
            <div key={e.id || i} className="event-item stagger-item">
              <span className="event-icon">{eventIcons[e.type] || '\u{1F4CB}'}</span>
              <div className="event-body">
                <span className="event-label">{eventLabels[e.type] || e.type}</span>
                {e.data?.their_name && (
                  <span className="event-detail">{e.data.their_name}</span>
                )}
                {e.data?.summary && (
                  <span className="event-summary">{e.data.summary}</span>
                )}
              </div>
              <span className="event-time" title={new Date(e.timestamp).toLocaleString()}>
                {timeAgo(e.timestamp)}
              </span>
            </div>
          ))
        )}
      </div>

      <style>{`
        .event-panel {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 20px;
          display: flex;
          flex-direction: column;
        }
        .event-panel .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }
        .event-panel .panel-header h3 {
          font-size: 16px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .live-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--success);
          animation: pulse 1.5s infinite;
        }
        .event-count {
          font-size: 12px;
          color: var(--text-muted);
          background: var(--bg-secondary);
          padding: 2px 8px;
          border-radius: 10px;
        }
        .event-feed {
          flex: 1;
          overflow-y: auto;
          max-height: 400px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .event-item {
          display: flex;
          align-items: flex-start;
          gap: 10px;
          padding: 8px 10px;
          border-radius: var(--radius-sm);
          background: var(--bg-secondary);
          font-size: 13px;
        }
        .event-icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; }
        .event-body {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .event-label { font-weight: 500; }
        .event-detail { font-size: 12px; color: var(--text-secondary); }
        .event-summary {
          font-size: 11px;
          color: var(--success);
          font-style: italic;
        }
        .event-time {
          font-size: 11px;
          color: var(--text-muted);
          white-space: nowrap;
          cursor: default;
        }
        .empty-state {
          text-align: center;
          padding: 32px;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  )
}
