"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  type ByModelRow,
  formatCount,
  formatLatencySeconds,
  formatUsd,
  hasValue,
} from "./types";

interface ModelBreakdownTableProps {
  rows: ByModelRow[];
  totalVolume: number;
}

// Per-model breakdown table (mirrors the shadcn table used elsewhere). Shows
// share of volume, queries, avg cost, latency and confidence per model.
//
// Note: the /admin/stats contract carries no per-model regression attribution
// (latest_snapshot.metrics is only {overall: {...}}), so this table
// deliberately has no per-model health/"drift" status column - inventing one
// would be misleading. Drift is surfaced at the metric level via the banner
// and flagged KPI cards instead.
export function ModelBreakdownTable({ rows, totalVolume }: ModelBreakdownTableProps) {
  return (
    <div className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10" data-slot="model-table">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Model</TableHead>
            <TableHead className="text-right">Share</TableHead>
            <TableHead className="text-right">Queries</TableHead>
            <TableHead className="text-right">Avg cost</TableHead>
            <TableHead className="text-right">Avg latency</TableHead>
            <TableHead className="text-right">Avg conf.</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => {
            const modelId = row.model_used ?? "unknown";
            const share = totalVolume > 0 ? row.query_volume / totalVolume : null;
            return (
              <TableRow key={`${modelId}-${index}`}>
                <TableCell className="font-mono text-xs">{modelId}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {share === null ? "\u2014" : `${(share * 100).toFixed(0)}%`}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(row.query_volume)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatUsd(row.avg_cost_usd, 3)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatLatencySeconds(row.avg_latency_ms)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {hasValue(row.avg_confidence) ? row.avg_confidence.toFixed(2) : "\u2014"}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
