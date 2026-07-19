import Link from "next/link";

// The actual CrewCircle mark (three linked nodes in a ring), matching
// crewcircle-website/src/components/Logo.tsx exactly - not a placeholder.
function CrewCircleMark({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 200 200"
      className={className}
      role="img"
      aria-label="CrewCircle"
    >
      <circle cx="100" cy="100" r="90" fill="none" stroke="#ff6b35" strokeWidth="8" />
      <circle cx="100" cy="60" r="18" fill="#ff6b35" />
      <rect x="88" y="78" width="24" height="20" rx="4" fill="#ff6b35" />
      <circle cx="65" cy="120" r="18" fill="#ff6b35" opacity="0.8" />
      <rect x="53" y="138" width="24" height="20" rx="4" fill="#ff6b35" opacity="0.8" />
      <circle cx="135" cy="120" r="18" fill="#ff6b35" opacity="0.6" />
      <rect x="123" y="138" width="24" height="20" rx="4" fill="#ff6b35" opacity="0.6" />
      <path
        d="M 90 100 L 95 105 L 115 85"
        fill="none"
        stroke="#ffffff"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// TaxFlow wordmark with the CrewCircle brand mark. Pass `onDark` when this
// renders over a dark section (e.g. the footer) so "Tax" and the subtitle
// stay readable instead of using the light-theme near-black foreground color.
export function Logo({ href = "/", onDark = false }: { href?: string; onDark?: boolean }) {
  return (
    <Link href={href} className="flex items-center gap-2">
      <CrewCircleMark className="h-8 w-8 shrink-0" />
      <span className="flex flex-col leading-none">
        <span className={`text-xl font-bold tracking-tight ${onDark ? "text-white" : "text-foreground"}`}>
          Tax<span className="text-accent">Flow</span>
        </span>
        <span
          className={`text-[10px] font-medium tracking-wide ${
            onDark ? "text-white/60" : "text-muted-foreground"
          }`}
        >
          by CrewCircle
        </span>
      </span>
    </Link>
  );
}
