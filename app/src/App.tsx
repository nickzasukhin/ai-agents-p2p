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
import { isAuthenticated, getMe } from './api/orchestrator'
import { getOnboardingStatus } from './api/agent'

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

  useEffect(() => {
    checkAuth()
  }, [])

  async function checkAuth() {
    if (!isAuthenticated()) {
      setAppState('auth')
      return
    }

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

  // ── Loading ────────────────────────────────────────────

  if (appState === 'loading') {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        height: '100vh', background: colors.bgPrimary, animation: 'pulse 1.5s infinite',
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
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: colors.bgPrimary }}>
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
                onClick={() => setActiveTab(tab)}
                style={{
                  padding: `${spacing.xs}px ${spacing.md}px`,
                  borderRadius: radius.md,
                  fontSize: fontSize.sm,
                  fontWeight: 500,
                  color: activeTab === tab ? colors.accent : colors.textSecondary,
                  background: activeTab === tab ? colors.accentMuted : 'transparent',
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
        {activeTab === 'home' && <HomeScreen />}
        {activeTab === 'search' && <SearchScreen />}
        {activeTab === 'chat' && <ChatScreen />}
        {activeTab === 'profile' && <ProfileScreen onLogout={handleLogout} />}
      </main>

      {/* Mobile bottom tab bar */}
      <nav style={{
        display: 'none',  // Will be shown via media query
        borderTop: `1px solid ${colors.border}`,
        background: colors.bgSecondary,
        padding: `${spacing.xs}px 0`,
        flexShrink: 0,
      }}
        className="mobile-tabs"
      >
        {(['home', 'search', 'chat', 'profile'] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              flex: 1,
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              padding: `${spacing.xs}px 0`,
              color: activeTab === tab ? colors.accent : colors.textMuted,
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
