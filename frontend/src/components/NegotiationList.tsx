import { useEffect, useState } from 'react'
import {
  fetchNegotiations,
  approveNegotiation,
  rejectNegotiation,
  type Negotiation,
} from '../api'
import { ConfirmDialog, Skeleton, timeAgo } from './ErrorBoundary'

type Props = {
  refreshTrigger?: number
  wsNegotiations?: Negotiation[] | null
  onOpenChat?: (negId: string) => void
}

const stateColors: Record<string, string> = {
  proposed: 'badge-negotiating',
  counter: 'badge-negotiating',
  evaluating: 'badge-negotiating',
  accepted: 'badge-pending',
  owner_review: 'badge-pending',
  confirmed: 'badge-confirmed',
  rejected: 'badge-rejected',
  declined: 'badge-rejected',
  timeout: 'badge-rejected',
}

const stateLabels: Record<string, string> = {
  proposed: 'Proposed',
  counter: 'Counter',
  evaluating: 'Evaluating...',
  accepted: 'Accepted',
  owner_review: 'Needs Approval',
  confirmed: 'Confirmed',
  rejected: 'Rejected',
  declined: 'Declined',
  timeout: 'Timed Out',
}

type StateFilter = 'all' | 'active' | 'pending' | 'completed'

const STATE_GROUPS: Record<StateFilter, string[]> = {
  all: [],
  active: ['proposed', 'counter', 'evaluating'],
  pending: ['accepted', 'owner_review'],
  completed: ['confirmed', 'rejected', 'declined', 'timeout'],
}

