import { useState, useEffect, useCallback, useRef } from 'react'
import AgentStatus from './components/AgentStatus'
import MatchList from './components/MatchList'
import NegotiationList from './components/NegotiationList'
import EventFeed from './components/EventFeed'
import ProfileEditor from './components/ProfileEditor'
import ProjectList from './components/ProjectList'
import NetworkPanel from './components/NetworkPanel'
import ChatPanel from './components/ChatPanel'
import TokenDialog from './components/TokenDialog'
import { ErrorBoundary } from './components/ErrorBoundary'
import {
  connectWebSocket,
  fetchPendingApprovals,
  type AgentEvent,
  type Match,
  type Negotiation,
  type ChatChannel,
} from './api'

type Tab = 'dashboard' | 'network' | 'matches' | 'projects' | 'chat' | 'profile'

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '\u{1F3E0}' },
  { id: 'network', label: 'Network', icon: '\u{1F310}' },
  { id: 'matches', label: 'Matches', icon: '\u{1F3AF}' },
  { id: 'projects', label: 'Projects', icon: '\u{1F4CB}' },
  { id: 'chat', label: 'Chat', icon: '\u{1F4AC}' },
  { id: 'profile', label: 'Profile', icon: '\u{1F464}' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard')
  const [refreshTrigger, setRefreshTrigger] = useState(0)
  const [pendingCount, setPendingCount] = useState(0)
  const [wsConnected, setWsConnected] = useState(false)
  const [health, setHealth] = useState<any>(null)
  const [wsMatches, setWsMatches] = useState<Match[] | null>(null)
  const [wsNegotiations, setWsNegotiations] = useState<Negotiation[] | null>(null)
  const [wsEvents, setWsEvents] = useState<AgentEvent[]>([])
  const [wsChats, setWsChats] = useState<ChatChannel[] | null>(null)
  const [chatNegId, setChatNegId] = useState<string | null>(null)
  const [unreadChats, setUnreadChats] = useState(0)
  const [eventDrawerOpen, setEventDrawerOpen] = useState(false)
  const wsRef = useRef<{ close: () => void; send: (msg: any) => void } | null>(null)

  const triggerRefresh = () => setRefreshTrigger(prev => prev + 1)

  const handleEvent = useCallback((event: AgentEvent) => {
    setWsEvents(prev => [...prev, event].slice(-50))
  }, [])

  const handleHealthUpdate = useCallback((data: any) => {
    setHealth(data)
    const pending = data?.negotiations?.pending_approval ?? 0
    setPendingCount(pending)
  }, [])

  const handleMatchesUpdate = useCallback((matches: Match[]) => {
    setWsMatches(matches)
  }, [])

  const handleNegotiationsUpdate = useCallback((negotiations: Negotiation[]) => {
    setWsNegotiations(negotiations)
    const pending = negotiations.filter(n => n.state === 'owner_review').length
    setPendingCount(pending)
  }, [])

  const handleChatUpdate = useCallback((chats: ChatChannel[]) => {
    setWsChats(chats)
    const total = chats.reduce((sum, c) => sum + c.message_count, 0)
    setUnreadChats(total > 0 ? chats.length : 0)
  }, [])

  const openChat = useCallback((negId: string) => {
    setChatNegId(negId)
    setActiveTab('chat')
  }, [])

  // WebSocket connection
  useEffect(() => {
    const conn = connectWebSocket({
      onEvent: handleEvent,
      onHealthUpdate: handleHealthUpdate,
      onMatchesUpdate: handleMatchesUpdate,
      onNegotiationsUpdate: handleNegotiationsUpdate,
      onChatUpdate: handleChatUpdate,
      onConnectionChange: setWsConnected,
    })
    wsRef.current = conn
    return () => conn.close()
  }, [handleEvent, handleHealthUpdate, handleMatchesUpdate, handleNegotiationsUpdate, handleChatUpdate])

  // Fallback polling for pending count (only when WS not connected)
  useEffect(() => {
    if (wsConnected) return
    const loadPending = () => {
      fetchPendingApprovals()
        .then(d => setPendingCount(d.pending?.length || 0))
        .catch(() => {})
    }
    loadPending()
    const iv = setInterval(loadPending, 5000)
    return () => clearInterval(iv)
  }, [wsConnected])

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-row">
          <div className="logo">
            <span className="logo-icon">&#x1F310;</span>
            <h1>Agent Social Network</h1>
          </div>
          <div className="header-actions">
            <a href="/viz/" target="_blank" rel="noopener" className="btn-header">3D</a>
            <button
              className={`btn-header btn-events ${eventDrawerOpen ? 'active' : ''}`}
              onClick={() => setEventDrawerOpen(prev => !prev)}
            >
              Events
              {wsEvents.length > 0 && <span className="events-badge">{wsEvents.length}</span>}
              {wsEvents.length > 0 && <span className="live-dot-header" />}
            </button>
            <TokenDialog />
          </div>
        </div>
        <p className="subtitle">P2P AI Agent Discovery & Collaboration</p>
      </header>

      {/* Tab Navigation */}
      <nav className="tab-nav">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="tab-icon">{tab.icon}</span>
            {tab.label}
            {tab.id === 'matches' && pendingCount > 0 && (
              <span className="tab-badge">{pendingCount}</span>
            )}
            {tab.id === 'chat' && unreadChats > 0 && (
              <span className="tab-badge">{unreadChats}</span>
            )}
          </button>
        ))}
      </nav>

      <ErrorBoundary>
        <main className="dashboard">
          {activeTab === 'dashboard' && (
            <>
              <AgentStatus wsHealth={health} wsConnected={wsConnected} />
              <NegotiationList
                refreshTrigger={refreshTrigger}
                wsNegotiations={wsNegotiations}
                onOpenChat={openChat}
              />
            </>
          )}

          {activeTab === 'network' && (
            <NetworkPanel />
          )}

          {activeTab === 'matches' && (
            <MatchList
              onRefresh={triggerRefresh}
              wsMatches={wsMatches}
              wsNegotiations={wsNegotiations}
            />
          )}

          {activeTab === 'projects' && (
            <ProjectList refreshTrigger={refreshTrigger} />
          )}

          {activeTab === 'chat' && (
            <ChatPanel wsChats={wsChats} initialChatId={chatNegId} />
          )}

          {activeTab === 'profile' && (
            <ProfileEditor />
          )}
        </main>
      </ErrorBoundary>

      {/* Event Drawer */}
      {eventDrawerOpen && <div className="drawer-overlay" onClick={() => setEventDrawerOpen(false)} />}
      <div className={`event-drawer ${eventDrawerOpen ? 'open' : ''}`}>
        <div className="drawer-header">
          <h3>Events</h3>
          <button className="btn-outline btn-close-drawer" onClick={() => setEventDrawerOpen(false)}>Close</button>
        </div>
        <EventFeed wsEvents={wsEvents} wsConnected={wsConnected} />
      </div>

      <style>{`
        .app {
          max-width: 1200px;
          margin: 0 auto;
          padding: 24px;
        }
        .app-header {
          text-align: center;
          margin-bottom: 20px;
        }
        .header-row {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
        }
        .logo {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
        }
        .logo-icon { font-size: 28px; }
        .logo h1 {
          font-size: 28px;
          background: linear-gradient(135deg, var(--accent-light), var(--success));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          white-space: nowrap;
        }
        .header-actions {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .btn-header {
          background: var(--bg-card);
          border: 1px solid var(--border);
          color: var(--text-secondary);
          padding: 5px 12px;
          border-radius: var(--radius-sm);
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
          text-decoration: none;
          display: inline-flex;
          align-items: center;
          gap: 5px;
        }
        .btn-header:hover {
          border-color: var(--accent);
          color: var(--accent-light);
          transform: none;
        }
        .btn-events.active {
          background: var(--accent);
          border-color: var(--accent);
          color: white;
        }
        .events-badge {
          background: rgba(255,255,255,0.2);
          padding: 0 5px;
          border-radius: 8px;
          font-size: 10px;
          min-width: 16px;
          text-align: center;
        }
        .btn-events:not(.active) .events-badge {
          background: var(--accent);
          color: white;
        }
        .live-dot-header {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--success);
          animation: pulse 1.5s infinite;
        }
        .subtitle {
          color: var(--text-muted);
          font-size: 14px;
          margin-top: 4px;
        }
        .dashboard {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        /* Event Drawer */
        .drawer-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0,0,0,0.5);
          z-index: 99;
          animation: fadeIn 0.15s ease-out;
        }
        .event-drawer {
          position: fixed;
          top: 0;
          right: -400px;
          width: 380px;
          height: 100vh;
          background: var(--bg-primary);
          border-left: 1px solid var(--border);
          z-index: 100;
          transition: right 0.3s ease;
          display: flex;
          flex-direction: column;
          padding: 16px;
          overflow: hidden;
        }
        .event-drawer.open { right: 0; }
        .drawer-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
          flex-shrink: 0;
        }
        .drawer-header h3 { font-size: 16px; }
        .btn-close-drawer {
          padding: 4px 12px;
          font-size: 11px;
        }
        .event-drawer .event-panel {
          flex: 1;
          overflow: hidden;
          border: none;
          padding: 0;
          background: transparent;
        }
        .event-drawer .event-panel > .panel-header { display: none; }
        @media (max-width: 480px) {
          .app { padding: 12px; }
          .logo-icon { font-size: 22px; }
          .logo h1 { font-size: 20px; }
          .subtitle { font-size: 12px; }
          .event-drawer { width: 100%; right: -100%; }
          .header-actions { gap: 4px; }
          .btn-header { padding: 4px 8px; font-size: 11px; }
        }
      `}</style>
    </div>
  )
}
