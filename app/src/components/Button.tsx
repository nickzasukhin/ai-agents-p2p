/** Reusable button component with DevPunks styling. */

import { CSSProperties, ReactNode } from 'react'
import { colors, radius, fontSize } from '../theme/tokens'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps {
  children: ReactNode
  onClick?: () => void
  variant?: Variant
  disabled?: boolean
  loading?: boolean
  fullWidth?: boolean
  small?: boolean
  style?: CSSProperties
  type?: 'button' | 'submit'
}

const variants: Record<Variant, CSSProperties> = {
  primary: {
    background: colors.accent,
    color: '#fff',
  },
  secondary: {
    background: colors.bgCard,
    color: colors.textPrimary,
    border: `1px solid ${colors.border}`,
  },
  ghost: {
    background: 'transparent',
    color: colors.textSecondary,
  },
  danger: {
    background: colors.errorMuted,
    color: colors.error,
  },
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  disabled,
  loading,
  fullWidth,
  small,
  style,
  type = 'button',
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      style={{
        ...variants[variant],
        padding: small ? '8px 16px' : '12px 24px',
        borderRadius: radius.md,
        fontSize: small ? fontSize.sm : fontSize.md,
        fontWeight: 600,
        width: fullWidth ? '100%' : undefined,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'all 0.15s ease',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        ...style,
      }}
    >
      {loading && <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</span>}
      {children}
    </button>
  )
}
