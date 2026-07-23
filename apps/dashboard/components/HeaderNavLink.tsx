"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

interface HeaderNavLinkProps {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}

// Horizontal top-header equivalent of the old vertical sidebar nav link.
// `icon` must be a rendered element, not a component reference - passing a
// Lucide component type from the Server Component layout down to this
// Client Component isn't serializable across the RSC boundary.
export function HeaderNavLink({ href, icon, children }: HeaderNavLinkProps) {
  const pathname = usePathname();
  const isActive = href === "/dashboard" ? pathname === href : pathname.startsWith(href);

  return (
    <Link
      href={href}
      // Never prefetch the route already active: this link is persistent
      // header chrome, so its default auto-prefetch keeps re-firing (~every
      // 30s) for as long as the page is open - re-prefetching the ACTIVE
      // route re-executes its client component tree instead of just warming
      // an unused cache entry (a real, confirmed production bug).
      prefetch={isActive ? false : undefined}
      className={cn(
        "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
        isActive
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {icon}
      {children}
    </Link>
  );
}
