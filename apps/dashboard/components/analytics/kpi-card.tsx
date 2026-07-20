"use client";

import type { LucideIcon } from "lucide-react";
import { ShieldAlert, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Sparkline, type TrendPoint } from "./charts";

interface KpiCardProps {
  label: string;
  icon: LucideIcon;
  // Pre-formatted value string (already handles the "—" null case).
  value: string;
  unit?: string;
  // Optional inline sparkline series.
  spark?: TrendPoint[];
  // A regressed metric gets a destructive ring, a "Flagged" badge and a red spark.
  flagged?: boolean;
  // A "good" metric (higher/lower is healthy) tints its sparkline green.
  positiveSpark?: boolean;
  // Optional footer: a directional delta + a baseline reference caption.
  delta?: { text: string; tone: "good" | "bad" | "warn" | "flat" } | null;
  baselineCaption?: string | null;
}

const DELTA_TONE: Record<string, string> = {
  good: "text-[#15803d]",
  bad: "text-destructive",
  warn: "text-[#b45309]",
  flat: "text-muted-foreground",
};

export function KpiCard({
  label,
  icon: Icon,
  value,
  unit,
  spark,
  flagged = false,
  positiveSpark = false,
  delta,
  baselineCaption,
}: KpiCardProps) {
  const DeltaIcon = delta?.tone === "bad" || delta?.text.trim().startsWith("-") ? TrendingDown : TrendingUp;
  return (
    <div
      className={cn(
        "rounded-xl bg-card px-4 py-3.5 ring-1 ring-foreground/10",
        flagged && "bg-destructive/[0.04] ring-[1.5px] ring-destructive/30"
      )}
      data-slot="kpi-card"
      data-flagged={flagged || undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Icon className="size-3.5" />
          {label}
        </span>
        {flagged && (
          <Badge variant="destructive" className="gap-1">
            <ShieldAlert className="size-3" />
            Flagged
          </Badge>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1 text-2xl font-semibold tracking-tight tabular-nums">
        {value}
        {unit && <span className="text-[13px] font-medium text-muted-foreground">{unit}</span>}
      </div>
      {delta && (
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <span className={cn("flex items-center gap-1 text-xs font-semibold", DELTA_TONE[delta.tone])}>
            <DeltaIcon className="size-3" />
            {delta.text}
          </span>
          {baselineCaption && <span className="text-[11px] text-muted-foreground">{baselineCaption}</span>}
        </div>
      )}
      {spark && spark.length > 0 && (
        <div className="mt-1.5">
          <Sparkline points={spark} regressed={flagged} positive={positiveSpark} />
        </div>
      )}
    </div>
  );
}

// The skeleton KPI card used in the collecting-data / loading state.
export function KpiCardSkeleton({ label, icon: Icon }: { label: string; icon: LucideIcon }) {
  return (
    <div className="rounded-xl bg-card px-4 py-3.5 opacity-55 ring-1 ring-foreground/10" data-slot="kpi-skeleton">
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Icon className="size-3.5" />
        {label}
      </span>
      <div className="mt-2 h-6 w-3/5 rounded-md bg-muted" />
      <div className="mt-2.5 h-10 rounded-md bg-muted" />
    </div>
  );
}
