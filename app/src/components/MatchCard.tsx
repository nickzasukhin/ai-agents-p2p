/** Agent match card with score and skills. */

import { Card } from './Card'
import { Badge } from './Badge'
import { Button } from './Button'
import { colors, spacing, fontSize } from '../theme/tokens'

interface MatchCardProps {
  agentName: string
  agentUrl: string
  description: string
  score: number
  skills: string
  isMutual?: boolean
  onNegotiate?: () => void
  onView?: () => void
}

export function MatchCard({
  agentName,
  description,
  score,
  skills,
  isMutual,
  onNegotiate,
  onView,
}: MatchCardProps) {
  const scorePercent = Math.round(score * 100)
  const scoreColor = scorePercent >= 70 ? colors.success : scorePercent >= 40 ? colors.warning : colors.textMuted

  return (
    <Card hoverable onClick={onView}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: spacing.md }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.xs }}>
            <h3 style={{ fontSize: fontSize.lg, fontWeight: 600, margin: 0 }}>{agentName}</h3>
            {isMutual && <Badge variant="success">Mutual</Badge>}
          </div>
          {description && (
            <p style={{ color: colors.textSecondary, fontSize: fontSize.sm, margin: `${spacing.xs}px 0`, lineHeight: 1.5 }}>
              {description.slice(0, 120)}{description.length > 120 ? '...' : ''}
            </p>
          )}
          {skills && (
            <p style={{ color: colors.textMuted, fontSize: fontSize.xs, margin: 0 }}>
              {skills.slice(0, 80)}{skills.length > 80 ? '...' : ''}
            </p>
          )}
        </div>
        <div style={{ textAlign: 'center', flexShrink: 0 }}>
          <div style={{ fontSize: fontSize.xl, fontWeight: 700, color: scoreColor }}>
            {scorePercent}%
          </div>
          <div style={{ fontSize: fontSize.xs, color: colors.textMuted }}>match</div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: spacing.sm, marginTop: spacing.md }}>
        {onNegotiate && (
          <div onClick={(e) => e.stopPropagation()}>
            <Button small onClick={onNegotiate}>Negotiate</Button>
          </div>
        )}
      </div>
    </Card>
  )
}
