import { useEffect, useState } from 'react'
import { fetchMatches, runDiscovery, startNegotiations, type Match } from '../api'
import { Skeleton } from './ErrorBoundary'

type Props = {
  onRefresh?: () => void
  wsMatches?: Match[] | null
}

export default function MatchList({ onRefresh, wsMatches }: Props) {
  const [matches, setMatches] = useState<Match[]>([])
  const [loading, setLoading] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [search, setSearch] = useState('')

  // Use WS-pushed matches when available
  useEffect(() => {
    if (wsMatches) {
      setMatches(wsMatches)
      setInitialLoading(false)
    }
  }, [wsMatches])

  const refresh = () => {
    fetchMatches()
      .then(d => setMatches(d.matches || []))
      .catch(() => {})
      .finally(() => setInitialLoading(false))
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
        }
        .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
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
          grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
          gap: 10px;
        }
        .match-card {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: var(--radius-sm);
          padding: 12px 14px;
          transition: border-color 0.2s;
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
        .match-reasons { display: flex; flex-direction: column; gap: 3px; }
        .reason {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          line-height: 1.3;
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
      `}</style>
    </div>
  )
}
