/** DevPunks Agents — Main App with auth gate + tab navigation. */

import { useState, useEffect } from 'react'
import { Logo } from './components/Logo'
import { colors, spacing, fontSize, radius } from './theme/tokens'
import { AuthScreen } from './screens/AuthScreen'
import { OnboardingScreen } from './screens/OnboardingScreen'
import { HomeScreen } from './screens/HomeScreen'
import { SearchScreen } from './screens/SearchScreen'
import { ChatScreen } from './screens/ChatScreen'
import { ProfileScreen } from './screens/ProfileScreen'
import { AgentDetailScreen } from './screens/AgentDetailScreen'
import { isAuthenticated, getMe, setSession } from './api/orchestrator'
import { getOnboardingStatus } from './api/agent'
import { startNegotiation } from './api/agent'

/** Detect if we're on the main domain or a user subdomain. */
const MAIN_DOMAIN = 'agents.devpunks.io'
function isMainDomain(): boolean {
  const host = window.location.hostname
  return host === MAIN_DOMAIN || host === 'localhost' || host === '127.0.0.1'
}

function isSubdomain(): boolean {
  const host = window.location.hostname
  return host.endsWith(`.${MAIN_DOMAIN}`) && host !== MAIN_DOMAIN
}

/** Read URL params and store tokens in localStorage (used after redirect from main domain). */
function consumeUrlTokens() {
  const params = new URLSearchParams(window.location.search)
  const session = params.get('session')
  const agentToken = params.get('agent_token')
  const agentUrl = params.get('agent_url')

  if (session) {
    setSession(session)
    if (agentToken) localStorage.setItem('agent_token', agentToken)
    if (agentUrl) localStorage.setItem('agent_url', agentUrl)

    // Clean URL
    const url = new URL(window.location.href)
    url.searchParams.delete('session')
    url.searchParams.delete('agent_token')
    url.searchParams.delete('agent_url')
    window.history.replaceState({}, '', url.pathname + url.hash)
    return true
  }
  return false
}

type AppState = 'loading' | 'auth' | 'onboarding' | 'main'
type Tab = 'home' | 'search' | 'chat' | 'profile'

const TAB_ICONS: Record<Tab, string> = {
  home: '🏠',
  search: '🔍',
  chat: '💬',
  profile: '👤',
}

const TAB_LABELS: Record<Tab, string> = {
  home: 'Home',
  search: 'Search',
  chat: 'Chat',
  profile: 'Profile',
}

