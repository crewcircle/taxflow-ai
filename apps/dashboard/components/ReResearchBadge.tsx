"use client";

import { Loader2, Sparkles, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// Inline status for a feedback-triggered async re-research (C7). The value is
// set by the backend when a thumbs-down-with-note enqueues a re-research job:
// - "pending": job queued/running
// - "done":    re-researched answer is ready ("Answer improved")
// - "failed":  the re-research exhausted its retries
export function ReResearchBadge({
  status,
  className,
}: {
  status?: string | null;
  className?: string;
}) {
  if (status === "pending") {
    return (
      <Badge variant="secondary" className={cn("gap-1 text-[10px]", className)}>
        <Loader2 className="size-3 animate-spin" />
        Re-researching…
      </Badge>
    );
  }
  if (status === "done") {
    return (
      <Badge
        variant="outline"
        className={cn("gap-1 border-emerald-500/40 text-emerald-600 dark:text-emerald-400 text-[10px]", className)}
      >
        <Sparkles className="size-3" />
        Answer improved
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="destructive" className={cn("gap-1 text-[10px]", className)}>
        <AlertTriangle className="size-3" />
        Re-research failed
      </Badge>
    );
  }
  return null;
}
