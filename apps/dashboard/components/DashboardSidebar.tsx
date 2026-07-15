"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { DashboardNavLink } from "@/components/DashboardNavLink";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

const STORAGE_KEY = "taxflow_nav_collapsed";

export function DashboardSidebar({ navLinks }: { navLinks: NavItem[] }) {
  // Collapsed by default - only expand if the user previously expanded it.
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => {
    if (window.localStorage.getItem(STORAGE_KEY) !== "0") return;
    const t = setTimeout(() => setCollapsed(false), 0);
    return () => clearTimeout(t);
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
        {navLinks.map((link) => (
          <DashboardNavLink key={link.href} href={link.href} icon={link.icon} collapsed={collapsed}>
            {link.label}
          </DashboardNavLink>
        ))}
      </nav>
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
