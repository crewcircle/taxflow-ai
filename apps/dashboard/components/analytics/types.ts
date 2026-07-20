// Shape of the backend /admin/stats response, proxied verbatim through
// app/api/admin/stats/route.ts. Every rate is a 0..1 fraction; cost/citation
// fields can be null when the backend migration 035 columns aren't present
// yet, so the UI must degrade gracefully.

export interface VerificationBreakdownRow {
  overall_status: string;
  count: number;
}

export interface ByModelRow {
  model_used: string | null;
  query_volume: number;
  avg_latency_ms: number | null;
  avg_confidence: number | null;
  avg_cost_usd?: number | null;
}

export interface ByDayRow {
  day: string | null;
  query_volume: number;
  avg_latency_ms: number | null;
  avg_cost_usd?: number | null;
}

export interface SnapshotDiff {
  deltas: Record<string, number>;
  regressions: string[];
  has_regressions: boolean;
}

export interface DriftSnapshot {
  id: string;
  window_start: string | null;
  window_end: string | null;
  baseline_start: string | null;
  baseline_end: string | null;
  metrics: { overall?: Record<string, number | null> } & Record<string, unknown>;
  diff: SnapshotDiff;
  has_regressions: boolean;
  created_at: string;
}

export interface OpsNotification {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  metadata: Record<string, unknown> | null;
  severity: string | null;
  read_at: string | null;
  created_at: string;
}

export interface AdminStats {
  query_volume: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  total_cost_usd: number | null;
  avg_cost_usd: number | null;
  avg_confidence: number | null;
  citation_validity_rate: number | null;
  feedback_up: number;
  feedback_down: number;
  feedback_up_rate: number | null;
  feedback_down_rate: number | null;
  verification_failure_rate: number | null;
  verification_breakdown: VerificationBreakdownRow[];
  by_model: ByModelRow[];
  by_day: ByDayRow[];
  latest_snapshot: DriftSnapshot | null;
  has_regressions: boolean;
  snapshots: DriftSnapshot[];
  ops_notifications: OpsNotification[];
}

export type AnalyticsWindow = "7d" | "30d" | "90d" | "12m";

// Human-readable labels for the metric keys the backend uses in
// latest_snapshot.diff.regressions, so the drift banner can name them.
export const METRIC_LABELS: Record<string, string> = {
  feedback_down_rate: "Feedback-down rate",
  feedback_up_rate: "Feedback-up rate",
  verification_failure_rate: "Verification-failure rate",
  citation_validity_rate: "Citation-validity rate",
  avg_confidence: "Average confidence",
  avg_latency_ms: "Average latency",
  p95_latency_ms: "p95 latency",
  avg_cost_usd: "Average cost",
  total_cost_usd: "Total cost",
  quality_per_dollar: "Quality per dollar",
};

export function metricLabel(key: string): string {
  return (
    METRIC_LABELS[key] ??
    key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
}

// "—" for null so a missing metric never renders as NaN or crashes.
const EM_DASH = "\u2014";

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EM_DASH;
  return value.toLocaleString("en-AU");
}

// Rates are 0..1 fractions - render as a percentage with one decimal.
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EM_DASH;
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatLatencySeconds(ms: number | null | undefined, digits = 1): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return EM_DASH;
  return `${(ms / 1000).toFixed(digits)}s`;
}

export function formatUsd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EM_DASH;
  return `$${value.toFixed(digits)}`;
}

export function hasValue(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && !Number.isNaN(value);
}
