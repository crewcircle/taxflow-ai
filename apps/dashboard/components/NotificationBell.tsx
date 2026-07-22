"use client";

import { useEffect, useRef, useState } from "react";
import { Bell, Check, Scale, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useNotifications } from "@/lib/useNotifications";

const REGULATORY_LAST_SEEN_KEY = "taxflow_regulatory_last_seen";

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

// One bell for everything that can page the user - app notifications
// (answer improved, re-research failed) AND new regulatory/ATO alerts, which
// used to have their own separate unread dot on the sidebar's "Regulatory
// updates" link. Two independent unread indicators in two different corners
// of the screen was the actual "which one has something new?" confusion -
// this folds the regulatory feed in as just another notification kind.
function useRegulatoryAlert() {
  const [alert, setAlert] = useState<{ detectedAt: string; isNew: boolean } | null>(null);

  useEffect(() => {
    fetch("/api/regulatory-alerts")
      .then((r) => (r.ok ? r.json() : []))
      .then((alerts: { detected_at: string }[]) => {
        if (!alerts.length) return;
        const latest = alerts[0].detected_at;
        const lastSeen = window.localStorage.getItem(REGULATORY_LAST_SEEN_KEY);
        setAlert({ detectedAt: latest, isNew: !lastSeen || new Date(latest) > new Date(lastSeen) });
      })
      .catch(() => {});
  }, []);

  function markSeen() {
    if (!alert) return;
    window.localStorage.setItem(REGULATORY_LAST_SEEN_KEY, new Date().toISOString());
    setAlert({ ...alert, isNew: false });
  }

  return { alert, markSeen };
}

export function NotificationBell() {
  const { notifications, unreadCount, markRead, remove } = useNotifications();
  const { alert: regulatoryAlert, markSeen: markRegulatorySeen } = useRegulatoryAlert();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const totalUnread = unreadCount + (regulatoryAlert?.isNew ? 1 : 0);

  // Close the dropdown on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const recent = notifications.slice(0, 8);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={totalUnread > 0 ? `${totalUnread} unread notifications` : "Notifications"}
        aria-expanded={open}
        className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Bell className="size-4" />
        {totalUnread > 0 && (
          <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-accent text-[9px] font-bold leading-none text-white">
            {totalUnread > 9 ? "9+" : totalUnread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Notifications
            </span>
            {totalUnread > 0 && (
              <Badge variant="secondary" className="text-[10px]">
                {totalUnread} unread
              </Badge>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto">
            {regulatoryAlert && (
              <a
                href="/dashboard/library?tab=reference"
                onClick={markRegulatorySeen}
                className={cn(
                  "flex items-start gap-2 border-b border-border/60 px-3 py-2",
                  regulatoryAlert.isNew && "bg-accent/5"
                )}
              >
                <Scale className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                <span className="flex flex-1 flex-col gap-0.5">
                  <span className="flex items-center gap-1.5">
                    {regulatoryAlert.isNew && <span className="size-1.5 shrink-0 rounded-full bg-accent" />}
                    <span className="line-clamp-1 text-sm font-medium">New regulatory update</span>
                  </span>
                  <span className="line-clamp-2 text-xs text-muted-foreground">
                    A new ATO/tax law change relevant to your clients was detected
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    {relativeTime(regulatoryAlert.detectedAt)}
                  </span>
                </span>
              </a>
            )}
            {recent.length === 0 && !regulatoryAlert ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                No notifications yet.
              </p>
            ) : (
              recent.map((n) => {
                const isUnread = !n.read_at;
                const inner = (
                  <span className="flex flex-1 flex-col gap-0.5">
                    <span className="flex items-center gap-1.5">
                      {isUnread && <span className="size-1.5 shrink-0 rounded-full bg-accent" />}
                      <span className="line-clamp-1 text-sm font-medium">
                        {n.title || "Notification"}
                      </span>
                    </span>
                    {n.body && (
                      <span className="line-clamp-2 text-xs text-muted-foreground">{n.body}</span>
                    )}
                    <span className="text-[10px] text-muted-foreground">
                      {relativeTime(n.created_at)}
                    </span>
                  </span>
                );

                function handleClick() {
                  if (isUnread) markRead(n.id);
                  if (n.query_id) {
                    window.location.href = `/dashboard/query?query=${n.query_id}`;
                  } else {
                    setOpen(false);
                  }
                }

                return (
                  <div
                    key={n.id}
                    className={cn(
                      "flex items-start gap-2 border-b border-border/60 px-3 py-2 last:border-b-0",
                      isUnread && "bg-accent/5"
                    )}
                  >
                    <button
                      type="button"
                      onClick={handleClick}
                      className="flex flex-1 items-start gap-2 text-left"
                    >
                      {inner}
                    </button>
                    {isUnread && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-6 shrink-0"
                        aria-label="Mark read"
                        onClick={() => markRead(n.id)}
                      >
                        <Check className="size-3.5" />
                      </Button>
                    )}
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-6 shrink-0"
                      aria-label="Delete notification"
                      onClick={() => remove(n.id)}
                    >
                      <X className="size-3.5" />
                    </Button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
