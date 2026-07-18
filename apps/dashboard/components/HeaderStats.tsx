"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen, ChevronDown, FileText, MessageSquareText } from "lucide-react";

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
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  count: number;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      {icon}
      <span className="font-semibold text-foreground">{count}</span>
      <span className="hidden sm:inline">{label}</span>
    </Link>
  );
}

interface BreakdownItem {
  label: string;
  count: number;
  href: string;
}

// A per-stat breakdown (tag counts, client counts, ...) shown in a native
// <details> dropdown - no extra dependency, no click-outside JS needed.
function StatDropdown({
  icon,
  label,
  count,
  items,
  allHref,
  tourId,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
  items: BreakdownItem[];
  allHref: string;
  tourId?: string;
}) {
  if (items.length === 0) {
    return <StatLink href={allHref} icon={icon} label={label} count={count} />;
  }

  return (
    <details className="group relative" data-tour={tourId}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&::-webkit-details-marker]:hidden">
        {icon}
        <span className="font-semibold text-foreground">{count}</span>
        <span className="hidden sm:inline">{label}</span>
        <ChevronDown className="size-3 transition-transform group-open:rotate-180" />
      </summary>
      <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-lg border border-border bg-background p-1 shadow-lg">
        <Link
          href={allHref}
          className="flex items-center justify-between rounded-md px-2 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
        >
          <span>All {label.toLowerCase()}</span>
          <span>{count}</span>
        </Link>
        <div className="my-1 border-t border-border" />
        {items.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <span className="truncate">{item.label}</span>
            <span className="font-semibold text-foreground">{item.count}</span>
          </Link>
        ))}
      </div>
    </details>
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
    <div className="flex items-center gap-1">
      <StatDropdown
        icon={<MessageSquareText className="size-3.5" />}
        label="Questions asked"
        count={questionRows.length}
        items={tagItems}
        allHref="/dashboard/query?focus=history"
        tourId="suggested-question"
      />
      <StatDropdown
        icon={<FileText className="size-3.5" />}
        label="Documents generated"
        count={documentRows.length}
        items={clientItems}
        allHref="/dashboard/documents"
      />
      <StatLink
        href="/dashboard/knowledge"
        icon={<BookOpen className="size-3.5" />}
        label="Firm knowledge"
        count={knowledgeCount}
      />
    </div>
  );
}
