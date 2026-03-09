import { useState, useEffect } from 'react'
import { getApiToken, setApiToken, hasApiToken } from '../api'

export default function TokenDialog() {
  const [open, setOpen] = useState(false)
  const [token, setToken] = useState('')
  const [saved, setSaved] = useState(hasApiToken())

  useEffect(() => {
    if (open) setToken(getApiToken())
  }, [open])

  const handleSave = () => {
    setApiToken(token.trim())
    setSaved(!!token.trim())
    setOpen(false)
  }

  const handleClear = () => {
    setApiToken('')
    setToken('')
    setSaved(false)
    setOpen(false)
  }

  return (
    <>
      <button
        className="token-btn"
        onClick={() => setOpen(true)}
        title={saved ? 'API token set' : 'Set API token'}
      >
        {saved ? '\u{1F512}' : '\u{1F513}'}
      </button>

      {open && (
        <div className="token-overlay" onClick={() => setOpen(false)}>
          <div className="token-dialog" onClick={e => e.stopPropagation()}>
            <h3>API Token</h3>
            <p className="token-hint">
              Bearer token for owner endpoints. Set API_TOKEN env var on the server,
              then paste the same value here.
            </p>
            <input
              type="password"
              value={token}
              onChange={e => setToken(e.target.value)}
              placeholder="Enter API token..."
              className="token-input"
              autoFocus
              onKeyDown={e => e.key === 'Enter' && handleSave()}
            />
            <div className="token-actions">
              <button className="btn-secondary" onClick={handleClear}>Clear</button>
              <button className="btn-primary" onClick={handleSave}>Save</button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        .token-btn {
          background: none;
          border: 1px solid var(--border);
          border-radius: 8px;
          font-size: 18px;
          cursor: pointer;
          padding: 4px 8px;
          transition: background 0.2s;
        }
        .token-btn:hover {
          background: var(--surface-hover);
        }
        .token-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0,0,0,0.6);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }
        .token-dialog {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 24px;
          width: 400px;
          max-width: 90vw;
        }
        .token-dialog h3 {
          margin: 0 0 8px;
          color: var(--text);
        }
        .token-hint {
          color: var(--text-muted);
          font-size: 13px;
          margin: 0 0 16px;
          line-height: 1.4;
        }
        .token-input {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid var(--border);
          border-radius: 8px;
          background: var(--bg);
          color: var(--text);
          font-family: monospace;
          font-size: 14px;
          box-sizing: border-box;
        }
        .token-input:focus {
          outline: none;
          border-color: var(--accent);
        }
        .token-actions {
          display: flex;
          gap: 8px;
          justify-content: flex-end;
          margin-top: 16px;
        }
        .btn-primary, .btn-secondary {
          padding: 8px 16px;
          border-radius: 8px;
          border: none;
          cursor: pointer;
          font-size: 14px;
        }
        .btn-primary {
          background: var(--accent);
          color: white;
        }
        .btn-secondary {
          background: var(--surface-hover);
          color: var(--text-muted);
        }
      `}</style>
    </>
  )
}