export default function NegotiationList({ refreshTrigger, wsNegotiations, onOpenChat }: Props) {
  const [negotiations, setNegotiations] = useState<Negotiation[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState<StateFilter>('all')
  const [confirm, setConfirm] = useState<{
    type: 'approve' | 'reject'
    id: string
    name: string
  } | null>(null)

  // Use WS-pushed negotiations when available
  useEffect(() => {
    if (wsNegotiations) {
      setNegotiations(wsNegotiations)
      setInitialLoading(false)
    }
  }, [wsNegotiations])

  const refresh = () => {
    fetchNegotiations()
      .then(d => setNegotiations(d.negotiations || []))
      .catch(() => {})
      .finally(() => setInitialLoading(false))
  }

  useEffect(() => { refresh() }, [refreshTrigger])

  const handleApprove = async (id: string) => {
    setLoading(id)
    try { await approveNegotiation(id); refresh() } catch {}
    setLoading(null)
    setConfirm(null)
  }

  const handleReject = async (id: string) => {
    setLoading(id)
    try { await rejectNegotiation(id); refresh() } catch {}
    setLoading(null)
    setConfirm(null)
  }

  const filtered = negotiations.filter(neg => {
    if (search) {
      const q = search.toLowerCase()
      if (!neg.their_name.toLowerCase().includes(q)
        && !neg.collaboration_summary?.toLowerCase().includes(q)) {
        return false
      }
    }
    if (stateFilter !== 'all') {
      const group = STATE_GROUPS[stateFilter]
      if (!group.includes(neg.state)) return false
    }
    return true
  })

  if (initialLoading) {
    return (
      <div className="neg-panel animate-in">
        <div className="panel-header"><h3>Negotiations</h3></div>
        <Skeleton cards={2} />
      </div>
    )
  }

  if (negotiations.length === 0) return null

  return (
    <div className="neg-panel animate-in">
      <div className="panel-header">
        <h3>Negotiations <span className="neg-count">{negotiations.length}</span></h3>
        <button className="btn-outline" onClick={refresh}>Refresh</button>
      </div>

      {negotiations.length > 2 && (
        <div className="search-wrapper">
          <input
            type="text"
            className="search-input"
            placeholder="Search negotiations..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      )}

      <div className="filter-bar">
        {(['all', 'active', 'pending', 'completed'] as StateFilter[]).map(f => (
          <button
            key={f}
            className={`filter-btn ${stateFilter === f ? 'active' : ''}`}
            onClick={() => setStateFilter(f)}
          >
            {f}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state"><p>No negotiations match your filter.</p></div>
      ) : (
        <div className="neg-list">
          {filtered.map(neg => (
            <div key={neg.id} className={`neg-card stagger-item ${neg.is_terminal ? 'terminal' : ''}`}>
              <div className="neg-header" onClick={() => setExpanded(expanded === neg.id ? null : neg.id)}>
                <div className="neg-info">
                  <span className="neg-name">{neg.their_name}</span>
                  <span className={`badge ${stateColors[neg.state] || ''}`}>
                    {stateLabels[neg.state] || neg.state}
                  </span>
                </div>
                <div className="neg-meta">
                  <span className="neg-round">Round {neg.current_round}/{neg.max_rounds}</span>
                  <span className="neg-score">{(neg.match_score * 100).toFixed(0)}%</span>
                  <span className="neg-time">{timeAgo(neg.updated_at)}</span>
                </div>
              </div>

              {neg.collaboration_summary && (
                <p className="neg-summary">{neg.collaboration_summary}</p>
              )}

              {/* Actions */}
              <div className="neg-actions">
                {neg.state === 'proposed' && (
                  <span className="sent-badge">Proposal Sent — waiting for response</span>
                )}
                {neg.state === 'owner_review' && (
                  <>
                    <button className="btn-success"
                      onClick={() => setConfirm({ type: 'approve', id: neg.id, name: neg.their_name })}
                      disabled={loading === neg.id}>
                      Approve
                    </button>
                    <button className="btn-danger"
                      onClick={() => setConfirm({ type: 'reject', id: neg.id, name: neg.their_name })}
                      disabled={loading === neg.id}>
                      Decline
                    </button>
                  </>
                )}
                {neg.state === 'confirmed' && onOpenChat && (
                  <button className="btn-outline" onClick={() => onOpenChat(neg.id)}>
                    View Chat
                  </button>
                )}
              </div>

              {/* Expanded message history */}
              {expanded === neg.id && (
                <div className="neg-messages">
                  {neg.messages.map((msg, i) => {
                    const isOurs = msg.sender === neg.their_url ? false : true
                    return (
                      <div key={i} className={`msg ${isOurs ? 'msg-ours' : 'msg-theirs'}`}>
                        <div className="msg-header">
                          <span className="msg-sender">{isOurs ? 'You' : neg.their_name}</span>
                          <span className="msg-time">R{msg.round} &middot; {timeAgo(msg.timestamp)}</span>
                        </div>
                        <p className="msg-content">{msg.content}</p>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Confirm Dialog */}
      {confirm && (
        <ConfirmDialog
          title={confirm.type === 'approve' ? 'Approve Collaboration?' : 'Decline Collaboration?'}
          message={confirm.type === 'approve'
            ? `Approve collaboration with ${confirm.name}? This will confirm the partnership.`
            : `Decline collaboration with ${confirm.name}? This action cannot be undone.`}
          confirmLabel={confirm.type === 'approve' ? 'Approve' : 'Decline'}
          confirmVariant={confirm.type === 'approve' ? 'success' : 'danger'}
          onConfirm={() => confirm.type === 'approve'
            ? handleApprove(confirm.id)
            : handleReject(confirm.id)}
          onCancel={() => setConfirm(null)}
        />
      )}

      <style>{`
        .neg-panel {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 20px;
        }
        .neg-count {
          font-size: 12px;
          color: var(--text-muted);
          background: var(--bg-secondary);
          padding: 1px 8px;
          border-radius: 10px;
          margin-left: 6px;
          font-weight: 400;
        }
        .neg-list { display: flex; flex-direction: column; gap: 12px; }
        .neg-card {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: var(--radius-sm);
          padding: 16px;
          transition: border-color 0.2s;
        }
        .neg-card:hover { border-color: var(--accent); }
        .neg-card.terminal { opacity: 0.7; }
        .neg-card.terminal:hover { border-color: var(--border); }
        .neg-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          cursor: pointer;
          margin-bottom: 8px;
        }
        .neg-info { display: flex; align-items: center; gap: 10px; }
        .neg-name { font-weight: 600; font-size: 15px; }
        .neg-meta { display: flex; gap: 12px; align-items: center; }
        .neg-round { font-size: 12px; color: var(--text-muted); }
        .neg-score { font-weight: 700; color: var(--accent-light); }
        .neg-time { font-size: 11px; color: var(--text-muted); }
        .neg-summary {
          font-size: 13px;
          color: var(--success);
          margin-bottom: 12px;
          padding: 8px 12px;
          background: rgba(0,206,201,0.05);
          border-radius: var(--radius-sm);
          border-left: 3px solid var(--success);
        }
        .neg-actions { display: flex; gap: 8px; margin-top: 8px; align-items: center; }
        .sent-badge {
          font-size: 12px;
          color: var(--success);
          padding: 4px 12px;
          background: rgba(0,206,201,0.08);
          border: 1px solid rgba(0,206,201,0.2);
          border-radius: 4px;
        }
        .neg-messages {
          margin-top: 16px;
          border-top: 1px solid var(--border);
          padding-top: 12px;
          display: flex;
          flex-direction: column;
          gap: 10px;
          max-height: 400px;
          overflow-y: auto;
        }
        .msg {
          padding: 10px 14px;
          border-radius: var(--radius-sm);
          font-size: 13px;
        }
        .msg-ours {
          background: rgba(108,92,231,0.1);
          border-left: 3px solid var(--accent);
          margin-left: 20px;
        }
        .msg-theirs {
          background: rgba(0,206,201,0.05);
          border-left: 3px solid var(--success);
          margin-right: 20px;
        }
        .msg-header {
          display: flex;
          justify-content: space-between;
          margin-bottom: 6px;
        }
        .msg-sender { font-weight: 600; font-size: 12px; }
        .msg-time { font-size: 11px; color: var(--text-muted); }
        .msg-content {
          color: var(--text-secondary);
          line-height: 1.5;
          white-space: pre-wrap;
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
