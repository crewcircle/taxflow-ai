import Link from "next/link";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";

interface SiteHeaderProps {
  cta: "login" | "signup";
}

// Logged-out chrome for /login, /signup, /upgrade - mirrors
// crewcircle-website/src/components/layout/Header.tsx (sticky, blurred,
// max-w-7xl, hairline border) so these pages read as part of the same
// product family instead of standalone screens.
export function SiteHeader({ cta }: SiteHeaderProps) {
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
        <Logo />
        <nav>
          {cta === "login" ? (
            <Button asChild size="sm" className="bg-accent text-accent-foreground hover:opacity-90">
              <Link href="/signup">Start free trial</Link>
            </Button>
          ) : (
            <Button asChild variant="outline" size="sm">
              <Link href="/login">Login</Link>
            </Button>
          )}
        </nav>
      </div>
    </header>
  );
}
