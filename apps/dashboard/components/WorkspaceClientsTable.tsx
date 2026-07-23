"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface DirectoryEngagement {
  id: string;
  engagement_number: number;
  description: string;
  status: string;
  created_at: string;
  firm_client_id: string;
  firm_client_name: string;
  query_count: number;
  conversation_count: number;
  document_count: number;
  last_question_at: string | null;
  last_question_id: string | null;
  last_document_at: string | null;
}

interface ClientRow {
  firm_client_id: string;
  firm_client_name: string;
  engagementCount: number;
  conversationCount: number;
  documentCount: number;
  lastActivity: string | null;
  // Whichever engagement was most recently active - "click the count, land
  // on that conversation" needs one concrete query id to deep-link to.
  mostRecentQueryId: string | null;
}

function formatLastActivity(iso: string | null): string {
  if (!iso) return "No activity yet";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(iso).toLocaleDateString("en-AU", { year: "numeric", month: "short", day: "numeric" });
}

function groupByClient(engagements: DirectoryEngagement[]): ClientRow[] {
  const map = new Map<string, DirectoryEngagement[]>();
  for (const e of engagements) {
    const list = map.get(e.firm_client_id) ?? [];
    list.push(e);
    map.set(e.firm_client_id, list);
  }
  const rows: ClientRow[] = [];
  for (const [firm_client_id, list] of map) {
    const mostRecent = [...list].sort((a, b) =>
      (b.last_question_at ?? "").localeCompare(a.last_question_at ?? "")
    )[0];
    const lastActivity = list.reduce<string | null>((acc, e) => {
      const candidate = [e.last_question_at, e.last_document_at].filter(Boolean).sort().pop() ?? null;
      if (!candidate) return acc;
      if (!acc) return candidate;
      return candidate > acc ? candidate : acc;
    }, null);
    rows.push({
      firm_client_id,
      firm_client_name: list[0].firm_client_name,
      engagementCount: list.length,
      conversationCount: list.reduce((sum, e) => sum + e.conversation_count, 0),
      documentCount: list.reduce((sum, e) => sum + e.document_count, 0),
      lastActivity,
      mostRecentQueryId: mostRecent?.last_question_id ?? null,
    });
  }
  rows.sort((a, b) => (b.lastActivity ?? "").localeCompare(a.lastActivity ?? ""));
  return rows;
}

// Clicking an engagement or conversation count deep-links to Ask TaxFlow
// with that client's most recently active conversation already loaded -
// loadConversation there re-selects the matching engagement/conversation in
// the top ConversationBar from the query row itself, so no separate
// engagement/session params are needed here.
function goToConversation(queryId: string | null) {
  if (!queryId) return;
  window.location.href = `/dashboard/query?query=${queryId}`;
}

export function WorkspaceClientsTable() {
  const [engagements, setEngagements] = useState<DirectoryEngagement[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/engagements/directory")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setEngagements)
      .catch(() => setError("Could not load your client list"));
  }, []);

  const rows = useMemo(() => (engagements ? groupByClient(engagements) : null), [engagements]);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!rows) return <p className="text-sm text-muted-foreground">Loading...</p>;
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No clients yet - clients and engagements are created the first time you select or add one from
        Ask TaxFlow, Workspace, or ATO Correspondence.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Client</TableHead>
            <TableHead>Engagements</TableHead>
            <TableHead>Conversations</TableHead>
            <TableHead>Documents generated</TableHead>
            <TableHead>Last activity</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.firm_client_id}>
              <TableCell className="font-medium text-foreground">{row.firm_client_name}</TableCell>
              <TableCell>
                <button
                  type="button"
                  onClick={() => goToConversation(row.mostRecentQueryId)}
                  disabled={!row.mostRecentQueryId}
                  className="text-accent hover:underline disabled:cursor-default disabled:text-muted-foreground disabled:no-underline"
                >
                  {row.engagementCount}
                </button>
              </TableCell>
              <TableCell>
                <button
                  type="button"
                  onClick={() => goToConversation(row.mostRecentQueryId)}
                  disabled={!row.mostRecentQueryId}
                  className="text-accent hover:underline disabled:cursor-default disabled:text-muted-foreground disabled:no-underline"
                >
                  {row.conversationCount}
                </button>
              </TableCell>
              <TableCell className="text-muted-foreground">{row.documentCount}</TableCell>
              <TableCell className="text-muted-foreground">{formatLastActivity(row.lastActivity)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
