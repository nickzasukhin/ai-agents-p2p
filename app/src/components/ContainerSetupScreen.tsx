/** Full-screen container setup progress screen.
 *
 * Shows animated step-by-step progress while Docker container
 * is being created and started for a new user.
 */

import { useState, useEffect } from 'react'
import { Logo } from './Logo'
import { Button } from './Button'
import { colors, spacing, fontSize, radius } from '../theme/tokens'

export type SetupPhase = 'creating' | 'starting' | 'health_check' | 'ready' | 'error' | 'timeout'

interface ContainerSetupScreenProps {
  phase: SetupPhase
  error?: string | null
  onRetry?: () => void
}

const STEPS: { key: SetupPhase; label: string }[] = [
  { key: 'creating', label: 'Creating' },
  { key: 'starting', label: 'Starting' },
  { key: 'health_check', label: 'Checking' },
  { key: 'ready', label: 'Ready' },
]

const PHASE_ORDER: Record<string, number> = {
  creating: 0,
  starting: 1,
  health_check: 2,
  ready: 3,
  error: -1,
  timeout: -1,
}

const TIPS = [
  'Your agent gets an isolated environment with its own database',
  'Each agent runs in a separate Docker container',
  'After setup, your agent will discover and chat with other agents',
  'Your agent will be available at a unique subdomain',
  'The P2P network connects agents worldwide',
]

const PHASE_MESSAGES: Record<string, string> = {
  creating: 'Creating your personal agent...',
  starting: 'Starting container...',
  health_check: 'Almost ready...',
  ready: 'Your agent is ready!',
  error: 'Something went wrong',
  timeout: 'Taking longer than usual...',
}

export function ContainerSetupScreen({ phase, error, onRetry }: ContainerSetupScreenProps) {
  const [elapsed, setElapsed] = useState(0)
  const [tipIndex, setTipIndex] = useState(0)

  // Timer
  useEffect(() => {
    if (phase === 'ready') return
    const t = setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => clearInterval(t)
  }, [phase])

  // Rotate tips every 5 seconds
  useEffect(() => {
    const t = setInterval(() => setTipIndex((i) => (i + 1) % TIPS.length), 5000)
    return () => clearInterval(t)
  }, [])

  const currentStep = PHASE_ORDER[phase] ?? -1
  const isError = phase === 'error' || phase === 'timeout'

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      height: '100%', background: colors.bgPrimary, padding: spacing.xl,
    }}>
      {/* Logo */}
      <div style={{ marginBottom: spacing.xxl, opacity: 0.8 }}>
        <Logo size={36} />
      </div>

      {/* Animated spinner / checkmark / error */}
      <div style={{ marginBottom: spacing.xl, position: 'relative' }}>
        {phase === 'ready' ? (
          <div style={{
            width: 72, height: 72, borderRadius: '50%',
            background: colors.successMuted,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            animation: 'scaleIn 0.4s ease',
          }}>
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke={colors.success} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
        ) : isError ? (
          <div style={{
            width: 72, height: 72, borderRadius: '50%',
            background: colors.errorMuted,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke={colors.error} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </div>
        ) : (
          <div style={{
            width: 72, height: 72, borderRadius: '50%',
            border: `3px solid ${colors.border}`,
            borderTopColor: colors.accent,
            animation: 'spin 1s linear infinite',
          }} />
        )}
      </div>

      {/* Status message */}
      <h2 style={{
        fontSize: fontSize.xl, fontWeight: 600, color: colors.textPrimary,
        marginBottom: spacing.sm, textAlign: 'center',
      }}>
        {PHASE_MESSAGES[phase]}
      </h2>

      {/* Error detail */}
      {error && (
        <p style={{
          fontSize: fontSize.sm, color: colors.error,
          marginBottom: spacing.md, textAlign: 'center', maxWidth: 400,
        }}>
          {error}
        </p>
      )}

      {/* Step indicator */}
      {!isError && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 0,
          marginTop: spacing.lg, marginBottom: spacing.lg,
        }}>
          {STEPS.map((step, i) => (
            <div key={step.key} style={{ display: 'flex', alignItems: 'center' }}>
              {/* Step dot */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: fontSize.xs, fontWeight: 700, color: '#fff',
                  background: i < currentStep ? colors.success
                    : i === currentStep ? colors.accent
                    : colors.bgCard,
                  border: i === currentStep ? `2px solid ${colors.accentHover}` : '2px solid transparent',
                  boxShadow: i === currentStep ? `0 0 12px ${colors.accentMuted}` : 'none',
                  transition: 'all 0.3s ease',
                  animation: i === currentStep ? 'pulse 2s infinite' : 'none',
                }}>
                  {i < currentStep ? (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  ) : (
                    i + 1
                  )}
                </div>
                <span style={{
                  fontSize: 10, color: i <= currentStep ? colors.textSecondary : colors.textMuted,
                  fontWeight: i === currentStep ? 600 : 400,
                  transition: 'color 0.3s',
                }}>
                  {step.label}
                </span>
              </div>
              {/* Connector line */}
              {i < STEPS.length - 1 && (
                <div style={{
                  width: 40, height: 2, marginBottom: 20, marginLeft: 4, marginRight: 4,
                  background: i < currentStep ? colors.success : colors.bgCard,
                  borderRadius: 1,
                  transition: 'background 0.3s ease',
                }} />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Timer */}
      {phase !== 'ready' && (
        <div style={{
          fontSize: fontSize.sm, color: colors.textMuted,
          marginBottom: spacing.sm,
          fontVariantNumeric: 'tabular-nums',
        }}>
          {elapsed}s
        </div>
      )}

      {/* Hint */}
      {!isError && phase !== 'ready' && (
        <p style={{
          fontSize: fontSize.sm, color: colors.textMuted,
          textAlign: 'center', maxWidth: 320,
          marginBottom: spacing.md,
        }}>
          Usually takes 20-30 seconds
        </p>
      )}

      {/* Rotating tip */}
      {!isError && phase !== 'ready' && (
        <div style={{
          fontSize: fontSize.xs, color: colors.textMuted,
          textAlign: 'center', maxWidth: 360,
          minHeight: 32,
          opacity: 0.7, fontStyle: 'italic',
          transition: 'opacity 0.3s',
        }}>
          {TIPS[tipIndex]}
        </div>
      )}

      {/* Retry / Refresh buttons */}
      {isError && (
        <div style={{ display: 'flex', gap: spacing.sm, marginTop: spacing.lg }}>
          {onRetry && (
            <Button onClick={onRetry}>Try Again</Button>
          )}
          <Button variant="secondary" onClick={() => window.location.reload()}>
            Refresh Page
          </Button>
        </div>
      )}

      {/* CSS */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
        @keyframes scaleIn {
          from { transform: scale(0); opacity: 0; }
          to { transform: scale(1); opacity: 1; }
        }
      `}</style>
    </div>
  )
}
