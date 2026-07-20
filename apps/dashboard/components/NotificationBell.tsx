"use client";

import { useEffect, useRef, useState } from "react";
import { Bell, Check, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useNotifications } from "@/lib/useNotifications";

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function NotificationBell() {
  const { notifications, unreadCount, markRead, remove } = useNotifications();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

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
        aria-label={unreadCount > 0 ? `${unreadCount} unread notifications` : "Notifications"}
        aria-expanded={open}
        className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Bell className="size-4" />
        {unreadCount > 0 && (
          <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-accent text-[9px] font-bold leading-none text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-lg">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Notifications
            </span>
            {unreadCount > 0 && (
              <Badge variant="secondary" className="text-[10px]">
                {unreadCount} unread
              </Badge>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto">
            {recent.length === 0 ? (
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
