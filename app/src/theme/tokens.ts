/** DevPunks design tokens — dark theme with crimson accent. */

export const colors = {
  bgPrimary: '#0a0a0f',
  bgSecondary: '#12121a',
  bgCard: '#1a1a2e',
  bgCardHover: '#222240',
  bgInput: '#0f0f1a',

  textPrimary: '#FFFFFF',
  textSecondary: '#8888aa',
  textMuted: '#555570',
  textPlaceholder: '#444460',

  accent: '#E50051',
  accentHover: '#FF1A6C',
  accentMuted: 'rgba(229, 0, 81, 0.15)',

  success: '#00cec9',
  successMuted: 'rgba(0, 206, 201, 0.15)',
  warning: '#fdcb6e',
  warningMuted: 'rgba(253, 203, 110, 0.15)',
  error: '#ff4757',
  errorMuted: 'rgba(255, 71, 87, 0.15)',

  border: '#2a2a40',
  borderLight: '#333350',
  overlay: 'rgba(0, 0, 0, 0.6)',
} as const

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const

export const radius = {
  sm: 6,
  md: 10,
  lg: 16,
  xl: 24,
  full: 9999,
} as const

export const fontSize = {
  xs: 11,
  sm: 13,
  md: 15,
  lg: 18,
  xl: 22,
  xxl: 28,
  hero: 36,
} as const
