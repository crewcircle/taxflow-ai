"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MessageSquareText } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface QueryRow {
  topic_tag: string | null;
}

interface BreakdownItem {
  label: string;
  count: number;
  href: string;
}

const MAX_PILLS = 3;

function countBy<T>(rows: T[], getKey: (row: T) => string | null): BreakdownItem[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const key = getKey(row);
    if (!key) continue;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([label, count]) => ({ label, count, href: "" }));
}

export function HeaderStats() {
  const [questionRows, setQuestionRows] = useState<QueryRow[]>([]);

  useEffect(() => {
    fetch("/api/query")
      .then((r) => (r.ok ? r.json() : []))
      .then(setQuestionRows)
      .catch(() => {});
  }, []);

  const tagItems = countBy(questionRows, (r) => r.topic_tag).map((item) => ({
    ...item,
    href: `/dashboard/query?focus=history&tag=${encodeURIComponent(item.label)}`,
  }));

  return (
    <div className="flex flex-wrap items-center gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <Link
            href="/dashboard/query?focus=history"
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <MessageSquareText className="size-3.5" />
            <span className="font-semibold text-foreground">{questionRows.length}</span>
            <span className="hidden sm:inline">Questions asked</span>
          </Link>
        </TooltipTrigger>
        <TooltipContent>Opens the question history panel on the Ask TaxFlow screen</TooltipContent>
      </Tooltip>

      {tagItems.length > 0 && (
        <div className="flex items-center gap-1" data-tour="suggested-question">
          {tagItems.slice(0, MAX_PILLS).map((item) => (
            <Tooltip key={item.label}>
              <TooltipTrigger asChild>
                <Link
                  href={item.href}
                  className="flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:border-accent hover:text-accent"
                >
                  <span className="max-w-24 truncate">{item.label}</span>
                  <span className="font-semibold">{item.count}</span>
                </Link>
              </TooltipTrigger>
              <TooltipContent>Jump to questions tagged &ldquo;{item.label}&rdquo;</TooltipContent>
            </Tooltip>
          ))}
        </div>
      )}
    </div>
  );
}
