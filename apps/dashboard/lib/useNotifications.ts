"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

export interface AppNotification {
  id: string;
  kind: string;
  query_id: string | null;
  title: string | null;
  body: string | null;
  read_at: string | null;
  created_at: string;
}

// Fired whenever a fresh batch of notifications arrives, so other parts of the
// dashboard (e.g. the query history sidebar) can refresh derived state like the
// inline re-research badge without coupling to this hook directly.
export const NOTIFICATIONS_UPDATED_EVENT = "taxflow:notifications-updated";

const POLL_INTERVAL_MS = 30_000;

// Module-level guard against more than one poll interval ever running at
// once. Investigated a live bug where this poll's effective frequency was
// running ~10-15x faster than POLL_INTERVAL_MS, which only happens if
// multiple copies of this effect are active simultaneously - this hook is
// called from exactly one place in the tree (NotificationBell), so this
// should be structurally impossible, but a stray second mount (e.g. from a
// framework-level remount this app has been fighting) would otherwise
// silently stack intervals with no error and no easy way to notice. Belt and
// suspenders: only the FIRST mount gets a real interval; any concurrent
// second mount is a no-op until the first one unmounts.
let activePoller = false;

/**
 * Lightweight polling hook for the notifications feed. Polls every ~30s (SSE
 * can't deliver a completion event after the query stream closes, so the
 * dashboard polls instead). Surfaces a toast the first time an
 * `answer_improved` notification is seen, linking to the improved query.
 */
export function useNotifications() {
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  // Track ids we've already toasted so a repeated poll doesn't re-toast.
  const seenToastIds = useRef<Set<string>>(new Set());
  // First load shouldn't toast pre-existing notifications - only genuinely new
  // ones that arrive while the dashboard is open.
  const primed = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/notifications");
      if (!response.ok) return;
      const data: AppNotification[] = await response.json();
      if (!Array.isArray(data)) return;

      if (primed.current) {
        for (const n of data) {
          if (n.read_at || seenToastIds.current.has(n.id)) continue;
          seenToastIds.current.add(n.id);
          if (n.kind === "answer_improved") {
            toast.success(n.title || "Answer improved", {
              description: n.body || "A re-researched answer is ready.",
              action: n.query_id
                ? {
                    label: "View",
                    onClick: () => {
                      window.location.href = `/dashboard/query?query=${n.query_id}`;
                    },
                  }
                : undefined,
            });
          } else if (n.kind === "re_research_failed") {
            toast.warning(n.title || "Re-research failed", {
              description: n.body || "We couldn't improve that answer.",
            });
          }
        }
      } else {
        // Prime the seen-set with the initial batch so we don't toast history.
        for (const n of data) {
          if (!n.read_at) seenToastIds.current.add(n.id);
        }
        primed.current = true;
      }

      setNotifications(data);
      window.dispatchEvent(new CustomEvent(NOTIFICATIONS_UPDATED_EVENT));
    } catch {
      // Non-fatal - polling retries on the next interval.
    }
  }, []);

  useEffect(() => {
    if (activePoller) return;
    activePoller = true;
    // Poll on an interval. The first tick fires immediately via a 0ms timer so
    // the state update happens in a callback (not synchronously in the effect
    // body), then every POLL_INTERVAL_MS thereafter.
    const kickoff = setTimeout(refresh, 0);
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => {
      clearTimeout(kickoff);
      clearInterval(timer);
      activePoller = false;
    };
  }, [refresh]);

  const markRead = useCallback(async (id: string) => {
    // Optimistic update so the indicator clears immediately.
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read_at: n.read_at ?? new Date().toISOString() } : n))
    );
    try {
      await fetch(`/api/notifications/${id}/read`, { method: "POST" });
    } catch {
      // Best-effort; the next poll reconciles server state.
    }
  }, []);

  const remove = useCallback(async (id: string) => {
    // Optimistic removal so the item disappears immediately.
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    try {
      await fetch(`/api/notifications/${id}`, { method: "DELETE" });
    } catch {
      // Best-effort; the next poll reconciles server state.
    }
  }, []);

  const unread = notifications.filter((n) => !n.read_at);

  return { notifications, unread, unreadCount: unread.length, markRead, remove, refresh };
}
