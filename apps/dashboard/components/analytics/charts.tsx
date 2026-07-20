"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface TrendPoint {
  label: string;
  value: number | null;
}

interface TrendChartProps {
  title: string;
  subtitle: string;
  points: TrendPoint[];
  // The current headline value shown top-right of the card.
  currentValue: string;
  unit?: string;
  // A trailing-baseline dashed reference line (chart y-units), if known.
  baseline?: number | null;
  // Render the metric in destructive red (regressed) rather than neutral gray.
  regressed?: boolean;
  // Fraction (0..1) of the x-axis, from the right, to shade as the drift window.
  driftWindowFraction?: number | null;
}

// A single time-series trend card built with recharts. Healthy metrics use the
// neutral --chart-2 gray; a regressed metric switches to --destructive with a
// shaded drift window and a red baseline marker, matching the drift mockups.
export function TrendChart({
  title,
  subtitle,
  points,
  currentValue,
  unit,
  baseline,
  regressed = false,
  driftWindowFraction,
}: TrendChartProps) {
  const stroke = regressed ? "var(--destructive)" : "var(--chart-2)";
  const fillId = regressed ? "trendFillDrift" : "trendFillHealthy";
  const fillColor = regressed ? "var(--destructive)" : "var(--chart-2)";

  const driftStartIndex =
    driftWindowFraction && points.length > 1
      ? Math.max(0, Math.floor(points.length * (1 - driftWindowFraction)))
      : null;

  return (
    <Card className="gap-3" data-slot="trend-chart">
      <CardContent className="space-y-2.5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-foreground">{title}</div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">{subtitle}</div>
          </div>
          <div className="text-right text-lg font-semibold tabular-nums">
            {currentValue}
            {unit && <span className="ml-0.5 text-[11px] font-medium text-muted-foreground">{unit}</span>}
          </div>
        </div>
        <div className="h-[168px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={fillColor} stopOpacity={0.16} />
                  <stop offset="100%" stopColor={fillColor} stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--border)" strokeOpacity={0.5} vertical={false} />
              <XAxis dataKey="label" hide />
              <YAxis hide domain={["auto", "auto"]} />
              <Tooltip
                cursor={{ stroke: "var(--border)" }}
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelStyle={{ color: "var(--muted-foreground)" }}
              />
              {driftStartIndex !== null && points[driftStartIndex] && (
                <ReferenceArea
                  x1={points[driftStartIndex].label}
                  x2={points[points.length - 1].label}
                  fill="var(--destructive)"
                  fillOpacity={0.08}
                  stroke="var(--destructive)"
                  strokeOpacity={0.4}
                  strokeDasharray="3 3"
                />
              )}
              {typeof baseline === "number" && (
                <ReferenceLine
                  y={baseline}
                  stroke={regressed ? "var(--destructive)" : "var(--muted-foreground)"}
                  strokeDasharray="4 4"
                  strokeOpacity={0.55}
                />
              )}
              <Area
                type="monotone"
                dataKey="value"
                stroke={stroke}
                strokeWidth={2}
                fill={`url(#${fillId})`}
                dot={false}
                activeDot={{ r: 3, fill: stroke }}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={stroke}
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

interface SparklineProps {
  points: TrendPoint[];
  regressed?: boolean;
  positive?: boolean;
  className?: string;
}

// The small inline trend inside a KPI card. Green when the metric is a
// "good" one (positive=true, e.g. citation validity), destructive when the
// metric has regressed, otherwise neutral gray.
export function Sparkline({ points, regressed = false, positive = false, className }: SparklineProps) {
  // Healthy "good" metrics (citation validity, low feedback-down) trend green;
  // #15803d matches the mockup's --green token. Neutral metrics use --chart-2.
  const stroke = regressed
    ? "var(--destructive)"
    : positive
      ? "#15803d"
      : "var(--chart-2)";
  return (
    <div className={cn("h-10 w-full", className)} data-slot="sparkline">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.18} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={1.6}
            fill="url(#sparkFill)"
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
