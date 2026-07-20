"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  CircleDollarSign,
  Info,
  LineChart,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  ThumbsDown,
  Timer,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DriftBanner } from "@/components/analytics/drift-banner";
import { KpiCard, KpiCardSkeleton } from "@/components/analytics/kpi-card";
import { ModelBreakdownTable } from "@/components/analytics/model-table";
import { TrendChart, type TrendPoint } from "@/components/analytics/charts";
import {
  type AdminStats,
  type AnalyticsWindow,
  formatCount,
  formatLatencySeconds,
  formatPercent,
  formatUsd,
  hasValue,
} from "@/components/analytics/types";

const WINDOWS: AnalyticsWindow[] = ["7d", "30d", "90d", "12m"];

// The minimum by_day points before trends/tables are considered meaningful;
// below this the page shows the collecting-data empty state instead.
const MIN_TREND_DAYS = 2;

function toTrendPoints(
  rows: AdminStats["by_day"],
  pick: (row: AdminStats["by_day"][number]) => number | null
): TrendPoint[] {
  return rows.map((row) => ({
    label: row.day ?? "",
    value: pick(row),
  }));
}

export default function AnalyticsPage() {
  const [window, setWindow] = useState<AnalyticsWindow>("30d");
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Bumped by the refresh button to re-trigger the fetch effect without
  // changing the window.
  const [reloadKey, setReloadKey] = useState(0);

  // Fetch on window change or explicit refresh. All setState happens inside the
  // fetch promise callbacks (never synchronously in the effect body), so the
  // effect only synchronizes with the external /admin/stats endpoint.
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    fetch(`/api/admin/stats?window=${window}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Request failed (${response.status})`);
        return response.json() as Promise<AdminStats>;
      })
      .then((data) => {
        if (!active) return;
        setStats(data);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active || (err instanceof DOMException && err.name === "AbortError")) return;
        setError("Could not load analytics - please try again.");
        setStats(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [window, reloadKey]);

  function selectWindow(selected: AnalyticsWindow) {
    if (selected === window) return;
    setLoading(true);
    setWindow(selected);
  }

  function refresh() {
    setLoading(true);
    setReloadKey((key) => key + 1);
  }

  const byDay = stats?.by_day ?? [];
  const hasData = byDay.length >= MIN_TREND_DAYS && (stats?.query_volume ?? 0) > 0;
  const hasRegressions = Boolean(stats?.has_regressions && stats?.latest_snapshot);
  const regressedKeys = useMemo(
    () => new Set(stats?.latest_snapshot?.diff?.regressions ?? []),
    [stats]
  );

  // Models the drift snapshot attributes the regression to (from snapshot
  // metadata if present), used to flag the offending table row.
  const flaggedModels = useMemo<string[]>(() => {
    const meta = stats?.latest_snapshot?.metrics as Record<string, unknown> | undefined;
    const raw = meta?.regressed_models ?? meta?.flagged_models;
    return Array.isArray(raw) ? (raw.filter((m) => typeof m === "string") as string[]) : [];
  }, [stats]);

  const volumeSpark = toTrendPoints(byDay, (r) => r.query_volume);
  const costSpark = toTrendPoints(byDay, (r) => r.avg_cost_usd ?? null);
  const latencySpark = toTrendPoints(byDay, (r) => r.avg_latency_ms);

  return (
    <div className="mx-auto max-w-[1120px]">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2.5 text-xl font-semibold tracking-tight">
            Pipeline analytics
            {!loading && !error && (
              hasRegressions ? (
                <Badge variant="destructive" className="gap-1">
                  <ShieldCheck className="size-3" />
                  Drift detected
                </Badge>
              ) : hasData ? (
                <Badge variant="outline" className="gap-1 border-[#15803d]/30 text-[#15803d]">
                  <ShieldCheck className="size-3" />
                  Healthy
                </Badge>
              ) : (
                <Badge variant="secondary">Collecting data</Badge>
              )
            )}
          </h1>
          <p className="mt-0.5 max-w-[640px] text-sm text-muted-foreground">
            Monitor the health of the AI research pipeline over time and catch model-performance
            drift. Aggregates across all firm queries.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="inline-flex h-8 overflow-hidden rounded-lg border border-border">
            {WINDOWS.map((w, index) => (
              <button
                key={w}
                type="button"
                onClick={() => selectWindow(w)}
                className={cn(
                  "px-3 text-[13px] font-medium text-muted-foreground",
                  index > 0 && "border-l border-border",
                  w === window && "bg-muted text-foreground"
                )}
                aria-pressed={w === window}
              >
                {w}
              </button>
            ))}
          </div>
          <Button variant="outline" onClick={refresh} disabled={loading}>
            <RefreshCw className={cn("size-4", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-border bg-card p-6 text-sm text-destructive">
          {error}
        </div>
      )}

      {!error && (hasRegressions && stats?.latest_snapshot) && (
        <div className="mb-5">
          <DriftBanner snapshot={stats.latest_snapshot} />
        </div>
      )}

      {/* KPI row - skeletons while loading, real cards once data lands. */}
      <div className="mb-5 grid grid-cols-2 gap-3.5 md:grid-cols-3">
        {loading || !stats ? (
          <>
            <KpiCardSkeleton label="Query volume" icon={MessageSquareText} />
            <KpiCardSkeleton label="Total cost" icon={CircleDollarSign} />
            <KpiCardSkeleton label="p95 latency" icon={Timer} />
            <KpiCardSkeleton label="Feedback-down rate" icon={ThumbsDown} />
            <KpiCardSkeleton label="Verification-failure rate" icon={ShieldCheck} />
            <KpiCardSkeleton label="Citation-validity rate" icon={ShieldCheck} />
          </>
        ) : (
          <>
            <KpiCard
              label="Query volume"
              icon={MessageSquareText}
              value={formatCount(stats.query_volume)}
              spark={volumeSpark}
            />
            <KpiCard
              label="Total cost"
              icon={CircleDollarSign}
              value={hasValue(stats.total_cost_usd) ? formatUsd(stats.total_cost_usd) : "\u2014"}
              baselineCaption={
                hasValue(stats.avg_cost_usd) ? `avg ${formatUsd(stats.avg_cost_usd, 3)}/query` : "Not available yet"
              }
              spark={costSpark}
            />
            <KpiCard
              label="p95 latency"
              icon={Timer}
              value={formatLatencySeconds(stats.p95_latency_ms)}
              spark={latencySpark}
            />
            <KpiCard
              label="Feedback-down rate"
              icon={ThumbsDown}
              value={formatPercent(stats.feedback_down_rate)}
              flagged={regressedKeys.has("feedback_down_rate")}
              positiveSpark
            />
            <KpiCard
              label="Verification-failure rate"
              icon={ShieldCheck}
              value={formatPercent(stats.verification_failure_rate)}
              flagged={regressedKeys.has("verification_failure_rate")}
            />
            <KpiCard
              label="Citation-validity rate"
              icon={ShieldCheck}
              value={hasValue(stats.citation_validity_rate) ? formatPercent(stats.citation_validity_rate) : "\u2014"}
              flagged={regressedKeys.has("citation_validity_rate")}
              positiveSpark
            />
          </>
        )}
      </div>

      {/* Trends + quality/drift trend line, or the collecting-data empty state. */}
      <section className="mb-5">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Trends
          </span>
        </div>

        {loading || !stats ? (
          <div className="grid gap-3.5 lg:grid-cols-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-[220px] rounded-xl bg-card opacity-55 ring-1 ring-foreground/10" />
            ))}
          </div>
        ) : !hasData ? (
          <EmptyState volume={stats.query_volume} days={byDay.length} />
        ) : (
          <div className="grid gap-3.5 lg:grid-cols-2">
            <TrendChart
              title="Query volume"
              subtitle="Answered research queries / day"
              points={volumeSpark}
              currentValue={formatCount(byDay.at(-1)?.query_volume ?? null)}
              unit="/day"
            />
            <TrendChart
              title="Cost"
              subtitle="Average model spend / query / day"
              points={costSpark}
              currentValue={formatUsd(byDay.at(-1)?.avg_cost_usd ?? null, 3)}
              unit="/query"
            />
            <TrendChart
              title="p95 latency"
              subtitle="95th-percentile response time"
              points={latencySpark}
              currentValue={formatLatencySeconds(stats.p95_latency_ms)}
            />
            <QualityTrendChart stats={stats} />
          </div>
        )}
      </section>

      {/* Per-model breakdown. */}
      {!loading && stats && hasData && stats.by_model.length > 0 && (
        <section className="mb-5">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Breakdown by model
            </span>
            <span className="text-[11px] text-muted-foreground">Per-model quality and cost</span>
          </div>
          <ModelBreakdownTable
            rows={stats.by_model}
            totalVolume={stats.query_volume}
            flaggedModels={flaggedModels}
          />
        </section>
      )}
    </div>
  );
}

