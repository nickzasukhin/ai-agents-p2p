/** Home screen — matches, status, quick actions. */

import { useState, useEffect } from 'react'
import { Card } from '../components/Card'
import { Button } from '../components/Button'
import { Badge } from '../components/Badge'
import { MatchCard } from '../components/MatchCard'
import { colors, spacing, fontSize } from '../theme/tokens'
import * as agentApi from '../api/agent'
import * as orchApi from '../api/orchestrator'

interface HomeScreenProps {
  onViewAgent?: (agentUrl: string) => void
  onSwitchToChat?: () => void
  onSwitchToSearch?: () => void
}

export function HomeScreen({ onViewAgent, onSwitchToChat, onSwitchToSearch }: HomeScreenProps) {
  const [matches, setMatches] = useState<agentApi.Match[]>([])
  const [onlineStatus, setOnlineStatus] = useState<agentApi.OnlineStatus | null>(null)
  const [agentInfo, setAgentInfo] = useState<orchApi.AgentInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [negotiating, setNegotiating] = useState<string | null>(null)
  const [negResult, setNegResult] = useState<{ peer: string; state: string } | null>(null)
  const [discoveryRuns, setDiscoveryRuns] = useState(0)

  useEffect(() => {
    loadData()
  }, [])

  // Auto-refresh while no matches and discovery is still running early cycles
  useEffect(() => {
    if (loading) return
    if (matches.length > 0 || discoveryRuns >= 5) return
    const t = setInterval(loadData, 10000)
    return () => clearInterval(t)
  }, [loading, matches.length, discoveryRuns])

  async function loadData() {
    setLoading(true)
    try {
      const [matchesResp, status, info, health] = await Promise.allSettled([
        agentApi.getMatches(),
        agentApi.getOnlineStatus(),
        orchApi.getMyAgent(),
        agentApi.getHealth(),
      ])

      if (matchesResp.status === 'fulfilled') setMatches(matchesResp.value.matches || [])
      if (status.status === 'fulfilled') setOnlineStatus(status.value)
      if (info.status === 'fulfilled') setAgentInfo(info.value)
      if (health.status === 'fulfilled') {
        const h = health.value as any
        setDiscoveryRuns(h?.discovery?.runs_completed ?? 0)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleGoOnline() {
    try {
      await agentApi.goOnline()
      loadData()
    } catch {}
  }

  async function handleNegotiate(peerUrl: string) {
    setNegotiating(peerUrl)
    setNegResult(null)
    try {
      console.log('[negotiate] starting with peer:', peerUrl)
      const result = await agentApi.startNegotiation(peerUrl)
      console.log('[negotiate] result:', result)
      const state = (result as any).state || 'unknown'
      const peer = (result as any).peer || peerUrl
      setNegResult({ peer, state })

      // If confirmed, switch to chat after a short delay
      if (state === 'confirmed') {
        setTimeout(() => onSwitchToChat?.(), 1500)
      }
      loadData()
    } catch (err) {
      console.error('[negotiate] error:', err)
      setNegResult({ peer: peerUrl, state: 'error' })
    } finally {
      setNegotiating(null)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div style={{ color: colors.textMuted, animation: 'pulse 1.5s infinite' }}>Loading...</div>
      </div>
    )
  }

  return (
    <div style={{ padding: spacing.lg, overflow: 'auto', height: '100%' }}>
      {/* Status cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: spacing.md, marginBottom: spacing.xl }}>
        <Card>
          <div style={{ fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.xs }}>Status</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm }}>
            <div style={{
              width: 10, height: 10, borderRadius: '50%',
              background: onlineStatus?.is_online ? colors.success : colors.textMuted,
              boxShadow: onlineStatus?.is_online ? `0 0 8px ${colors.success}` : 'none',
            }} />
            <span style={{ fontSize: fontSize.lg, fontWeight: 600 }}>
              {onlineStatus?.is_online ? 'Online' : 'Offline'}
            </span>
          </div>
          {!onlineStatus?.is_online && (
            <Button small onClick={handleGoOnline} style={{ marginTop: spacing.sm }}>Go Online</Button>
          )}
        </Card>

        <Card>
          <div style={{ fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.xs }}>Matches</div>
          <div style={{ fontSize: fontSize.xxl, fontWeight: 700, color: colors.accent }}>
            {matches.length}
          </div>
          <div style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>compatible agents</div>
        </Card>

        <Card>
          <div style={{ fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.xs }}>Agent</div>
          <Badge variant={agentInfo?.status === 'running' ? 'success' : 'warning'}>
            {agentInfo?.status || 'unknown'}
          </Badge>
          {agentInfo?.agent_url && (
            <a href={agentInfo.agent_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: fontSize.xs, color: colors.accent, marginTop: spacing.xs, wordBreak: 'break-all', fontFamily: 'monospace', textDecoration: 'none', display: 'block' }}>
              {agentInfo.agent_url.replace('https://', '')}
            </a>
          )}
        </Card>
      </div>

      {/* Negotiation status */}
      {negotiating && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, padding: spacing.sm }}>
            <div style={{ animation: 'pulse 1s infinite', fontSize: 20 }}>⏳</div>
            <span style={{ color: colors.textSecondary }}>Negotiating with peer... This may take a moment.</span>
          </div>
        </Card>
      )}
      {negResult && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, padding: spacing.sm }}>
            <span style={{ fontSize: 20 }}>
              {negResult.state === 'confirmed' ? '✅' : negResult.state === 'error' ? '❌' : '🤝'}
            </span>
            <span style={{ color: colors.textSecondary }}>
              {negResult.state === 'confirmed'
                ? `Collaboration confirmed with ${negResult.peer}! Switching to chat...`
                : negResult.state === 'error'
                ? `Negotiation failed. Try again later.`
                : `Negotiation with ${negResult.peer} — state: ${negResult.state}`}
            </span>
            {negResult.state === 'confirmed' && (
              <Button small onClick={() => onSwitchToChat?.()}>Go to Chat</Button>
            )}
          </div>
        </Card>
      )}

      {/* Matches */}
      <h2 style={{ fontSize: fontSize.lg, fontWeight: 600, marginBottom: spacing.md }}>
        Top Matches
      </h2>

      {matches.length === 0 ? (
        <Card>
          <div style={{ textAlign: 'center', padding: spacing.xl }}>
            {!onlineStatus?.is_online ? (
              <>
                <div style={{ fontSize: 48, marginBottom: spacing.md }}>📡</div>
                <h3 style={{ fontSize: fontSize.lg, marginBottom: spacing.sm }}>Go online to discover agents</h3>
                <p style={{ color: colors.textSecondary, fontSize: fontSize.sm }}>
                  Your agent needs to be online to find compatible peers.
                </p>
              </>
            ) : discoveryRuns < 3 ? (
              <>
                <div style={{
                  width: 48, height: 48, borderRadius: '50%',
                  border: `3px solid ${colors.border}`, borderTopColor: colors.accent,
                  animation: 'spin 1s linear infinite',
                  margin: '0 auto', marginBottom: spacing.md,
                }} />
                <h3 style={{ fontSize: fontSize.lg, marginBottom: spacing.sm }}>Searching for compatible agents...</h3>
                <p style={{ color: colors.textSecondary, fontSize: fontSize.sm, marginBottom: spacing.md }}>
                  Usually takes 30–60 seconds. Discovery cycle {discoveryRuns}/3
                </p>
                {onSwitchToSearch && (
                  <Button small variant="secondary" onClick={onSwitchToSearch}>Search manually</Button>
                )}
              </>
            ) : (
              <>
                <div style={{ fontSize: 48, marginBottom: spacing.md }}>🔍</div>
                <h3 style={{ fontSize: fontSize.lg, marginBottom: spacing.sm }}>No compatible agents found yet</h3>
                <p style={{ color: colors.textSecondary, fontSize: fontSize.sm, marginBottom: spacing.md }}>
                  Discovery is running. Try searching manually for agents.
                </p>
                {onSwitchToSearch && (
                  <Button small variant="secondary" onClick={onSwitchToSearch}>Search agents</Button>
                )}
              </>
            )}
          </div>
        </Card>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
          {matches.slice(0, 10).map((m) => (
            <MatchCard
              key={m.agent_url}
              agentName={m.agent_name}
              agentUrl={m.agent_url}
              description={m.their_description}
              score={m.overall_score}
              skills={m.their_skills_text}
              isMutual={m.is_mutual}
              onNegotiate={() => handleNegotiate(m.agent_url)}
              onView={() => onViewAgent?.(m.agent_url)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
