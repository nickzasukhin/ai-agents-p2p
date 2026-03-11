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
}

export function HomeScreen({ onViewAgent }: HomeScreenProps) {
  const [matches, setMatches] = useState<agentApi.Match[]>([])
  const [onlineStatus, setOnlineStatus] = useState<agentApi.OnlineStatus | null>(null)
  const [agentInfo, setAgentInfo] = useState<orchApi.AgentInfo | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    setLoading(true)
    try {
      const [matchesResp, status, info] = await Promise.allSettled([
        agentApi.getMatches(),
        agentApi.getOnlineStatus(),
        orchApi.getMyAgent(),
      ])

      if (matchesResp.status === 'fulfilled') setMatches(matchesResp.value.matches || [])
      if (status.status === 'fulfilled') setOnlineStatus(status.value)
      if (info.status === 'fulfilled') setAgentInfo(info.value)
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
    try {
      await agentApi.startNegotiation(peerUrl)
      loadData()
    } catch {}
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

      {/* Matches */}
      <h2 style={{ fontSize: fontSize.lg, fontWeight: 600, marginBottom: spacing.md }}>
        Top Matches
      </h2>

      {matches.length === 0 ? (
        <Card>
          <div style={{ textAlign: 'center', padding: spacing.xl }}>
            <div style={{ fontSize: 48, marginBottom: spacing.md }}>🔍</div>
            <h3 style={{ fontSize: fontSize.lg, marginBottom: spacing.sm }}>No matches yet</h3>
            <p style={{ color: colors.textSecondary, fontSize: fontSize.sm }}>
              {onlineStatus?.is_online
                ? 'Your agent is discovering the network. Check back soon!'
                : 'Go online to start discovering compatible agents.'
              }
            </p>
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
