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
          <TokenDialog />
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
          <div className="col-main">
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
          </div>

          <div className="col-side">
            <EventFeed wsEvents={wsEvents} wsConnected={wsConnected} />
          </div>
        </main>
      </ErrorBoundary>

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
          gap: 12px;
        }
        .logo {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 12px;
        }
        .logo-icon { font-size: 32px; }
        .logo h1 {
          font-size: 28px;
          background: linear-gradient(135deg, var(--accent-light), var(--success));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }
        .subtitle {
          color: var(--text-muted);
          font-size: 14px;
          margin-top: 4px;
        }
        .dashboard {
          display: grid;
          grid-template-columns: 1fr 340px;
          gap: 20px;
          align-items: start;
        }
        .col-main {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        .col-side {
          position: sticky;
          top: 24px;
        }
        @media (max-width: 900px) {
          .dashboard {
            grid-template-columns: 1fr;
          }
          .col-side {
            position: static;
          }
        }
      `}</style>
    </div>
  )
}
