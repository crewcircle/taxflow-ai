"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

interface AlertRow {
  id: string;
  detected_at: string;
}

// Individual rulings/decisions used to be listed here one-by-one, but that
// duplicated the "Documents" and citation surfaces where a ruling actually
// matters to a specific answer - all a reader needs on the library landing
// page is confidence that the feed is live: how often it's checked, and when
// it last ran.
export default function RegulatoryPage() {
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch("/api/regulatory-alerts")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((alerts: AlertRow[]) => {
        const latest = alerts.reduce<string | null>((max, a) => {
          if (!a.detected_at) return max;
          return !max || a.detected_at > max ? a.detected_at : max;
        }, null);
        setLastRefreshed(latest);
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm">
      <RefreshCw className="size-4 shrink-0 text-muted-foreground" />
      <p className="text-muted-foreground">
        Regulatory feed checked every 2 hours
        {loaded && lastRefreshed && (
          <>
            {" · "}Last refreshed{" "}
            {new Date(lastRefreshed).toLocaleString("en-AU", {
              day: "numeric",
              month: "short",
              hour: "numeric",
              minute: "2-digit",
            })}
          </>
        )}
        {loaded && !lastRefreshed && <>{" · "}No updates detected yet</>}
      </p>
    </div>
  );
}
