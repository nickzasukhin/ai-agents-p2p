/** Onboarding screen — container setup progress + chat interview + card preview + go online. */

import { useState, useRef, useEffect } from 'react'
import { Logo } from '../components/Logo'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { ChatBubble } from '../components/ChatBubble'
import { Card } from '../components/Card'
import { Badge } from '../components/Badge'
import { ContainerSetupScreen, type SetupPhase } from '../components/ContainerSetupScreen'
import { colors, spacing, fontSize } from '../theme/tokens'
import * as agent from '../api/agent'
import { createAgent, getMyAgent } from '../api/orchestrator'

interface OnboardingScreenProps {
  onComplete: () => void
}

interface Message {
  content: string
  isOwn: boolean
}

const OB_KEY = 'onboarding_state'

function saveOnboarding(data: any) {
  try { localStorage.setItem(OB_KEY, JSON.stringify(data)) } catch {}
}
function loadOnboarding(): any | null {
  try { const s = localStorage.getItem(OB_KEY); return s ? JSON.parse(s) : null } catch { return null }
}
function clearOnboarding() {
  try { localStorage.removeItem(OB_KEY) } catch {}
}

export function OnboardingScreen({ onComplete }: OnboardingScreenProps) {
  const saved = loadOnboarding()
  const [step, setStep] = useState<'chat' | 'review' | 'go-online' | 'done'>(saved?.step || 'chat')
  const [sessionId, setSessionId] = useState(saved?.sessionId || '')
  const [messages, setMessages] = useState<Message[]>(saved?.messages || [])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState(saved?.progress || 0)
  const [cardPreview, setCardPreview] = useState<any>(saved?.cardPreview || null)
  const [goOnlineResult, setGoOnlineResult] = useState<any>(null)
  const [setupPhase, setSetupPhase] = useState<SetupPhase | null>(null)
  const [setupError, setSetupError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Persist onboarding state to localStorage on changes
  useEffect(() => {
    if (sessionId) {
      saveOnboarding({ step, sessionId, messages, progress, cardPreview })
    }
  }, [step, sessionId, messages, progress, cardPreview])

  // Start the interview on mount (only if no saved session)
  useEffect(() => {
    if (!saved?.sessionId) startInterview()
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  async function ensureAgent() {
    setSetupError(null)

    // If we already have a token, just wait for the agent to be reachable
    if (localStorage.getItem('agent_token')) {
      setSetupPhase('health_check')
      const ready = await agent.waitForReady(15000, (_attempt, elapsed) => {
        if (elapsed > 10000) setSetupPhase('health_check')
      })
      if (ready) {
        // Verify token actually works (container may have been recreated with new token)
        try {
          await agent.getOnboardingStatus()
          setSetupPhase('ready')
          await new Promise((r) => setTimeout(r, 800))
          setSetupPhase(null)
          return
        } catch {
          // Token invalid — fall through to get fresh token from orchestrator
        }
      }
      // Token exists but agent unreachable or token invalid — fall through to check/create
    }

    // Check if agent already exists on orchestrator side (e.g. token lost from localStorage)
    try {
      setSetupPhase('health_check')
      const info = await getMyAgent()
      if (info.has_agent && info.api_token) {
        localStorage.setItem('agent_token', info.api_token)
        if (info.agent_url) localStorage.setItem('agent_url', info.agent_url)

        if (info.status === 'running') {
          setSetupPhase('health_check')
        } else {
          setSetupPhase('starting')
        }

        const ready = await agent.waitForReady(30000, (_attempt, elapsed) => {
          if (elapsed > 5000) setSetupPhase('health_check')
        })
        if (ready) {
          setSetupPhase('ready')
          await new Promise((r) => setTimeout(r, 800))
          setSetupPhase(null)
          return
        }
        // If not ready after 30s, fall through to timeout
        setSetupPhase('timeout')
        setSetupError('Agent container did not start in time.')
        throw new Error('Agent container did not start in time. Please try again.')
      }
    } catch (err: any) {
      if (setupPhase === 'timeout') throw err
      // Orchestrator unreachable — try creating anyway
    }

    // Create a new agent container
    setSetupPhase('creating')
    const result = await createAgent('My Agent')

    // Wait for the container to become healthy
    setSetupPhase('starting')
    const ready = await agent.waitForReady(45000, (_attempt, elapsed) => {
      if (elapsed > 8000) setSetupPhase('health_check')
    })

    if (!ready) {
      setSetupPhase('timeout')
      setSetupError('Agent container did not start in time.')
      throw new Error('Agent container did not start in time. Please try again.')
    }

    setSetupPhase('ready')
    await new Promise((r) => setTimeout(r, 800))
    setSetupPhase(null)
  }

  async function startInterview() {
    try {
      await ensureAgent()
    } catch (err: any) {
      // If it's a timeout/error, the ContainerSetupScreen handles retry
      if (setupPhase === 'timeout' || setupPhase === 'error') return
      setSetupPhase('error')
      setSetupError(err.message)
      return
    }

    // Retry startOnboarding a few times — container may still be initializing
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const result = await agent.startOnboarding()
        setSessionId(result.session_id)
        setProgress(result.progress)
        setMessages([{ content: result.response, isOwn: false }])
        return
      } catch (err: any) {
        if (attempt < 2) {
          await new Promise((r) => setTimeout(r, 2000))
        } else {
          setMessages([{
            content: "Welcome! Tell me about yourself \u2014 your name and skills. For example: \"Alice, Python and FastAPI developer\"",
            isOwn: false,
          }])
        }
      }
    }
  }

  function handleRetry() {
    setSetupPhase(null)
    setSetupError(null)
    startInterview()
  }

  async function handleSend() {
    if (!input.trim() || loading) return

    const text = input.trim()
    setInput('')
    setMessages((prev) => [...prev, { content: text, isOwn: true }])
    setLoading(true)

    try {
      const result = await agent.chatOnboarding(sessionId, text)
      setProgress(result.progress)
      setMessages((prev) => [...prev, { content: result.response, isOwn: false }])

      if (result.state === 'review' && result.card_preview) {
        setCardPreview(result.card_preview)
        setStep('review')
      } else if (result.state === 'confirmed' || result.progress >= 0.9) {
        // Auto-advance: profile is ready
        if (result.card_preview) {
          setCardPreview(result.card_preview)
          setStep('review')
        } else {
          try { await agent.confirmOnboarding(sessionId) } catch {}
          setStep('go-online')
        }
      }
    } catch (err: any) {
      setMessages((prev) => [...prev, { content: `Error: ${err.message}`, isOwn: false }])
    } finally {
      setLoading(false)
    }
  }

  async function handleNext() {
    setLoading(true)
    try {
      if (cardPreview) {
        setStep('review')
      } else {
        try { await agent.confirmOnboarding(sessionId) } catch {}
        setStep('go-online')
      }
    } catch {
      setStep('go-online')
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirm() {
    setLoading(true)
    try {
      await agent.confirmOnboarding(sessionId)
      setStep('go-online')
    } catch (err: any) {
      setMessages((prev) => [...prev, { content: `Error confirming: ${err.message}`, isOwn: false }])
    } finally {
      setLoading(false)
    }
  }

  async function handleGoOnline() {
    setLoading(true)
    try {
      const result = await agent.goOnline()
      setGoOnlineResult(result)
      setStep('done')
    } catch {
      // Even if go-online fails, we can proceed
      setStep('done')
    } finally {
      setLoading(false)
    }
  }

  const showNext = progress >= 0.9 && !input.trim() && !loading

  // ── Container Setup Screen (full-screen during container creation) ──
  if (setupPhase && setupPhase !== 'ready') {
    return (
      <ContainerSetupScreen
        phase={setupPhase}
        error={setupError}
        onRetry={handleRetry}
      />
    )
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: colors.bgPrimary, maxWidth: 600, margin: '0 auto',
    }}>
      {/* Header */}
      <div style={{
        padding: `${spacing.md}px ${spacing.lg}px`,
        borderBottom: `1px solid ${colors.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <Logo size={28} />
        <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
          <div style={{
            width: 80, height: 4, borderRadius: 2, background: colors.bgCard, overflow: 'hidden',
          }}>
            <div style={{
              width: `${progress * 100}%`, height: '100%',
              background: colors.accent, borderRadius: 2,
              transition: 'width 0.3s ease',
            }} />
          </div>
          <span style={{ color: colors.textMuted, fontSize: fontSize.xs }}>{Math.round(progress * 100)}%</span>
        </div>
      </div>

      {/* Chat */}
      {step === 'chat' && (
        <>
          <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', padding: spacing.lg }}>
            {messages.map((m, i) => (
              <ChatBubble key={i} content={m.content} isOwn={m.isOwn} />
            ))}
            {loading && (
              <div style={{ color: colors.textMuted, fontSize: fontSize.sm, padding: spacing.sm, animation: 'pulse 1.5s infinite' }}>
                Thinking...
              </div>
            )}
          </div>

          <div style={{
            padding: spacing.md, borderTop: `1px solid ${colors.border}`,
            display: 'flex', gap: spacing.sm,
          }}>
            <Input
              value={input}
              onChange={setInput}
              placeholder="Type your answer..."
              onKeyDown={(e) => e.key === 'Enter' && (showNext ? handleNext() : handleSend())}
              autoFocus
            />
            <Button
              onClick={showNext ? handleNext : handleSend}
              disabled={!showNext && (!input.trim() || loading)}
              small
            >
              {loading ? '...' : showNext ? 'Next' : 'Send'}
            </Button>
          </div>
        </>
      )}

      {step === 'review' && cardPreview && (
        <div style={{ flex: 1, overflow: 'auto', padding: spacing.lg }}>
          <div style={{ animation: 'slideUp 0.3s ease' }}>
            <h2 style={{ fontSize: fontSize.xl, marginBottom: spacing.lg }}>Your Agent Card</h2>

            <Card style={{ marginBottom: spacing.lg }}>
              <h3 style={{ fontSize: fontSize.lg, marginBottom: spacing.sm }}>{cardPreview.agent_name}</h3>

              <div style={{ marginBottom: spacing.md }}>
                <div style={{ color: colors.textMuted, fontSize: fontSize.xs, marginBottom: spacing.xs, textTransform: 'uppercase', letterSpacing: 1 }}>Skills</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.xs }}>
                  {(cardPreview.skills || []).map((s: any, i: number) => (
                    <Badge key={i} variant="accent">{typeof s === 'string' ? s : s.name || String(s)}</Badge>
                  ))}
                </div>
              </div>

              <div>
                <div style={{ color: colors.textMuted, fontSize: fontSize.xs, marginBottom: spacing.xs, textTransform: 'uppercase', letterSpacing: 1 }}>Looking For</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.xs }}>
                  {(cardPreview.needs || []).map((n: any, i: number) => (
                    <Badge key={i} variant="success">{typeof n === 'string' ? n : n.name || n.description || String(n)}</Badge>
                  ))}
                </div>
              </div>
            </Card>

            <div style={{ display: 'flex', gap: spacing.sm }}>
              <Button fullWidth onClick={handleConfirm} loading={loading}>
                Looks good!
              </Button>
              <Button fullWidth variant="secondary" onClick={() => setStep('chat')}>
                Edit
              </Button>
            </div>
          </div>
        </div>
      )}

      {step === 'go-online' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: spacing.xl }}>
          <div style={{ textAlign: 'center', animation: 'slideUp 0.3s ease' }}>
            <div style={{ fontSize: 64, marginBottom: spacing.lg }}>🌐</div>
            <h2 style={{ fontSize: fontSize.xxl, marginBottom: spacing.sm }}>Go Online</h2>
            <p style={{ color: colors.textSecondary, fontSize: fontSize.md, marginBottom: spacing.xl, maxWidth: 320 }}>
              Connect your agent to the P2P network and start discovering other agents.
            </p>
            <Button onClick={handleGoOnline} loading={loading} style={{ fontSize: fontSize.lg, padding: '16px 48px' }}>
              Go Online
            </Button>
            <div style={{ marginTop: spacing.lg }}>
              <Button variant="ghost" onClick={() => setStep('done')}>
                Skip for now
              </Button>
            </div>
          </div>
        </div>
      )}

      {step === 'done' && (() => {
        const agentUrl = goOnlineResult?.public_url || localStorage.getItem('agent_url') || ''
        return (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: spacing.xl }}>
            <div style={{ textAlign: 'center', animation: 'slideUp 0.3s ease' }}>
              <div style={{ fontSize: 64, marginBottom: spacing.lg }}>🎉</div>
              <h2 style={{ fontSize: fontSize.xxl, marginBottom: spacing.sm }}>You're all set!</h2>
              <p style={{ color: colors.textSecondary, fontSize: fontSize.md, marginBottom: spacing.md }}>
                Your agent is ready.
                {goOnlineResult?.status === 'online' && ' Connected to the network.'}
              </p>
              {agentUrl && (
                <p style={{ color: colors.textMuted, fontSize: fontSize.sm, marginBottom: spacing.xl }}>
                  Your agent: <span style={{ color: colors.accent, fontFamily: 'monospace', wordBreak: 'break-all' }}>{agentUrl}</span>
                </p>
              )}
              <Button onClick={() => { clearOnboarding(); onComplete() }} style={{ fontSize: fontSize.lg, padding: '16px 48px' }}>
                Enter Dashboard
              </Button>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
