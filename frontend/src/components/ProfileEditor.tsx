import { useEffect, useState, useCallback } from 'react'
import {
  fetchProfile, updateProfileFile, fetchIdentity,
  fetchGossipStats, fetchDhtStats, fetchCard, rebuildCard,
} from '../api'

type ProfileFiles = {
  'profile.md': string
  'skills.md': string
  'needs.md': string
}

type IdentityInfo = {
  did: string
  public_key: string
}

type NetworkStats = {
  gossip: { rounds: number; peers_learned: number; known_peers: number } | null
  dht: { is_running: boolean; udp_port: number; cached_peers: number } | null
}

type CardInfo = {
  name: string
  description: string
  skills: { id: string; name: string; description: string; tags: string[] }[]
  last_rebuild: string | null
  regenerating: boolean
}

const FILE_LABELS: Record<string, { label: string; icon: string; hint: string }> = {
  'profile.md': { label: 'Profile', icon: String.fromCodePoint(0x1F464), hint: 'Name, role, experience, bio' },
  'skills.md': { label: 'Skills', icon: String.fromCodePoint(0x26A1), hint: 'Expert, advanced, intermediate skills' },
  'needs.md': { label: 'Needs', icon: String.fromCodePoint(0x1F3AF), hint: 'Collaboration needs, learning goals, projects' },
}

