"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

interface DashboardNavLinkProps {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  collapsed?: boolean;
}

// `icon` must be a rendered element (e.g. <LayoutDashboard className="size-4" />),
// not a component reference - passing a Lucide component type from the Server
// Component layout down to this Client Component isn't serializable across the
// RSC boundary and throws "error in Server Components render" in production.
export function DashboardNavLink({ href, icon, children, collapsed }: DashboardNavLinkProps) {
  const pathname = usePathname();
  const isActive = href === "/dashboard" ? pathname === href : pathname.startsWith(href);

  return (
    <Link
      href={href}
      title={collapsed && typeof children === "string" ? children : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        collapsed && "justify-center px-2",
        isActive
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {icon}
      {!collapsed && children}
    </Link>
  );
}
