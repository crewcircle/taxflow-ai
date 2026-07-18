"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen, FileText, MessageSquareText } from "lucide-react";

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

export function HeaderStats() {
  const [questionCount, setQuestionCount] = useState(0);
  const [documentCount, setDocumentCount] = useState(0);
  const [knowledgeCount, setKnowledgeCount] = useState(0);

  useEffect(() => {
    fetch("/api/query")
      .then((r) => (r.ok ? r.json() : []))
      .then((d: unknown[]) => setQuestionCount(d.length))
      .catch(() => {});
    fetch("/api/documents")
      .then((r) => (r.ok ? r.json() : []))
      .then((d: unknown[]) => setDocumentCount(d.length))
      .catch(() => {});
    fetch("/api/firm-knowledge")
      .then((r) => (r.ok ? r.json() : []))
      .then((d: unknown[]) => setKnowledgeCount(d.length))
      .catch(() => {});
  }, []);

  return (
    <div className="flex items-center gap-1">
      <StatLink
        href="/dashboard/query?focus=history"
        icon={<MessageSquareText className="size-3.5" />}
        label="Questions asked"
        count={questionCount}
      />
      <StatLink
        href="/dashboard/documents"
        icon={<FileText className="size-3.5" />}
        label="Documents generated"
        count={documentCount}
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
