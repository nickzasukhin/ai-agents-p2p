import { Component, type ReactNode } from 'react'

// ── Time utility ────────────────────────────────────────────

export function timeAgo(ts: string | Date): string {
  const now = Date.now()
  const then = new Date(ts).getTime()
  const diff = Math.max(0, now - then)

  const seconds = Math.floor(diff / 1000)
  if (seconds < 10) return 'just now'
  if (seconds < 60) return `${seconds}s ago`

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`

  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`

  return new Date(ts).toLocaleDateString()
}

// ── Skeleton ────────────────────────────────────────────────

type SkeletonProps = {
  lines?: number
  cards?: number
}

export function Skeleton({ lines = 0, cards = 0 }: SkeletonProps) {
  return (
    <div className="animate-in">
      {Array.from({ length: cards }).map((_, i) => (
        <div key={`card-${i}`} className="skeleton skeleton-card" />
      ))}
      {Array.from({ length: lines }).map((_, i) => (
        <div key={`line-${i}`} className="skeleton skeleton-line" />
      ))}
    </div>
  )
}

// ── Confirm Dialog ──────────────────────────────────────────

type ConfirmDialogProps = {
  title: string
  message: string
  confirmLabel?: string
  confirmVariant?: 'primary' | 'success' | 'danger'
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Confirm',
  confirmVariant = 'primary',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <h3>{title}</h3>
        <p>{message}</p>
        <div className="modal-actions">
          <button className="btn-outline" onClick={onCancel}>Cancel</button>
          <button className={`btn-${confirmVariant}`} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Error Boundary ──────────────────────────────────────────

type EBProps = {
  children: ReactNode
  fallbackMessage?: string
}

type EBState = {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<EBProps, EBState> {
  constructor(props: EBProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): EBState {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <h3>Something went wrong</h3>
          <p>{this.props.fallbackMessage || this.state.error?.message || 'An unexpected error occurred'}</p>
          <button
            className="btn-primary"
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            Try Again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
