"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertCircle, Briefcase, FileText, MessageSquareText, Pin, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface EngagementSummary {
  id: string;
  engagement_number: number;
  description: string;
  status: string;
  created_at: string;
  query_count: number;
  document_count: number;
  open_comment_count: number;
  pending_re_research_count: number;
  last_activity: string | null;
  last_activity_type: "question" | "document" | "comment" | null;
  needs_attention: boolean;
}

interface ClientSummary {
  firm_client_id: string;
  firm_client_name: string;
  engagements: EngagementSummary[];
  engagement_count: number;
  needs_attention_count: number;
  last_activity: string | null;
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "No activity yet";
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks}w ago`;
  return new Date(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
}

const ACTIVITY_ICON = {
  question: MessageSquareText,
  document: FileText,
  comment: Pin,
} as const;

const ACTIVITY_LABEL = {
  question: "Question asked",
  document: "Document generated",
  comment: "Comment added",
} as const;

// Answers the question a principal actually opens this page to ask: for each
// client, how many engagements are open, what was last done on each, and
// which ones need attention right now (an unresolved comment or a pending
// re-research) - instead of that only being discoverable by opening each
// engagement's history one at a time.
export default function ClientsPage() {
  const [clients, setClients] = useState<ClientSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [attentionOnly, setAttentionOnly] = useState(false);

  useEffect(() => {
    fetch("/api/engagements/directory")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setClients)
      .catch(() => setError("Could not load your client list"));
  }, []);

  const filtered = useMemo(() => {
    if (!clients) return null;
    return clients
      .filter((c) => !attentionOnly || c.needs_attention_count > 0)
      .filter((c) => !search.trim() || c.firm_client_name.toLowerCase().includes(search.trim().toLowerCase()));
  }, [clients, search, attentionOnly]);

  const totals = useMemo(() => {
    if (!clients) return null;
    return {
      clientCount: clients.length,
      engagementCount: clients.reduce((sum, c) => sum + c.engagement_count, 0),
      needsAttention: clients.reduce((sum, c) => sum + c.needs_attention_count, 0),
    };
  }, [clients]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Clients</h1>
        <p className="text-sm text-muted-foreground">
          Every client and their engagements - billing is per-engagement, so this is where to see who
          you&apos;re working for, what&apos;s been done, and what still needs a look.
        </p>
      </div>

      {totals && (
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-muted/30 p-3 text-sm">
          <span className="flex items-center gap-1.5">
            <Users className="size-4 text-muted-foreground" />
            <b>{totals.clientCount}</b> client{totals.clientCount === 1 ? "" : "s"}
          </span>
          <span className="flex items-center gap-1.5">
            <Briefcase className="size-4 text-muted-foreground" />
            <b>{totals.engagementCount}</b> engagement{totals.engagementCount === 1 ? "" : "s"}
          </span>
          {totals.needsAttention > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => setAttentionOnly((v) => !v)}
                  className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium transition-colors ${
                    attentionOnly
                      ? "bg-amber-600 text-white"
                      : "bg-amber-100 text-amber-800 hover:bg-amber-200"
                  }`}
                >
                  <AlertCircle className="size-3.5" />
                  {totals.needsAttention} need{totals.needsAttention === 1 ? "s" : ""} attention
                </button>
              </TooltipTrigger>
              <TooltipContent>
                {attentionOnly ? "Showing only clients with something outstanding - click to show all" : "Click to filter to only clients with an unresolved comment or a pending re-research"}
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      )}

      <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search clients..."
        className="max-w-xs"
      />

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!clients && !error && <p className="text-sm text-muted-foreground">Loading...</p>}

      {clients && clients.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-12 text-center">
          <Users className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No clients yet - clients and engagements are created the first time you select or add one
            from Ask TaxFlow, Workspace, or ATO Correspondence.
          </p>
        </div>
      )}

      {filtered && filtered.length === 0 && clients && clients.length > 0 && (
        <p className="text-sm text-muted-foreground">No clients match this filter.</p>
      )}

      <div className="space-y-3">
        {filtered?.map((client) => (
          <div key={client.firm_client_id} className="rounded-xl border border-border">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/20 px-4 py-3">
              <div className="flex items-center gap-2">
                <p className="font-semibold text-foreground">{client.firm_client_name}</p>
                <Badge variant="outline">
                  {client.engagement_count} engagement{client.engagement_count === 1 ? "" : "s"}
                </Badge>
                {client.needs_attention_count > 0 && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge className="gap-1 border-amber-600/30 bg-amber-100 text-amber-800">
                        <AlertCircle className="size-3" />
                        {client.needs_attention_count} needs attention
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>
                      Has an unresolved comment or a pending re-research on at least one engagement
                    </TooltipContent>
                  </Tooltip>
                )}
              </div>
              <span className="text-xs text-muted-foreground">
                Last activity: {formatRelativeTime(client.last_activity)}
              </span>
            </div>

            <div className="divide-y divide-border">
              {client.engagements.map((engagement) => {
                const ActivityIcon = engagement.last_activity_type
                  ? ACTIVITY_ICON[engagement.last_activity_type]
                  : null;
                return (
                  <Link
                    key={engagement.id}
                    href={`/dashboard/query?engagement_id=${engagement.id}&engagement_number=${engagement.engagement_number}&engagement_description=${encodeURIComponent(engagement.description)}&client_name=${encodeURIComponent(client.firm_client_name)}&firm_client_id=${client.firm_client_id}`}
                    className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-muted/40"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <Briefcase className="size-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">
                          #{engagement.engagement_number} — {engagement.description}
                        </p>
                        <p className="flex items-center gap-3 text-xs text-muted-foreground">
                          <span>{engagement.query_count} question{engagement.query_count === 1 ? "" : "s"}</span>
                          <span>{engagement.document_count} document{engagement.document_count === 1 ? "" : "s"}</span>
                        </p>
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-3">
                      {engagement.needs_attention && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Badge className="gap-1 border-amber-600/30 bg-amber-100 text-amber-800">
                              <AlertCircle className="size-3" />
                              Needs attention
                            </Badge>
                          </TooltipTrigger>
                          <TooltipContent>
                            {engagement.open_comment_count > 0 && engagement.pending_re_research_count > 0
                              ? `${engagement.open_comment_count} unresolved comment(s) and ${engagement.pending_re_research_count} pending re-research`
                              : engagement.open_comment_count > 0
                                ? `${engagement.open_comment_count} unresolved comment${engagement.open_comment_count === 1 ? "" : "s"}`
                                : `${engagement.pending_re_research_count} pending re-research`}
                          </TooltipContent>
                        </Tooltip>
                      )}
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        {ActivityIcon && <ActivityIcon className="size-3.5" />}
                        {engagement.last_activity_type
                          ? `${ACTIVITY_LABEL[engagement.last_activity_type]} · ${formatRelativeTime(engagement.last_activity)}`
                          : "No activity yet"}
                      </span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
