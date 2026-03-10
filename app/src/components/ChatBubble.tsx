/** Chat message bubble. */

import { colors, radius, spacing, fontSize } from '../theme/tokens'

interface ChatBubbleProps {
  content: string
  isOwn: boolean
  timestamp?: string
}

export function ChatBubble({ content, isOwn, timestamp }: ChatBubbleProps) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isOwn ? 'flex-end' : 'flex-start',
        padding: `${spacing.xs}px 0`,
      }}
    >
      <div
        style={{
          maxWidth: '80%',
          padding: `${spacing.sm}px ${spacing.md}px`,
          borderRadius: radius.lg,
          background: isOwn ? colors.accent : colors.bgCard,
          color: isOwn ? '#fff' : colors.textPrimary,
          fontSize: fontSize.md,
          lineHeight: 1.5,
          borderBottomRightRadius: isOwn ? radius.sm : radius.lg,
          borderBottomLeftRadius: isOwn ? radius.lg : radius.sm,
        }}
      >
        <div>{content}</div>
        {timestamp && (
          <div
            style={{
              fontSize: fontSize.xs,
              color: isOwn ? 'rgba(255,255,255,0.6)' : colors.textMuted,
              marginTop: 4,
              textAlign: 'right',
            }}
          >
            {new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        )}
      </div>
    </div>
  )
}
