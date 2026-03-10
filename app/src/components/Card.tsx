/** Card container component. */

import { CSSProperties, ReactNode } from 'react'
import { colors, radius, spacing } from '../theme/tokens'

interface CardProps {
  children: ReactNode
  style?: CSSProperties
  onClick?: () => void
  hoverable?: boolean
}

export function Card({ children, style, onClick, hoverable }: CardProps) {
  return (
    <div
      onClick={onClick}
      style={{
        background: colors.bgCard,
        border: `1px solid ${colors.border}`,
        borderRadius: radius.lg,
        padding: spacing.lg,
        cursor: onClick ? 'pointer' : undefined,
        transition: 'all 0.15s ease',
        ...(hoverable ? { cursor: 'pointer' } : {}),
        ...style,
      }}
      onMouseEnter={(e) => {
        if (hoverable || onClick) {
          e.currentTarget.style.borderColor = colors.borderLight
          e.currentTarget.style.background = colors.bgCardHover
        }
      }}
      onMouseLeave={(e) => {
        if (hoverable || onClick) {
          e.currentTarget.style.borderColor = colors.border
          e.currentTarget.style.background = colors.bgCard
        }
      }}
    >
      {children}
    </div>
  )
}
