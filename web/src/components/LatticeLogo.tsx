export function LatticeLogo({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden
      focusable="false"
      style={{ display: 'block' }}
    >
      {/* L in two pieces — the glitch slice cuts the vertical stroke */}
      <path d="M15 9 h10 v13 h-10 Z" fill="currentColor" />
      <path d="M15 28 h10 v12 h21 v10 H15 Z" fill="currentColor" />
      {/* red glitch band, offset right of the cut */}
      <rect x="18" y="22" width="9" height="6" fill="#FF4D6D" />
      {/* terminal cursor block */}
      <rect x="46" y="9" width="8" height="8" fill="#FF4D6D" opacity="0.95" />
      {/* scanlines */}
      <rect x="11" y="54" width="42" height="2.4" rx="1.2" fill="currentColor" opacity="0.55" />
      <rect x="34" y="58" width="19" height="1.6" rx="0.8" fill="#FF4D6D" opacity="0.8" />
    </svg>
  )
}
