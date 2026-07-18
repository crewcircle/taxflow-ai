"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen, FileText, MessageSquareText } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface QueryRow {
  topic_tag: string | null;
}

interface DocumentRow {
  client_ref: string | null;
}

function StatLink({
  href,
  icon,
  label,
  count,
  tooltip,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  count: number;
  tooltip: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          href={href}
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {icon}
          <span className="font-semibold text-foreground">{count}</span>
          <span className="hidden sm:inline">{label}</span>
        </Link>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

interface BreakdownItem {
  label: string;
  count: number;
  href: string;
}

const MAX_PILLS = 3;

// Top-N breakdown shown as directly-clickable pills next to a stat, instead
// of a dropdown that hides the options behind an extra click.
function StatPills({ items, tourId }: { items: BreakdownItem[]; tourId?: string }) {
  if (items.length === 0) return null;
  return (
    <div className="flex items-center gap-1" data-tour={tourId}>
      {items.slice(0, MAX_PILLS).map((item) => (
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
          <TooltipContent>Jump to questions/documents for &ldquo;{item.label}&rdquo;</TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}

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
  const [documentRows, setDocumentRows] = useState<DocumentRow[]>([]);
  const [knowledgeCount, setKnowledgeCount] = useState(0);

  useEffect(() => {
    fetch("/api/query")
      .then((r) => (r.ok ? r.json() : []))
      .then(setQuestionRows)
      .catch(() => {});
    fetch("/api/documents")
      .then((r) => (r.ok ? r.json() : []))
      .then(setDocumentRows)
      .catch(() => {});
    fetch("/api/firm-knowledge")
      .then((r) => (r.ok ? r.json() : []))
      .then((d: unknown[]) => setKnowledgeCount(d.length))
      .catch(() => {});
  }, []);

  const tagItems = countBy(questionRows, (r) => r.topic_tag).map((item) => ({
    ...item,
    href: `/dashboard/query?focus=history&tag=${encodeURIComponent(item.label)}`,
  }));
  const clientItems = countBy(documentRows, (r) => r.client_ref).map((item) => ({
    ...item,
    href: `/dashboard/documents?client=${encodeURIComponent(item.label)}`,
  }));

  return (
    <div className="flex flex-wrap items-center gap-1">
      <StatLink
        href="/dashboard/query?focus=history"
        icon={<MessageSquareText className="size-3.5" />}
        label="Questions asked"
        count={questionRows.length}
        tooltip="Opens the question history panel on the Ask TaxFlow screen"
      />
      <StatPills items={tagItems} tourId="suggested-question" />

      <div className="mx-1 h-4 w-px bg-border" aria-hidden />

      <StatLink
        href="/dashboard/documents"
        icon={<FileText className="size-3.5" />}
        label="Documents generated"
        count={documentRows.length}
        tooltip="Opens the full list of generated documents"
      />
      <StatPills items={clientItems} />

      <div className="mx-1 h-4 w-px bg-border" aria-hidden />

      <StatLink
        href="/dashboard/knowledge"
        icon={<BookOpen className="size-3.5" />}
        label="Firm knowledge"
        count={knowledgeCount}
        tooltip="Opens your firm's saved precedents and guidance"
      />
    </div>
  );
}
