import Link from "next/link";

// CrewCircle brand mark (orange->amber gradient circle) with the TaxFlow wordmark.
// Mirrors crewcircle-website/src/components/layout/Header.tsx.
export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2">
      <div className="flex items-center justify-center rounded-full bg-gradient-to-br from-orange-500 to-amber-600 shadow-md w-8 h-8">
        <span className="text-white font-bold text-sm">C</span>
      </div>
      <span className="flex flex-col leading-none">
        <span className="text-xl font-bold tracking-tight text-foreground">
          Tax<span className="text-accent">Flow</span>
        </span>
        <span className="text-[10px] font-medium text-muted-foreground tracking-wide">
          by CrewCircle
        </span>
      </span>
    </Link>
  );
}
