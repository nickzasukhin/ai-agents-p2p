/** Agent detail view — full profile of a discovered agent. */

import { useState, useEffect } from 'react'
import { Card } from '../components/Card'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { colors, spacing, fontSize, radius } from '../theme/tokens'
import * as agentApi from '../api/agent'

interface AgentDetailScreenProps {
  agentUrl: string
  onBack: () => void
  onNegotiate?: (url: string) => void
  onChat?: (url: string) => void
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100)
  return (
    <div style={{ marginBottom: spacing.sm }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
        <span style={{ fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'capitalize' }}>{label}</span>
        <span style={{ fontSize: fontSize.xs, color: colors.textSecondary }}>{pct}%</span>
      </div>
      <div style={{ height: 4, background: colors.bgPrimary, borderRadius: radius.full }}>
        <div style={{
          height: '100%', width: `${pct}%`,
          background: colors.accent, borderRadius: radius.full,
          transition: 'width 0.3s ease',
        }} />
      </div>
    </div>
  )
}

function scoreColor(pct: number): string {
  if (pct >= 70) return colors.success
  if (pct >= 40) return colors.warning
  return colors.textMuted
}

export function AgentDetailScreen({ agentUrl, onBack, onNegotiate, onChat }: AgentDetailScreenProps) {
  const [agent, setAgent] = useState<agentApi.AgentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadAgent()
  }, [agentUrl])

  async function loadAgent() {
    setLoading(true)
    setError(null)
    try {
      const data = await agentApi.getAgentDetail(agentUrl)
      setAgent(data)
    } catch (err: any) {
      setError(err.message || 'Failed to load agent')
    } finally {
      setLoading(false)
    }
  }

  // ── Loading ────────────────────────────────────────────

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div style={{ color: colors.textMuted, animation: 'pulse 1.5s infinite' }}>Loading agent...</div>
      </div>
    )
  }

  // ── Error ──────────────────────────────────────────────

  if (error || !agent) {
    return (
      <div style={{ padding: spacing.lg, height: '100%', overflow: 'auto' }}>
        <button onClick={onBack} style={{
          display: 'flex', alignItems: 'center', gap: spacing.xs,
          color: colors.textSecondary, fontSize: fontSize.sm, marginBottom: spacing.lg,
          background: 'none', cursor: 'pointer',
        }}>
          ← Back
        </button>
        <Card>
          <div style={{ textAlign: 'center', padding: spacing.xl }}>
            <div style={{ fontSize: 48, marginBottom: spacing.md }}>😕</div>
            <h3 style={{ fontSize: fontSize.lg, marginBottom: spacing.sm }}>Agent not found</h3>
            <p style={{ color: colors.textSecondary, fontSize: fontSize.sm }}>
              {error || 'Could not load agent details.'}
            </p>
          </div>
        </Card>
      </div>
    )
  }

  // ── Content ────────────────────────────────────────────

  const matchPct = agent.match ? Math.round(agent.match.overall_score * 100) : null
  const initial = (agent.agent_name || '?')[0].toUpperCase()

  return (
    <div style={{ padding: spacing.lg, height: '100%', overflow: 'auto' }}>
      <div style={{ maxWidth: 600, margin: '0 auto' }}>

        {/* Back button */}
        <button onClick={onBack} style={{
          display: 'flex', alignItems: 'center', gap: spacing.xs,
          color: colors.textSecondary, fontSize: fontSize.sm, marginBottom: spacing.lg,
          background: 'none', cursor: 'pointer',
        }}>
          ← Back
        </button>

        {/* Header */}
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.md }}>
            {/* Avatar */}
            <div style={{
              width: 56, height: 56, borderRadius: radius.full,
              background: colors.accentMuted, display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              fontSize: fontSize.xl, fontWeight: 700, color: colors.accent,
              flexShrink: 0,
            }}>
              {initial}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <h2 style={{ fontSize: fontSize.xl, fontWeight: 700, margin: 0 }}>
                {agent.agent_name}
              </h2>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.xs }}>
                {matchPct !== null && (
                  <Badge variant={matchPct >= 70 ? 'success' : matchPct >= 40 ? 'warning' : 'muted'}>
                    {`${matchPct}% match`}
                  </Badge>
                )}
                {agent.match?.is_mutual && <Badge variant="success">Mutual</Badge>}
                {agent.verified && <Badge variant="accent">Verified</Badge>}
              </div>
            </div>
          </div>
        </Card>

        {/* Description */}
        {agent.description && (
          <Card>
            <div style={{ fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.sm }}>
              About
            </div>
            <p style={{ color: colors.textSecondary, fontSize: fontSize.md, lineHeight: 1.6, margin: 0 }}>
              {agent.description}
            </p>
          </Card>
        )}

        {/* Skills */}
        {agent.skills.length > 0 && (
          <Card>
            <div style={{ fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.md }}>
              Skills
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.md }}>
              {agent.skills.map((s, i) => (
                <div key={i}>
                  <div style={{ fontSize: fontSize.sm, fontWeight: 600, marginBottom: spacing.xs }}>
                    {s.name}
                  </div>
                  {s.description && s.description !== s.name && (
                    <div style={{ fontSize: fontSize.sm, color: colors.textSecondary, marginBottom: spacing.xs, lineHeight: 1.5 }}>
                      {s.description}
                    </div>
                  )}
                  {s.tags.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.xs }}>
                      {s.tags.map((t, j) => (
                        <Badge key={j} variant="muted">{t}</Badge>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Match Analysis */}
        {agent.match && (
          <Card>
            <div style={{ fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.md }}>
              Match Analysis
            </div>

            {/* Overall score */}
            <div style={{ textAlign: 'center', marginBottom: spacing.lg }}>
              <div style={{ fontSize: fontSize.hero, fontWeight: 700, color: scoreColor(matchPct!) }}>
                {matchPct}%
              </div>
              <div style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>
                overall compatibility
              </div>
            </div>

            {/* Score breakdown */}
            {agent.match.score_breakdown && (
              <div style={{ marginBottom: spacing.lg }}>
                <div style={{ fontSize: fontSize.xs, color: colors.textMuted, marginBottom: spacing.sm }}>
                  Score Factors
                </div>
                {['embedding', 'tags', 'freshness', 'availability', 'history'].map((key) => {
                  const val = (agent.match!.score_breakdown as any)?.[key]
                  return val !== undefined && val > 0 ? (
                    <ScoreBar key={key} label={key} value={val} />
                  ) : null
                })}
              </div>
            )}

            {/* Skill matches */}
            {agent.match.skill_matches.length > 0 && (
              <div>
                <div style={{ fontSize: fontSize.xs, color: colors.textMuted, marginBottom: spacing.sm }}>
                  Skill Matches
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
                  {agent.match.skill_matches.map((sm, i) => (
                    <div key={i} style={{
                      padding: spacing.sm,
                      background: colors.bgPrimary,
                      borderRadius: radius.md,
                      fontSize: fontSize.sm,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <Badge variant={sm.direction === 'we_need_they_offer' ? 'success' : 'accent'}>
                          {sm.direction === 'we_need_they_offer' ? 'They can help you' : 'You can help them'}
                        </Badge>
                        <span style={{ color: scoreColor(Math.round(sm.similarity * 100)), fontWeight: 600 }}>
                          {Math.round(sm.similarity * 100)}%
                        </span>
                      </div>
                      <div style={{ color: colors.textSecondary, lineHeight: 1.5 }}>
                        <span style={{ color: colors.textPrimary }}>{sm.their_text}</span>
                        <span style={{ color: colors.textMuted }}> ↔ </span>
                        <span>{sm.our_text}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        )}

        {/* Identity */}
        <Card>
          <div style={{ fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.md }}>
            Identity
          </div>
          {agent.did && (
            <div style={{ marginBottom: spacing.sm }}>
              <div style={{ fontSize: fontSize.xs, color: colors.textMuted, marginBottom: 2 }}>DID</div>
              <div style={{
                fontSize: fontSize.xs, color: colors.textSecondary, fontFamily: 'monospace',
                wordBreak: 'break-all', background: colors.bgPrimary,
                padding: spacing.sm, borderRadius: radius.sm,
              }}>
                {agent.did}
              </div>
            </div>
          )}
          {agent.version && (
            <div style={{ marginBottom: spacing.sm }}>
              <div style={{ fontSize: fontSize.xs, color: colors.textMuted, marginBottom: 2 }}>Version</div>
              <div style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>{agent.version}</div>
            </div>
          )}
          {agent.provider && (
            <div>
              <div style={{ fontSize: fontSize.xs, color: colors.textMuted, marginBottom: 2 }}>Provider</div>
              <div style={{ fontSize: fontSize.sm, color: colors.textSecondary }}>{agent.provider.organization}</div>
            </div>
          )}
          <div style={{ marginTop: spacing.sm }}>
            <div style={{ fontSize: fontSize.xs, color: colors.textMuted, marginBottom: 2 }}>URL</div>
            <div style={{
              fontSize: fontSize.xs, color: colors.textSecondary, fontFamily: 'monospace',
              wordBreak: 'break-all',
            }}>
              {agent.agent_url}
            </div>
          </div>
        </Card>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: spacing.md, marginTop: spacing.md, marginBottom: spacing.xxl }}>
          {onNegotiate && (
            <Button onClick={() => onNegotiate(agentUrl)} style={{ flex: 1 }}>
              Negotiate
            </Button>
          )}
          {onChat && (
            <Button variant="secondary" onClick={() => onChat(agentUrl)} style={{ flex: 1 }}>
              Chat
            </Button>
          )}
        </div>

      </div>
    </div>
  )
}