// A quality/drift trend line derived from the drift snapshots history. Each
// snapshot carries an overall verification-failure rate; we plot it oldest ->
// newest so a rising line reads as degrading quality. Falls back to the daily
// latency series if no snapshots exist yet.
function QualityTrendChart({ stats }: { stats: AdminStats }) {
  const snapshots = [...(stats.snapshots ?? [])].reverse();

  if (snapshots.length >= MIN_TREND_DAYS) {
    const points: TrendPoint[] = snapshots.map((snap) => {
      const overall = snap.metrics?.overall ?? {};
      const value =
        (overall.verification_failure_rate as number | null | undefined) ??
        (overall.feedback_down_rate as number | null | undefined) ??
        null;
      return { label: snap.created_at, value: hasValue(value) ? value : null };
    });
    const latest = points.at(-1)?.value ?? null;
    return (
      <TrendChart
        title="Quality drift"
        subtitle="Verification-failure rate across drift snapshots"
        points={points}
        currentValue={hasValue(latest) ? formatPercent(latest) : "\u2014"}
        regressed={stats.has_regressions}
        driftWindowFraction={stats.has_regressions ? 0.25 : null}
      />
    );
  }

  return (
    <TrendChart
      title="Verification-failure rate"
      subtitle="Answers flagged needs-correction / unreliable"
      points={toTrendPoints(stats.by_day, () => stats.verification_failure_rate)}
      currentValue={formatPercent(stats.verification_failure_rate)}
      regressed={stats.has_regressions}
    />
  );
}

function EmptyState({ volume, days }: { volume: number; days: number }) {
  return (
    <div
      className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-6 py-14 text-center"
      data-slot="analytics-empty"
    >
      <LineChart className="mb-3.5 size-11 text-muted-foreground" />
      <h2 className="text-base font-semibold">Not enough data yet</h2>
      <p className="mt-1.5 max-w-[420px] text-[13px] text-muted-foreground">
        Analytics and drift detection need at least <strong>7 days</strong> of query activity. Your
        firm has run <strong>{formatCount(volume)} queries over {days} day{days === 1 ? "" : "s"}</strong>{" "}
        so far — trends and the baseline comparison will unlock once a full baseline window is available.
      </p>
      <div className="mt-4 flex gap-2">
        <Button asChild>
          <Link href="/dashboard/query">
            <MessageSquareText className="size-4" />
            Ask TaxFlow a question
          </Link>
        </Button>
        <Button variant="outline" disabled>
          <Info className="size-4" />
          How drift detection works
        </Button>
      </div>
    </div>
  );
}