export default function ProfileEditor() {
  const [files, setFiles] = useState<ProfileFiles | null>(null)
  const [identity, setIdentity] = useState<IdentityInfo | null>(null)
  const [network, setNetwork] = useState<NetworkStats>({ gossip: null, dht: null })
  const [card, setCard] = useState<CardInfo | null>(null)
  const [activeFile, setActiveFile] = useState<string>('profile.md')
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState<{ type: 'saved' | 'rebuilt' | 'error'; msg: string } | null>(null)
  const [expanded, setExpanded] = useState(true)
  const [rebuilding, setRebuilding] = useState(false)

  const loadCard = useCallback(() => {
    fetchCard()
      .then(d => { if (!d.error) setCard(d) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchProfile()
      .then(d => {
        setFiles(d.files)
        setEditContent(d.files['profile.md'] || '')
      })
      .catch(() => {})

    fetchIdentity()
      .then(d => {
        if (!d.error) setIdentity({ did: d.did, public_key: d.public_key })
      })
      .catch(() => {})

    loadCard()

    Promise.all([
      fetchGossipStats().catch(() => null),
      fetchDhtStats().catch(() => null),
    ]).then(([g, d]) => {
      setNetwork({ gossip: g?.error ? null : g, dht: d?.error ? null : d })
    })
  }, [loadCard])

  const switchFile = (fname: string) => {
    setActiveFile(fname)
    setEditContent(files?.[fname as keyof ProfileFiles] || '')
    setSaveResult(null)
  }

  const save = async () => {
    setSaving(true)
    setSaveResult(null)
    try {
      const result = await updateProfileFile(activeFile, editContent)
      setFiles(prev => prev ? { ...prev, [activeFile]: editContent } : prev)

      if (result.card_rebuild?.status === 'rebuilt') {
        const rb = result.card_rebuild
        setSaveResult({
          type: 'rebuilt',
          msg: `Card rebuilt: ${rb.new_skills} skills (was ${rb.old_skills})`,
        })
        loadCard()
      } else {
        setSaveResult({ type: 'saved', msg: 'Saved' })
      }
      setTimeout(() => setSaveResult(null), 4000)
    } catch {
      setSaveResult({ type: 'error', msg: 'Save failed' })
    }
    setSaving(false)
  }

  const manualRebuild = async () => {
    setRebuilding(true)
    try {
      const result = await rebuildCard()
      if (result.status === 'rebuilt') {
        setSaveResult({
          type: 'rebuilt',
          msg: `Rebuilt: ${result.new_name} (${result.new_skills} skills)`,
        })
        loadCard()
      }
      setTimeout(() => setSaveResult(null), 4000)
    } catch {}
    setRebuilding(false)
  }

  const didShort = identity?.did
    ? `${identity.did.slice(0, 20)}...${identity.did.slice(-8)}`
    : null

  return (
    <div className="profile-editor">
      <div className="pe-header" onClick={() => setExpanded(!expanded)}>
        <h3>{expanded ? '\u25BC' : '\u25B6'} Agent Profile & Identity</h3>
        {identity && <span className="pe-did-badge" title={identity.did}>{'🔑'} {didShort}</span>}
      </div>

      {expanded && (
        <div className="pe-body">
          {/* Card summary */}
          {card && (
            <div className="pe-card-summary">
              <div className="pe-card-header">
                <span className="pe-card-name">{'🤖'} {card.name}</span>
                <button
                  className="pe-rebuild-btn"
                  onClick={manualRebuild}
                  disabled={rebuilding}
                  title="Rebuild Agent Card from profile files"
                >
                  {rebuilding ? '⏳ Rebuilding...' : '🔄 Rebuild Card'}
                </button>
              </div>
              <div className="pe-card-desc">{card.description}</div>
              <div className="pe-card-skills">
                {card.skills.map(s => (
                  <span key={s.id} className="pe-skill-tag" title={s.description}>
                    {s.name}
                  </span>
                ))}
              </div>
              {card.last_rebuild && (
                <div className="pe-card-rebuilt">
                  Last rebuilt: {new Date(card.last_rebuild).toLocaleTimeString()}
                </div>
              )}
            </div>
          )}

          {/* Identity & Network Row */}
          <div className="pe-network-row">
            {identity && (
              <div className="pe-identity-card">
                <div className="pe-id-label">DID Identity</div>
                <code className="pe-did-full">{identity.did}</code>
              </div>
            )}
            <div className="pe-network-stats">
              {network.gossip && (
                <span className="pe-stat" title="Gossip Protocol">
                  {'📡'} Gossip: {network.gossip.known_peers} peers, {network.gossip.rounds} rounds
                </span>
              )}
              {network.dht && (
                <span className="pe-stat" title={`DHT UDP port ${network.dht.udp_port}`}>
                  {'🌐'} DHT: {network.dht.is_running ? 'active' : 'off'} (port {network.dht.udp_port})
                </span>
              )}
            </div>
          </div>

          {/* File tabs */}
          <div className="pe-tabs">
            {Object.entries(FILE_LABELS).map(([fname, { label, icon }]) => (
              <button
                key={fname}
                className={`pe-tab ${activeFile === fname ? 'active' : ''}`}
                onClick={() => switchFile(fname)}
              >
                {icon} {label}
              </button>
            ))}
          </div>

          {/* Hint */}
          <div className="pe-hint">
            {FILE_LABELS[activeFile]?.hint}
          </div>

          {/* Editor */}
          <textarea
            className="pe-editor"
            value={editContent}
            onChange={e => { setEditContent(e.target.value); setSaveResult(null) }}
            spellCheck={false}
          />

          {/* Actions */}
          <div className="pe-actions">
            <button
              className={`btn-primary ${saving ? 'saving' : ''}`}
              onClick={save}
              disabled={saving}
            >
              {saving ? '⏳ Saving & Rebuilding...' : 'Save & Rebuild'}
            </button>
            <span className="pe-chars">{editContent.length} chars</span>
            {saveResult && (
              <span className={`pe-save-result pe-save-${saveResult.type}`}>
                {saveResult.type === 'rebuilt' ? '✨' : saveResult.type === 'saved' ? '✓' : '✗'}{' '}
                {saveResult.msg}
              </span>
            )}
          </div>
        </div>
      )}

      <style>{`
        .profile-editor {
          background: rgba(30, 30, 50, 0.7);
          border: 1px solid rgba(108, 92, 231, 0.3);
          border-radius: 12px;
          overflow: hidden;
        }
        .pe-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 14px 18px;
          cursor: pointer;
          background: rgba(108, 92, 231, 0.08);
          user-select: none;
        }
        .pe-header h3 {
          margin: 0;
          font-size: 15px;
          color: #e2e2e2;
        }
        .pe-did-badge {
          font-size: 11px;
          color: #00cec9;
          background: rgba(0, 206, 201, 0.1);
          padding: 3px 10px;
          border-radius: 20px;
          font-family: 'JetBrains Mono', monospace;
        }
        .pe-body {
          padding: 16px 18px;
        }
        /* Card summary */
        .pe-card-summary {
          background: rgba(108, 92, 231, 0.06);
          border: 1px solid rgba(108, 92, 231, 0.15);
          border-radius: 10px;
          padding: 14px;
          margin-bottom: 14px;
        }
        .pe-card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
        }
        .pe-card-name {
          font-size: 16px;
          font-weight: 600;
          color: #e2e2f0;
        }
        .pe-rebuild-btn {
          padding: 5px 12px;
          font-size: 11px;
          border: 1px solid rgba(108, 92, 231, 0.3);
          background: rgba(108, 92, 231, 0.1);
          color: #a0a0c0;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.2s;
        }
        .pe-rebuild-btn:hover {
          background: rgba(108, 92, 231, 0.2);
          color: #d0d0f0;
        }
        .pe-rebuild-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .pe-card-desc {
          font-size: 12px;
          color: #999;
          line-height: 1.5;
          margin-bottom: 10px;
        }
        .pe-card-skills {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .pe-skill-tag {
          font-size: 11px;
          background: rgba(0, 206, 201, 0.1);
          color: #00cec9;
          padding: 3px 10px;
          border-radius: 12px;
          border: 1px solid rgba(0, 206, 201, 0.15);
        }
        .pe-card-rebuilt {
          font-size: 10px;
          color: #666;
          margin-top: 8px;
          text-align: right;
        }
        /* Network row */
        .pe-network-row {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-bottom: 14px;
          padding-bottom: 14px;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .pe-identity-card {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .pe-id-label {
          font-size: 10px;
          text-transform: uppercase;
          color: #888;
          letter-spacing: 1px;
        }
        .pe-did-full {
          font-size: 11px;
          color: #aaa;
          word-break: break-all;
          background: rgba(0,0,0,0.3);
          padding: 6px 10px;
          border-radius: 6px;
          display: block;
        }
        .pe-network-stats {
          display: flex;
          gap: 16px;
          flex-wrap: wrap;
        }
        .pe-stat {
          font-size: 12px;
          color: #a0a0b0;
          background: rgba(255,255,255,0.04);
          padding: 4px 10px;
          border-radius: 6px;
        }
        .pe-tabs {
          display: flex;
          gap: 6px;
          margin-bottom: 8px;
        }
        .pe-tab {
          flex: 1;
          padding: 8px 0;
          border: 1px solid rgba(108, 92, 231, 0.2);
          background: transparent;
          color: #999;
          border-radius: 8px;
          cursor: pointer;
          font-size: 13px;
          transition: all 0.2s;
        }
        .pe-tab:hover {
          border-color: rgba(108, 92, 231, 0.5);
          color: #ccc;
        }
        .pe-tab.active {
          background: rgba(108, 92, 231, 0.15);
          border-color: #6c5ce7;
          color: #fff;
        }
        .pe-hint {
          font-size: 11px;
          color: #777;
          margin-bottom: 8px;
          font-style: italic;
        }
        .pe-editor {
          width: 100%;
          min-height: 200px;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid rgba(108, 92, 231, 0.15);
          border-radius: 8px;
          color: #d0d0e0;
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          font-size: 13px;
          line-height: 1.6;
          padding: 12px;
          resize: vertical;
          outline: none;
          transition: border-color 0.2s;
        }
        .pe-editor:focus {
          border-color: #6c5ce7;
        }
        .pe-actions {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-top: 10px;
        }
        .pe-actions .btn-primary {
          padding: 8px 24px;
          border-radius: 8px;
          border: none;
          background: #6c5ce7;
          color: #fff;
          cursor: pointer;
          font-size: 13px;
          transition: all 0.2s;
        }
        .pe-actions .btn-primary:hover {
          background: #7d6ff0;
        }
        .pe-actions .btn-primary:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .pe-chars {
          font-size: 11px;
          color: #666;
        }
        .pe-save-result {
          font-size: 12px;
          padding: 3px 10px;
          border-radius: 6px;
          animation: fadeIn 0.3s ease-in;
        }
        .pe-save-saved {
          color: #00b894;
          background: rgba(0, 184, 148, 0.1);
        }
        .pe-save-rebuilt {
          color: #fdcb6e;
          background: rgba(253, 203, 110, 0.1);
        }
        .pe-save-error {
          color: #e17055;
          background: rgba(225, 112, 85, 0.1);
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}
