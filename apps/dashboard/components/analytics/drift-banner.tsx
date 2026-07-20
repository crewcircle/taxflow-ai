"use client";

import { AlertTriangle, ShieldAlert } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { type DriftSnapshot, metricLabel } from "./types";

interface DriftBannerProps {
  snapshot: DriftSnapshot;
}

function formatFlaggedAt(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("en-AU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// A signed delta caption for a regressed metric key, read from the snapshot's
// diff.deltas. Rate metrics render as percentage points; everything else as a
// raw signed number so the banner never shows a bare NaN.
function formatDelta(key: string, delta: number | undefined): string | null {
  if (delta === undefined || Number.isNaN(delta)) return null;
  const sign = delta > 0 ? "+" : "";
  if (key.endsWith("_rate")) {
    return `${sign}${(delta * 100).toFixed(1)}pp`;
  }
  return `${sign}${delta.toFixed(2)}`;
}

// The on-brand destructive drift banner. Rendered ONLY when has_regressions is
// true; names each regressed metric from latest_snapshot.diff.regressions with
// its delta against the trailing baseline.
export function DriftBanner({ snapshot }: DriftBannerProps) {
  const regressions = snapshot.diff?.regressions ?? [];
  const deltas = snapshot.diff?.deltas ?? {};
  const flaggedAt = formatFlaggedAt(snapshot.created_at);

  return (
    <Alert
      variant="destructive"
      role="alert"
      className="border-destructive/35 bg-muted p-4"
      data-slot="drift-banner"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <ShieldAlert className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="text-[15px] font-semibold text-foreground">
              Model-performance drift detected
            </span>
            <Badge variant="destructive" className="gap-1">
              <AlertTriangle className="size-3" />
              {regressions.length} metric{regressions.length === 1 ? "" : "s"} regressed
            </Badge>
            {flaggedAt && (
              <Badge variant="outline" className="font-normal">
                flagged {flaggedAt}
              </Badge>
            )}
          </div>
          <p className="mt-1.5 text-[13px] text-foreground/90">
            A scheduled drift check flagged a regression against the trailing baseline. Review the
            affected metrics below and consider routing or pinning answers while this is investigated.
          </p>
          {regressions.length > 0 && (
            <div className="mt-3.5 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
              {regressions.map((key) => {
                const delta = formatDelta(key, deltas[key]);
                return (
                  <div
                    key={key}
                    className="rounded-[10px] bg-card p-3 ring-1 ring-foreground/10"
                    data-slot="drift-regression"
                  >
                    <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                      <AlertTriangle className="size-3 text-destructive" />
                      {metricLabel(key)}
                    </div>
                    {delta && (
                      <div className="mt-1.5 text-[19px] font-semibold text-destructive tabular-nums">
                        {delta}
                      </div>
                    )}
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      vs trailing baseline
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </Alert>
  );
}
