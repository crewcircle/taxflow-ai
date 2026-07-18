"use client";

import { useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { DashboardNavLink } from "@/components/DashboardNavLink";

const LAST_SEEN_KEY = "taxflow_regulatory_last_seen";

export function RegulatoryBellLink({ collapsed }: { collapsed?: boolean }) {
  const [hasUnread, setHasUnread] = useState(false);

  useEffect(() => {
    fetch("/api/regulatory-alerts")
      .then((r) => (r.ok ? r.json() : []))
      .then((alerts: { detected_at: string }[]) => {
        if (!alerts.length) return;
        const latest = alerts[0].detected_at;
        const lastSeen = window.localStorage.getItem(LAST_SEEN_KEY);
        setHasUnread(!lastSeen || new Date(latest) > new Date(lastSeen));
      })
      .catch(() => {});
  }, []);

  function markSeen() {
    window.localStorage.setItem(LAST_SEEN_KEY, new Date().toISOString());
    setHasUnread(false);
  }

  return (
    <div className="relative" onClick={markSeen}>
      <DashboardNavLink href="/dashboard/regulatory" icon={<Bell className="size-4" />} collapsed={collapsed}>
        Regulatory updates
      </DashboardNavLink>
      {hasUnread && (
        <span className="absolute right-2 top-2 size-1.5 rounded-full bg-accent" aria-label="New regulatory updates" />
      )}
    </div>
  );
}
