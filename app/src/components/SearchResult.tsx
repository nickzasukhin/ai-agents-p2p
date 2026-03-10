/** Search result card. */

import { Card } from './Card'
import { Badge } from './Badge'
import { colors, spacing, fontSize } from '../theme/tokens'

interface SearchResultProps {
  agentName: string
  description: string
  skills: { name: string; tags: string[] }[]
  matchScore: number
  source: string
  onClick?: () => void
}

export function SearchResult({ agentName, description, skills, matchScore, source, onClick }: SearchResultProps) {
  return (
    <Card hoverable onClick={onClick}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3 style={{ fontSize: fontSize.md, fontWeight: 600, margin: 0 }}>{agentName}</h3>
          <p style={{ color: colors.textSecondary, fontSize: fontSize.sm, margin: `${spacing.xs}px 0`, lineHeight: 1.5 }}>
            {description.slice(0, 150)}{description.length > 150 ? '...' : ''}
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.sm }}>
            {skills.slice(0, 4).map((s, i) => (
              <Badge key={i} variant="muted">{s.name}</Badge>
            ))}
            {source === 'registry' && <Badge variant="accent">Registry</Badge>}
          </div>
        </div>
        <div style={{ textAlign: 'center', flexShrink: 0, marginLeft: spacing.md }}>
          <div style={{ fontSize: fontSize.lg, fontWeight: 700, color: colors.accent }}>
            {Math.round(matchScore * 100)}%
          </div>
        </div>
      </div>
    </Card>
  )
}
