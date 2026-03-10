/** Reusable input component with DevPunks styling. */

import { CSSProperties } from 'react'
import { colors, radius, fontSize, spacing } from '../theme/tokens'

interface InputProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  type?: string
  onKeyDown?: (e: React.KeyboardEvent) => void
  autoFocus?: boolean
  disabled?: boolean
  style?: CSSProperties
}

export function Input({
  value,
  onChange,
  placeholder,
  type = 'text',
  onKeyDown,
  autoFocus,
  disabled,
  style,
}: InputProps) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      onKeyDown={onKeyDown}
      autoFocus={autoFocus}
      disabled={disabled}
      style={{
        width: '100%',
        padding: `${spacing.md}px`,
        background: colors.bgInput,
        border: `1px solid ${colors.border}`,
        borderRadius: radius.md,
        color: colors.textPrimary,
        fontSize: fontSize.md,
        transition: 'border-color 0.15s ease',
        ...style,
      }}
      onFocus={(e) => (e.target.style.borderColor = colors.accent)}
      onBlur={(e) => (e.target.style.borderColor = colors.border)}
    />
  )
}
