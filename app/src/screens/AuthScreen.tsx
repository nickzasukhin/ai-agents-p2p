/** Auth screen — email input + magic link flow. */

import { useState } from 'react'
import { Logo } from '../components/Logo'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { colors, spacing, fontSize, radius } from '../theme/tokens'
import { requestMagicLink, verifyMagicLink } from '../api/orchestrator'

interface AuthScreenProps {
  onAuth: () => void
}

export function AuthScreen({ onAuth }: AuthScreenProps) {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Check for magic link token in URL
  const params = new URLSearchParams(window.location.search)
  const token = params.get('token')

  // If there's a token, verify it immediately
  if (token && !sent) {
    verifyMagicLink(token)
      .then((result) => {
        // Clear URL params
        window.history.replaceState({}, '', window.location.pathname)

        // If user has a subdomain, redirect to their dashboard
        const MAIN_DOMAIN = 'agents.devpunks.io'
        if (result.subdomain && window.location.hostname === MAIN_DOMAIN) {
          const redirectParams = new URLSearchParams()
          redirectParams.set('session', result.session_token)
          if (result.agent_url) {
            redirectParams.set('agent_url', result.agent_url)
            const agentToken = localStorage.getItem('agent_token')
            if (agentToken) redirectParams.set('agent_token', agentToken)
          }
          window.location.href = `https://${result.subdomain}.${MAIN_DOMAIN}/app?${redirectParams.toString()}`
          return
        }

        onAuth()
      })
      .catch((e) => setError(e.message))
  }

  async function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault()
    if (!email.trim()) return

    setLoading(true)
    setError('')
    try {
      await requestMagicLink(email.trim())
      setSent(true)
    } catch (err: any) {
      setError(err.message || 'Failed to send magic link')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        padding: spacing.lg,
        background: colors.bgPrimary,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 420,
          animation: 'fadeIn 0.4s ease',
        }}
      >
        {/* Logo + tagline */}
        <div style={{ textAlign: 'center', marginBottom: spacing.xxl }}>
          <Logo size={48} />
          <p style={{ color: colors.textSecondary, fontSize: fontSize.md, marginTop: spacing.sm }}>
            AI Agent Network
          </p>
        </div>

        {/* Card */}
        <div
          style={{
            background: colors.bgSecondary,
            border: `1px solid ${colors.border}`,
            borderRadius: radius.xl,
            padding: spacing.xl,
          }}
        >
          {!sent ? (
            <form onSubmit={handleSubmit}>
              <h2 style={{ fontSize: fontSize.xl, fontWeight: 600, marginBottom: spacing.sm }}>
                Sign in
              </h2>
              <p style={{ color: colors.textSecondary, fontSize: fontSize.sm, marginBottom: spacing.lg }}>
                Enter your email to get a magic link. No password needed.
              </p>

              <Input
                value={email}
                onChange={setEmail}
                placeholder="you@example.com"
                type="email"
                autoFocus
                onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              />

              {error && (
                <p style={{ color: colors.error, fontSize: fontSize.sm, marginTop: spacing.sm }}>{error}</p>
              )}

              <Button
                type="submit"
                fullWidth
                loading={loading}
                disabled={!email.trim()}
                style={{ marginTop: spacing.lg }}
              >
                Send Magic Link
              </Button>
            </form>
          ) : (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 48, marginBottom: spacing.md }}>📧</div>
              <h2 style={{ fontSize: fontSize.xl, fontWeight: 600, marginBottom: spacing.sm }}>
                Check your email
              </h2>
              <p style={{ color: colors.textSecondary, fontSize: fontSize.md, marginBottom: spacing.lg }}>
                We sent a sign-in link to <strong style={{ color: colors.textPrimary }}>{email}</strong>
              </p>
              <p style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
                Link expires in 15 minutes.
              </p>
              <Button
                variant="ghost"
                style={{ marginTop: spacing.lg }}
                onClick={() => { setSent(false); setEmail('') }}
              >
                Use different email
              </Button>
            </div>
          )}
        </div>

        {/* Footer */}
        <p style={{ textAlign: 'center', color: colors.textMuted, fontSize: fontSize.xs, marginTop: spacing.xl }}>
          Your personal AI agent in the P2P network
        </p>
      </div>
    </div>
  )
}
