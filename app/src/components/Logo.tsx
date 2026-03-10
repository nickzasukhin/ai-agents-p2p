/** DevPunks logo component. */

interface LogoProps {
  size?: number
  className?: string
}

export function Logo({ size = 32, className }: LogoProps) {
  const fontSize = size * 0.65
  return (
    <span
      className={className}
      style={{
        fontFamily: "'Inter', sans-serif",
        fontWeight: 700,
        fontSize,
        letterSpacing: -1,
        userSelect: 'none',
      }}
    >
      Dev<span style={{ color: '#E50051' }}>/</span>Punks
    </span>
  )
}