export default function App() {
  const [appState, setAppState] = useState<AppState>('loading')
  const [activeTab, setActiveTab] = useState<Tab>('home')
  const [detailAgentUrl, setDetailAgentUrl] = useState<string | null>(null)
  const [pendingNegResult, setPendingNegResult] = useState<{ peer: string; state: string } | null>(null)

  useEffect(() => {
    // On subdomain, consume URL tokens from redirect first
    if (isSubdomain()) {
      consumeUrlTokens()
    }
    checkAuth()
  }, [])

  async function checkAuth() {
    if (!isAuthenticated()) {
      // On main domain, show auth. On subdomain without auth, also show auth.
      setAppState('auth')
      return
    }

    // On main domain: if already authenticated, redirect to subdomain
    if (isMainDomain()) {
      try {
        const user = await getMe()
        if (user.subdomain) {
          const token = localStorage.getItem('session_token') || ''
          const agentToken = localStorage.getItem('agent_token') || ''
          const agentUrl = localStorage.getItem('agent_url') || ''
          const params = new URLSearchParams()
          if (token) params.set('session', token)
          if (agentToken) params.set('agent_token', agentToken)
          if (agentUrl) params.set('agent_url', agentUrl)
          window.location.href = `https://${user.subdomain}.${MAIN_DOMAIN}/app?${params.toString()}`
          return
        }
      } catch {
        // If can't reach API, show auth
      }
      setAppState('auth')
      return
    }

    // On subdomain: normal flow
    try {
      const user = await getMe()
      if (!user.has_agent) {
        setAppState('onboarding')
        return
      }

      // Check if onboarding is complete
      try {
        const status = await getOnboardingStatus()
        if (!status.onboarding_complete) {
          setAppState('onboarding')
          return
        }
      } catch {
        // If we can't reach the agent, still go to main
      }

      setAppState('main')
    } catch {
      setAppState('auth')
    }
  }

  function handleAuth() {
    checkAuth()
  }

  function handleOnboardingComplete() {
    setAppState('main')
  }

  function handleLogout() {
    setAppState('auth')
  }

  function handleViewAgent(agentUrl: string) {
    setDetailAgentUrl(agentUrl)
    window.history.pushState({ detail: true }, '')
  }

  function handleBackFromDetail() {
    setDetailAgentUrl(null)
  }

  // Hardware back button support
  useEffect(() => {
    function onPop() {
      if (detailAgentUrl) {
        setDetailAgentUrl(null)
      }
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [detailAgentUrl])

  function handleTabClick(tab: Tab) {
    setDetailAgentUrl(null)
    setActiveTab(tab)
  }

  async function handleNegotiateFromDetail(peerUrl: string) {
    console.log('[negotiate-detail] starting with peer:', peerUrl)
    try {
      const result = await startNegotiation(peerUrl)
      console.log('[negotiate-detail] result:', result)
      const state = (result as any).state || 'unknown'
      const peer = (result as any).peer || peerUrl
      if (state === 'confirmed') {
        setPendingNegResult({ peer, state })
        setDetailAgentUrl(null)
        setActiveTab('chat')
        return
      }
      setPendingNegResult({ peer, state })
    } catch (err) {
      console.error('[negotiate-detail] error:', err)
      setPendingNegResult({ peer: peerUrl, state: 'error' })
    }
    setDetailAgentUrl(null)
    setActiveTab('home')
  }

  function handleChatFromDetail(_peerUrl: string) {
    setDetailAgentUrl(null)
    setActiveTab('chat')
  }

  // ── Loading ────────────────────────────────────────────

  if (appState === 'loading') {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        height: '100%', background: colors.bgPrimary, animation: 'pulse 1.5s infinite',
      }}>
        <Logo size={48} />
      </div>
    )
  }

  // ── Auth ───────────────────────────────────────────────

  if (appState === 'auth') {
    return <AuthScreen onAuth={handleAuth} />
  }

  // ── Onboarding ─────────────────────────────────────────

  if (appState === 'onboarding') {
    return <OnboardingScreen onComplete={handleOnboardingComplete} />
  }

  // ── Main App (tabs) ────────────────────────────────────

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: colors.bgPrimary }}>
      {/* Header */}
      <header style={{
        padding: `${spacing.sm}px ${spacing.lg}px`,
        borderBottom: `1px solid ${colors.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: colors.bgSecondary,
        flexShrink: 0,
      }}>
        <Logo size={28} />
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
          {/* Desktop nav */}
          <nav style={{ display: 'flex', gap: spacing.xs }}>
            {(['home', 'search', 'chat', 'profile'] as Tab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => handleTabClick(tab)}
                style={{
                  padding: `${spacing.xs}px ${spacing.md}px`,
                  borderRadius: radius.md,
                  fontSize: fontSize.sm,
                  fontWeight: 500,
                  color: activeTab === tab && !detailAgentUrl ? colors.accent : colors.textSecondary,
                  background: activeTab === tab && !detailAgentUrl ? colors.accentMuted : 'transparent',
                  transition: 'all 0.15s',
                }}
              >
                {TAB_LABELS[tab]}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Content */}
      <main style={{ flex: 1, overflow: 'hidden' }}>
        {detailAgentUrl ? (
          <AgentDetailScreen
            agentUrl={detailAgentUrl}
            onBack={handleBackFromDetail}
            onNegotiate={handleNegotiateFromDetail}
            onChat={handleChatFromDetail}
          />
        ) : (
          <>
            {activeTab === 'home' && <HomeScreen onViewAgent={handleViewAgent} onSwitchToChat={() => setActiveTab('chat')} onSwitchToSearch={() => setActiveTab('search')} initialNegResult={pendingNegResult} onNegResultConsumed={() => setPendingNegResult(null)} />}
            {activeTab === 'search' && <SearchScreen onViewAgent={handleViewAgent} />}
            {activeTab === 'chat' && <ChatScreen />}
            {activeTab === 'profile' && <ProfileScreen onLogout={handleLogout} />}
          </>
        )}
      </main>

      {/* Mobile bottom tab bar */}
      <nav style={{
        display: 'none',  // Will be shown via media query
        borderTop: `1px solid ${colors.border}`,
        background: colors.bgSecondary,
        padding: `${spacing.xs}px 0`,
        flexShrink: 0,
      }}
        className={detailAgentUrl ? '' : 'mobile-tabs'}
      >
        {(['home', 'search', 'chat', 'profile'] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => handleTabClick(tab)}
            style={{
              flex: 1,
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              padding: `${spacing.xs}px 0`,
              color: activeTab === tab && !detailAgentUrl ? colors.accent : colors.textMuted,
              fontSize: fontSize.xs,
              gap: 2,
              transition: 'color 0.15s',
            }}
          >
            <span style={{ fontSize: 20 }}>{TAB_ICONS[tab]}</span>
            <span>{TAB_LABELS[tab]}</span>
          </button>
        ))}
      </nav>

      {/* Mobile CSS */}
      <style>{`
        @media (max-width: 768px) {
          .mobile-tabs { display: flex !important; }
          header nav { display: none !important; }
        }
      `}</style>
    </div>
  )
}
