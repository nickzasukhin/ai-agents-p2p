import { useEffect, useState } from 'react'
import { fetchMatches, fetchNegotiations as fetchNegs, runDiscovery, startNegotiations, startSingleNegotiation, sendNegotiation, type Match, type Negotiation } from '../api'
import { Skeleton } from './ErrorBoundary'

type Props = {
  onRefresh?: () => void
  wsMatches?: Match[] | null
  wsNegotiations?: Negotiation[] | null
}

export default function MatchList({ onRefresh, wsMatches, wsNegotiations }: Props) {
  const [matches, setMatches] = useState<Match[]>([])
  const [negotiations, setNegotiations] = useState<Negotiation[]>([])
  const [loading, setLoading] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [negotiating, setNegotiating] = useState<Set<string>>(new Set())
  const [sent, setSent] = useState<Set<string>>(new Set())

  // Use WS-pushed data when available
  useEffect(() => {
    if (wsMatches) {
      setMatches(wsMatches)
      setInitialLoading(false)
    }
  }, [wsMatches])

  useEffect(() => {
    if (wsNegotiations) setNegotiations(wsNegotiations)
  }, [wsNegotiations])

  const refresh = () => {
    fetchMatches()
      .then(d => setMatches(d.matches || []))
      .catch(() => {})
      .finally(() => setInitialLoading(false))
    fetchNegs()
      .then(d => setNegotiations(d.negotiations || []))
      .catch(() => {})
  }

  useEffect(() => { refresh() }, [])

  const handleDiscover = async () => {
    setLoading(true)
    try {
      await runDiscovery()
      refresh()
      onRefresh?.()
    } catch {}
    setLoading(false)
  }

  const handleNegotiate = async () => {
    setLoading(true)
    try {
      await startNegotiations()
      onRefresh?.()
    } catch {}
    setLoading(false)
  }

  const handleNegotiateOne = async (agentUrl: string) => {
    setNegotiating(prev => new Set(prev).add(agentUrl))
    try {
      const result = await startSingleNegotiation(agentUrl)
      // Auto-send proposal immediately (no intermediate "Send Proposal" step)
      if (result.negotiation_id) {
        try { await sendNegotiation(result.negotiation_id) } catch {}
      }
      setSent(prev => new Set(prev).add(agentUrl))
      // Refresh negotiations to get new state
      fetchNegs()
        .then(d => setNegotiations(d.negotiations || []))
        .catch(() => {})
      onRefresh?.()
    } catch {}
    setNegotiating(prev => { const s = new Set(prev); s.delete(agentUrl); return s })
  }

  // Build negotiation lookup by their_url
  const negByUrl = new Map<string, Negotiation>()
  for (const n of negotiations) {
    negByUrl.set(n.their_url.replace(/\/+$/, ''), n)
  }

  const filtered = matches.filter(m =>
    !search || m.agent_name.toLowerCase().includes(search.toLowerCase())
      || m.description?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="match-panel animate-in">
      <div className="panel-header">
        <h3>Matches</h3>
        <div className="panel-actions">
          <button className="btn-outline" onClick={handleDiscover} disabled={loading}>
            {loading ? '...' : 'Discover'}
          </button>
          {matches.length > 0 && (
            <button className="btn-primary" onClick={handleNegotiate} disabled={loading}>
              Negotiate All
            </button>
          )}
        </div>
      </div>

      {matches.length > 2 && (
        <div className="search-wrapper">
          <input
            type="text"
            className="search-input"
            placeholder="Search matches..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      )}

      {initialLoading ? (
        <Skeleton cards={3} />
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <p>{search ? 'No matches found for your search.' : 'No matches yet. Click Discover to find agents.'}</p>
        </div>
      ) : (
        <div className="match-list">
          {filtered.map((m, idx) => (
            <div key={m.agent_url} className="match-card stagger-item">
              <div className="match-header">
                <div className="match-title-row">
                  <span className="match-name">{m.agent_name}</span>
                  {m.is_mutual && <span className="badge badge-confirmed">Mutual</span>}
                </div>
                <span className="score">{(m.overall_score * 100).toFixed(0)}%</span>
              </div>
              <p className="match-desc">{m.description}</p>
              <div className="match-reasons">
                {m.top_matches?.slice(0, 2).map((sm, i) => (
                  <div key={i} className="reason">
                    <span className={`reason-dir ${sm.direction === 'we_need_they_offer' ? 'dir-they' : 'dir-we'}`}>
                      {sm.direction === 'we_need_they_offer' ? 'THEY' : 'WE'}
                    </span>
                    <span className="reason-score">{(sm.similarity * 100).toFixed(0)}%</span>
                    <span className="reason-text">
                      {sm.direction === 'we_need_they_offer' ? sm.their_text : sm.our_text}
                    </span>
                  </div>
                ))}
              </div>
              <div className="match-actions">
                {(() => {
                  const neg = negByUrl.get(m.agent_url.replace(/\/+$/, ''))
                  if (neg) {
                    const stateLabel: Record<string, string> = {
                      init: 'Initiating',
                      proposed: 'Proposal Sent',
                      counter: 'Counter-proposal',
                      evaluating: 'Evaluating',
                      accepted: 'Accepted',
                      owner_review: 'Needs Review',
                      confirmed: 'Confirmed',
                      rejected: 'Rejected',
                      timeout: 'Timed Out',
                      declined: 'Declined',
                    }
                    const label = stateLabel[neg.state] || neg.state
                    const isActive = !neg.is_terminal
                    return (
                      <span className={`neg-status ${isActive ? 'neg-active' : neg.state === 'confirmed' ? 'neg-confirmed' : 'neg-terminal'}`}>
                        {label}
                        {isActive && <span className="neg-dot" />}
                      </span>
                    )
                  }
                  if (sent.has(m.agent_url)) {
                    return <span className="neg-status neg-active">Sending...<span className="neg-dot" /></span>
                  }
                  return (
                    <button
                      className="btn-negotiate"
                      onClick={() => handleNegotiateOne(m.agent_url)}
                      disabled={negotiating.has(m.agent_url)}
                    >
                      {negotiating.has(m.agent_url) ? '...' : 'Negotiate'}
                    </button>
                  )
                })()}
              </div>
            </div>
          ))}
        </div>
      )}

      <style>{`
        .match-panel {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 20px;
          min-width: 0;
        }
        .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
          flex-wrap: wrap;
          gap: 8px;
        }
        .panel-header h3 { font-size: 16px; }
        .panel-actions { display: flex; gap: 8px; }
        .empty-state {
          text-align: center;
          padding: 32px;
          color: var(--text-muted);
        }
        .match-list {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(min(340px, 100%), 1fr));
          gap: 10px;
        }
        .match-card {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: var(--radius-sm);
          padding: 12px 14px;
          transition: border-color 0.2s;
          min-width: 0;
          overflow: hidden;
        }
        .match-card:hover {
          border-color: var(--accent);
        }
        .match-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 4px;
          gap: 8px;
        }
        .match-title-row {
          display: flex;
          align-items: center;
          gap: 6px;
          min-width: 0;
        }
        .match-name {
          font-weight: 600;
          font-size: 14px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .score {
          font-size: 18px;
          font-weight: 700;
          color: var(--accent-light);
          flex-shrink: 0;
        }
        .match-desc {
          font-size: 12px;
          color: var(--text-muted);
          margin-bottom: 8px;
          line-height: 1.4;
          display: -webkit-box;
          -webkit-line-clamp: 1;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        .match-reasons { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
        .reason {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          line-height: 1.3;
          min-width: 0;
        }
        .reason-dir {
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.05em;
          min-width: 28px;
          flex-shrink: 0;
        }
        .dir-they { color: var(--success); }
        .dir-we { color: var(--accent-light); }
        .reason-score {
          color: var(--text-secondary);
          font-weight: 600;
          min-width: 26px;
          flex-shrink: 0;
        }
        .reason-text {
          color: var(--text-muted);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .match-actions {
          margin-top: 8px;
          display: flex;
          justify-content: flex-end;
        }
        .btn-negotiate {
          background: rgba(108,92,231,0.15);
          color: var(--accent-light);
          border: 1px solid var(--accent);
          padding: 4px 14px;
          font-size: 11px;
          border-radius: 4px;
        }
        .btn-negotiate:hover {
          background: var(--accent);
          color: white;
        }
        .btn-negotiate:disabled {
          opacity: 0.5;
          cursor: not-allowed;
          transform: none;
        }
        .neg-status {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          font-weight: 600;
          padding: 4px 12px;
          border-radius: 4px;
        }
        .neg-active {
          background: rgba(108,92,231,0.15);
          color: var(--accent-light);
          border: 1px solid var(--accent);
        }
        .neg-confirmed {
          background: rgba(0,200,83,0.15);
          color: var(--success);
          border: 1px solid var(--success);
        }
        .neg-terminal {
          background: rgba(255,255,255,0.05);
          color: var(--text-muted);
          border: 1px solid var(--border);
        }
        .neg-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: currentColor;
          animation: pulse-dot 1.5s ease-in-out infinite;
        }
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  )
}
