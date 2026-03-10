/** Status badge component. */

import { CSSProperties } from 'react'
import { colors, radius, fontSize, spacing } from '../theme/tokens'

type BadgeVariant = 'accent' | 'success' | 'warning' | 'error' | 'muted'

const variantStyles: Record<BadgeVariant, CSSProperties> = {
  accent: { background: colors.accentMuted, color: colors.accent },
  success: { background: colors.successMuted, color: colors.success },
  warning: { background: colors.warningMuted, color: colors.warning },
  error: { background: colors.errorMuted, color: colors.error },
  muted: { background: colors.bgCard, color: colors.textMuted },
}

interface BadgeProps {
  children: string
  variant?: BadgeVariant
  style?: CSSProperties
}

export function Badge({ children, variant = 'muted', style }: BadgeProps) {
  return (
    <span
      style={{
        ...variantStyles[variant],
        display: 'inline-flex',
        alignItems: 'center',
        padding: `${spacing.xs}px ${spacing.sm}px`,
        borderRadius: radius.full,
        fontSize: fontSize.xs,
        fontWeight: 600,
        letterSpacing: 0.5,
        textTransform: 'uppercase',
        ...style,
      }}
    >
      {children}
    </span>
  )
}
