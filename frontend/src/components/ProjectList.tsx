import { useEffect, useState } from 'react'
import {
  fetchProjects,
  suggestProject,
  createProject,
  recruitProject,
  syncProject,
  completeProject,
  type Project,
} from '../api'
import { ConfirmDialog, Skeleton } from './ErrorBoundary'

type Props = {
  refreshTrigger?: number
}

const stateColors: Record<string, string> = {
  draft: 'badge-draft',
  recruiting: 'badge-negotiating',
  partial: 'badge-pending',
  active: 'badge-confirmed',
  completed: 'badge-confirmed',
  stalled: 'badge-rejected',
}

const stateLabels: Record<string, string> = {
  draft: 'Draft',
  recruiting: 'Recruiting',
  partial: 'Partial',
  active: 'Active',
  completed: 'Completed',
  stalled: 'Stalled',
}

const roleStatusIcons: Record<string, string> = {
  open: '\u{1F7E1}',       // yellow circle
  negotiating: '\u{1F535}', // blue circle
  confirmed: '\u2705',      // green check
  rejected: '\u274C',       // red X
}

export default function ProjectList({ refreshTrigger }: Props) {
  const [projects, setProjects] = useState<Project[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [confirmComplete, setConfirmComplete] = useState<{ id: string; name: string } | null>(null)

  const refresh = () => {
    fetchProjects()
      .then(d => setProjects(d.projects || []))
      .catch(() => {})
      .finally(() => setInitialLoading(false))
  }

  useEffect(() => { refresh() }, [refreshTrigger])

  const handleSuggest = async () => {
    setSuggesting(true)
    try {
      const suggestion = await suggestProject()
      if (suggestion.error) {
        alert(suggestion.error)
        return
      }
      const roles = (suggestion.roles || []).map((r: any) => ({
        role_name: r.role_name,
        description: r.description,
        agent_url: r.suggested_agent_url || '',
      }))
      await createProject(suggestion.name || 'New Project', suggestion.description || '', roles)
      refresh()
    } catch {}
    setSuggesting(false)
  }

  const handleRecruit = async (id: string) => {
    setLoading(id)
    try { await recruitProject(id); refresh() } catch {}
    setLoading(null)
  }

  const handleSync = async (id: string) => {
    setLoading(id)
    try { await syncProject(id); refresh() } catch {}
    setLoading(null)
  }

  const handleComplete = async (id: string) => {
    setLoading(id)
    try { await completeProject(id); refresh() } catch {}
    setLoading(null)
    setConfirmComplete(null)
  }

  const filtered = projects.filter(p =>
    !search || p.name.toLowerCase().includes(search.toLowerCase())
      || p.description?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="proj-panel animate-in">
      <div className="panel-header">
        <h3>Projects</h3>
        <div className="proj-header-actions">
          <button className="btn-outline" onClick={refresh}>Refresh</button>
          <button className="btn-primary" onClick={handleSuggest} disabled={suggesting}>
            {suggesting ? 'Suggesting...' : 'Suggest Project'}
          </button>
        </div>
      </div>

      {projects.length > 2 && (
        <div className="search-wrapper">
          <input
            type="text"
            className="search-input"
            placeholder="Search projects..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      )}

      {initialLoading ? (
        <Skeleton cards={2} />
      ) : filtered.length === 0 ? (
        <p className="proj-empty">
          {search ? 'No projects match your search.' : 'No projects yet. Discover matches and suggest a collaboration project.'}
        </p>
      ) : (
        <div className="proj-list">
          {filtered.map(proj => (
            <div key={proj.id} className={`proj-card stagger-item ${proj.is_terminal ? 'terminal' : ''}`}>
              <div className="proj-header-row" onClick={() => setExpanded(expanded === proj.id ? null : proj.id)}>
                <div className="proj-info">
                  <span className="proj-name">{proj.name}</span>
                  <span className={`badge ${stateColors[proj.state] || ''}`}>
                    {stateLabels[proj.state] || proj.state}
                  </span>
                </div>
                <div className="proj-meta">
                  <span className="proj-progress">{proj.filled_roles}/{proj.total_roles} roles</span>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${proj.progress * 100}%` }} />
                  </div>
                </div>
              </div>

              {proj.description && (
                <p className="proj-description">{proj.description}</p>
              )}

              {/* Actions */}
              <div className="proj-actions">
                {(proj.state === 'draft' || proj.state === 'stalled') && (
                  <button className="btn-primary" onClick={() => handleRecruit(proj.id)}
                    disabled={loading === proj.id}>
                    {loading === proj.id ? 'Recruiting...' : 'Recruit'}
                  </button>
                )}
                {(proj.state === 'recruiting' || proj.state === 'partial') && (
                  <button className="btn-outline" onClick={() => handleSync(proj.id)}
                    disabled={loading === proj.id}>
                    {loading === proj.id ? 'Syncing...' : 'Sync Status'}
                  </button>
                )}
                {proj.state === 'active' && (
                  <button className="btn-success"
                    onClick={() => setConfirmComplete({ id: proj.id, name: proj.name })}
                    disabled={loading === proj.id}>
                    {loading === proj.id ? 'Completing...' : 'Mark Complete'}
                  </button>
                )}
              </div>

              {/* Expanded role details */}
              {expanded === proj.id && (
                <div className="proj-roles">
                  <h4>Roles</h4>
                  {proj.roles.map((role, i) => (
                    <div key={i} className={`role-card role-${role.status}`}>
                      <div className="role-header">
                        <span className="role-icon">{roleStatusIcons[role.status] || ''}</span>
                        <span className="role-name">{role.role_name}</span>
                        <span className="role-status">{role.status}</span>
                      </div>
                      <p className="role-desc">{role.description}</p>
                      {role.agent_name && (
                        <span className="role-agent">{role.agent_name}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Confirm Complete Dialog */}
      {confirmComplete && (
        <ConfirmDialog
          title="Complete Project?"
          message={`Mark "${confirmComplete.name}" as completed? This cannot be undone.`}
          confirmLabel="Complete"
          confirmVariant="success"
          onConfirm={() => handleComplete(confirmComplete.id)}
          onCancel={() => setConfirmComplete(null)}
        />
      )}

      <style>{`
        .proj-panel {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 20px;
        }
        .proj-header-actions { display: flex; gap: 8px; }
        .proj-empty {
          color: var(--text-muted);
          font-size: 14px;
          text-align: center;
          padding: 20px 0;
        }
        .proj-list { display: flex; flex-direction: column; gap: 12px; }
        .proj-card {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: var(--radius-sm);
          padding: 16px;
          transition: border-color 0.2s;
        }
        .proj-card:hover { border-color: var(--accent); }
        .proj-card.terminal { opacity: 0.7; }
        .proj-card.terminal:hover { border-color: var(--border); }
        .proj-header-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          cursor: pointer;
          margin-bottom: 8px;
        }
        .proj-info { display: flex; align-items: center; gap: 10px; }
        .proj-name { font-weight: 600; font-size: 15px; }
        .proj-meta { display: flex; align-items: center; gap: 10px; }
        .proj-progress { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
        .progress-bar {
          width: 60px;
          height: 6px;
          background: var(--bg-card);
          border-radius: 3px;
          overflow: hidden;
        }
        .progress-fill {
          height: 100%;
          background: var(--success);
          transition: width 0.3s ease;
          border-radius: 3px;
        }
        .proj-description {
          font-size: 13px;
          color: var(--text-secondary);
          margin-bottom: 12px;
          line-height: 1.5;
        }
        .proj-actions { display: flex; gap: 8px; margin-top: 8px; }
        .proj-roles {
          margin-top: 16px;
          border-top: 1px solid var(--border);
          padding-top: 12px;
        }
        .proj-roles h4 {
          font-size: 13px;
          color: var(--text-muted);
          margin-bottom: 10px;
        }
        .role-card {
          padding: 10px 14px;
          border-radius: var(--radius-sm);
          margin-bottom: 8px;
          border-left: 3px solid var(--border);
        }
        .role-confirmed { border-left-color: var(--success); background: rgba(0,206,201,0.05); }
        .role-negotiating { border-left-color: var(--accent); background: rgba(108,92,231,0.05); }
        .role-rejected { border-left-color: var(--danger); background: rgba(231,76,60,0.05); }
        .role-open { border-left-color: var(--warning); background: rgba(243,156,18,0.05); }
        .role-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 4px;
        }
        .role-icon { font-size: 14px; }
        .role-name { font-weight: 600; font-size: 14px; }
        .role-status { font-size: 11px; color: var(--text-muted); text-transform: uppercase; }
        .role-desc { font-size: 12px; color: var(--text-secondary); margin: 4px 0; }
        .role-agent {
          font-size: 12px;
          color: var(--accent-light);
          font-weight: 500;
        }
        .badge-draft { background: rgba(243,156,18,0.15); color: #f39c12; }
        .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .panel-header h3 { font-size: 16px; }
        .empty-state {
          text-align: center;
          padding: 32px;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  )
}
