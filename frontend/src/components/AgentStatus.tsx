import { useEffect, useState } from 'react'
import { fetchHealth } from '../api'

type Health = {
  status: string
  agent: string
  skills: number
  version: string
  discovery?: {
    is_running: boolean
    runs_completed: number
    discovered_agents: number
    matches: number
    peers_in_registry: number
  }
  negotiations?: {
    total: number
    active: number
    pending_approval: number
    confirmed: number
    rejected: number
  }
  events?: {
    total: number
    subscribers: number
  }
}

type Props = {
  wsHealth?: any
  wsConnected?: boolean
}

export default function AgentStatus({ wsHealth, wsConnected }: Props) {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState(false)

  // Use WS-pushed health when available
  useEffect(() => {
    if (wsHealth) {
      setHealth(wsHealth)
      setError(false)
    }
  }, [wsHealth])

  const refresh = () => {
    fetchHealth()
      .then(d => { setHealth(d); setError(false) })
      .catch(() => setError(true))
  }

  // Only poll if WebSocket is not connected
  useEffect(() => {
    refresh()
    if (wsConnected) return
    const iv = setInterval(refresh, 5000)
    return () => clearInterval(iv)
  }, [wsConnected])

  if (error) {
    return (
      <div className="status-card offline">
        <div className="status-dot" />
        <span>Agent Offline</span>
      </div>
    )
  }

  if (!health) return <div className="status-card"><span className="pulse">Connecting...</span></div>

  const d = health.discovery
  const n = health.negotiations

  return (
    <div className="status-card animate-in">
      <div className="status-header">
        <div className="status-dot online" />
        <h2>{health.agent}</h2>
        <span className="badge badge-online">Online</span>
      </div>

      <div className="status-grid">
        <div className="stat">
          <span className="stat-value">{health.skills}</span>
          <span className="stat-label">Skills</span>
        </div>
        <div className="stat">
          <span className="stat-value">{d?.discovered_agents ?? 0}</span>
          <span className="stat-label">Discovered</span>
        </div>
        <div className="stat">
          <span className="stat-value">{d?.matches ?? 0}</span>
          <span className="stat-label">Matches</span>
        </div>
        <div className="stat">
          <span className="stat-value">{n?.active ?? 0}</span>
          <span className="stat-label">Active Talks</span>
        </div>
        <div className="stat">
          <span className="stat-value highlight">{n?.pending_approval ?? 0}</span>
          <span className="stat-label">Pending</span>
        </div>
        <div className="stat">
          <span className="stat-value success">{n?.confirmed ?? 0}</span>
          <span className="stat-label">Confirmed</span>
        </div>
      </div>

      <style>{`
        .status-card {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 20px;
        }
        .status-card.offline { border-color: var(--danger); }
        .status-header {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 16px;
        }
        .status-header h2 { font-size: 18px; flex: 1; }
        .status-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background: var(--text-muted);
        }
        .status-dot.online {
          background: var(--success);
          box-shadow: 0 0 8px rgba(0,206,201,0.5);
        }
        .status-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
        }
        .stat {
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 10px;
          background: var(--bg-secondary);
          border-radius: var(--radius-sm);
        }
        .stat-value {
          font-size: 24px;
          font-weight: 700;
          color: var(--text-primary);
        }
        .stat-value.highlight { color: var(--warning); }
        .stat-value.success { color: var(--success); }
        .stat-label {
          font-size: 11px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-top: 2px;
        }
      `}</style>
    </div>
  )
}
