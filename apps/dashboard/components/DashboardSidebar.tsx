"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Settings } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { DashboardNavLink } from "@/components/DashboardNavLink";
import { RegulatoryBellLink } from "@/components/RegulatoryBellLink";
import { SignOutButton } from "@/components/SignOutButton";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

function humanizeType(type: string): string {
  return type.replace(/_/g, " ");
}

// Preview counts shown in a tooltip for these nav items, so the user knows
// how much is in each section before clicking in. Workspace merges two
// resource types (documents + ATO correspondence), so it fetches both and
// sums them; Library's count is just the firm's own precedents (the shared
// reference library's 600+ sources isn't a meaningful "preview" number).
const COUNT_TOOLTIPS: Record<string, { fetchUrls: string[]; noun: string }> = {
  "/dashboard/workspace": { fetchUrls: ["/api/documents", "/api/ato-response"], noun: "item" },
  "/dashboard/library": { fetchUrls: ["/api/firm-knowledge"], noun: "firm precedent" },
};

const STORAGE_KEY = "taxflow_nav_collapsed";

interface DashboardSidebarProps {
  navLinks: NavItem[];
  businessName: string;
  businessType: string;
}

export function DashboardSidebar({ navLinks, businessName, businessType }: DashboardSidebarProps) {
  // Collapsed by default - only expand if the user previously expanded it.
  const [collapsed, setCollapsed] = useState(true);
  const [counts, setCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    if (window.localStorage.getItem(STORAGE_KEY) !== "0") return;
    const t = setTimeout(() => setCollapsed(false), 0);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    Object.entries(COUNT_TOOLTIPS).forEach(([href, { fetchUrls }]) => {
      Promise.all(
        fetchUrls.map((url) =>
          fetch(url)
            .then((r) => (r.ok ? r.json() : []))
            .then((d: unknown[]) => (Array.isArray(d) ? d.length : 0))
            .catch(() => 0)
        )
      ).then((counts) =>
        setCounts((prev) => ({ ...prev, [href]: counts.reduce((a, b) => a + b, 0) }))
      );
    });
  }, []);

  function toggle() {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      return next;
    });
  }

  return (
    <aside
      className={`flex shrink-0 flex-col border-r border-border p-3 transition-[width] duration-150 ${
        collapsed ? "w-16" : "w-56"
      }`}
    >
      <nav className="flex flex-1 flex-col gap-1" data-tour="nav-sidebar">
        {navLinks.map((link) => {
          const countInfo = COUNT_TOOLTIPS[link.href];
          const navLink = (
            <DashboardNavLink href={link.href} icon={link.icon} collapsed={collapsed}>
              {link.label}
            </DashboardNavLink>
          );
          if (!countInfo) return <div key={link.href}>{navLink}</div>;
          const count = counts[link.href];
          return (
            <Tooltip key={link.href}>
              <TooltipTrigger asChild>{navLink}</TooltipTrigger>
              <TooltipContent side="right">
                {count === undefined
                  ? `View ${link.label.toLowerCase()}`
                  : `${count} ${countInfo.noun}${count === 1 ? "" : "s"} available`}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </nav>
      <Separator className="my-2" />
      {businessName && !collapsed && (
        <div className="mb-1 px-3 py-1">
          <p className="truncate text-sm font-medium text-foreground">{businessName}</p>
          <Badge variant="outline" className="mt-1 text-[10px]">
            {humanizeType(businessType)}
          </Badge>
        </div>
      )}
      <RegulatoryBellLink collapsed={collapsed} />
      <DashboardNavLink href="/dashboard/settings" icon={<Settings className="size-4" />} collapsed={collapsed}>
        Settings
      </DashboardNavLink>
      <SignOutButton collapsed={collapsed} />
      <button
        type="button"
        onClick={toggle}
        aria-label={collapsed ? "Expand menu" : "Collapse menu"}
        className="flex items-center justify-center rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        {collapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
      </button>
    </aside>
  );
}
