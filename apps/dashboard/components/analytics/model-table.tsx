"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
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
  // Model ids the drift snapshot attributes the regression to, so their row
  // can be flagged.
  flaggedModels?: string[];
}

// Per-model breakdown table (mirrors the shadcn table used elsewhere). Shows
// share of volume, queries, avg cost, latency and confidence per model, with a
// health badge; a flagged model row gets a destructive tint.
export function ModelBreakdownTable({ rows, totalVolume, flaggedModels = [] }: ModelBreakdownTableProps) {
  const flagged = new Set(flaggedModels.filter(Boolean));
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
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => {
            const modelId = row.model_used ?? "unknown";
            const isFlagged = flagged.has(modelId);
            const share = totalVolume > 0 ? row.query_volume / totalVolume : null;
            return (
              <TableRow
                key={`${modelId}-${index}`}
                className={cn(isFlagged && "bg-destructive/[0.04]")}
                data-flagged={isFlagged || undefined}
              >
                <TableCell className="font-mono text-xs">{modelId}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {share === null ? "\u2014" : `${(share * 100).toFixed(0)}%`}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(row.query_volume)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {hasValue(row.avg_cost_usd) ? formatUsd(row.avg_cost_usd, 3) : "\u2014"}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatLatencySeconds(row.avg_latency_ms)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {hasValue(row.avg_confidence) ? row.avg_confidence.toFixed(2) : "\u2014"}
                </TableCell>
                <TableCell>
                  {isFlagged ? (
                    <Badge variant="destructive" className="gap-1">
                      <ShieldAlert className="size-3" />
                      drift
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="gap-1 border-[#15803d]/30 text-[#15803d]">
                      <ShieldCheck className="size-3" />
                      healthy
                    </Badge>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
