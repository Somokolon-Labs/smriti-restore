/** Eight-fold stitched medallion, drawn rather than shipped as an asset. */
export function Logo({ className = "h-7 w-7" }: { className?: string }) {
  const petals = Array.from({ length: 8 }, (_, index) => {
    const angle = (index * Math.PI) / 4;
    return {
      cx: 16 + Math.cos(angle) * 7.4,
      cy: 16 + Math.sin(angle) * 7.4,
      rotate: (angle * 180) / Math.PI,
    };
  });

  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label="Smriti">
      <circle
        cx="16"
        cy="16"
        r="14"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeDasharray="3.2 3"
        opacity="0.55"
      />
      {petals.map((petal, index) => (
        <ellipse
          key={index}
          cx={petal.cx}
          cy={petal.cy}
          rx="4.1"
          ry="2.3"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
          transform={`rotate(${petal.rotate} ${petal.cx} ${petal.cy})`}
        />
      ))}
      <circle cx="16" cy="16" r="2.5" fill="currentColor" />
    </svg>
  );
}
