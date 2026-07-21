"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { Plus, MessageSquare, PanelLeftClose } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ReResearchBadge } from "@/components/ReResearchBadge";
import { ResourceRowActions } from "@/components/resource-actions/ResourceRowActions";
import { cn } from "@/lib/utils";

export interface QueryListItem {
  id: string;
  question: string;
  status: string;
  model_used: string | null;
  confidence_score: number | null;
  verification_result: { overall_status?: string } | null;
  client_ref: string | null;
  context_note: string | null;
  topic_tag: string | null;
  session_id: string | null;
  re_research_status?: string | null;
  created_at: string;
  engagement_id?: string | null;
  engagement_number?: number | null;
  engagement_description?: string | null;
  firm_client_name?: string | null;
}

interface QueryHistorySidebarProps {
  history: QueryListItem[];
  onSelect: (id: string) => void;
  onNewQuestion: () => void;
  onHide: () => void;
  // Delete a single past question.
  onDeleteQuery: (id: string) => void;
  // Delete an entire multi-turn engagement (session) at once.
  onDeleteSession: (sessionId: string) => void;
  // Set briefly (e.g. from a topic-tag click) to scroll to and highlight one
  // specific item without hiding the rest of the list.
  highlightedId?: string | null;
  // session_id -> label, for sessions the user has renamed. Sessions with no
  // entry here fall back to their first question's text.
  sessionLabels?: Record<string, string>;
}

type HistoryRow =
  | { type: "single"; item: QueryListItem }
  | { type: "session"; sessionId: string; label: string; items: QueryListItem[] };

// Multi-turn sessions (same session_id on more than one question) render as
// one sub-group under their label; single-turn sessions render exactly as
// before, so the common case has no visual change.
function groupBySession(items: QueryListItem[], sessionLabels: Record<string, string>): HistoryRow[] {
  const rows: HistoryRow[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    if (item.session_id) {
      if (seen.has(item.session_id)) continue;
      const sessionItems = items.filter((i) => i.session_id === item.session_id);
      if (sessionItems.length > 1) {
        seen.add(item.session_id);
        rows.push({
          type: "session",
          sessionId: item.session_id,
          label: sessionLabels[item.session_id] ?? sessionItems[sessionItems.length - 1].question,
          items: sessionItems,
        });
        continue;
      }
    }
    rows.push({ type: "single", item });
  }
  return rows;
}

function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks}w ago`;
  return new Date(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

interface EngagementGroup {
  key: string;
  label: string;
  lastActivity: string;
  items: QueryListItem[];
}

interface ClientGroup {
  key: string;
  clientName: string;
  lastActivity: string;
  engagements: EngagementGroup[];
}

// Billing is per-engagement, so the sidebar's primary hierarchy is client ->
// engagement (most recently active first) instead of raw date buckets -
// "which engagement is this question part of" should be answerable by
// scanning down the list, not by opening each one.
function groupByClientEngagement(history: QueryListItem[]): ClientGroup[] {
  const clientMap = new Map<string, Map<string, QueryListItem[]>>();
  for (const item of history) {
    const clientKey = item.firm_client_name ?? "__unassigned__";
    const engagementKey = item.engagement_id ?? "__none__";
    if (!clientMap.has(clientKey)) clientMap.set(clientKey, new Map());
    const engagementMap = clientMap.get(clientKey)!;
    if (!engagementMap.has(engagementKey)) engagementMap.set(engagementKey, []);
    engagementMap.get(engagementKey)!.push(item);
  }

  const clientGroups: ClientGroup[] = [];
  for (const [clientKey, engagementMap] of clientMap) {
    const engagements: EngagementGroup[] = [];
    for (const [engagementKey, items] of engagementMap) {
      const sorted = [...items].sort((a, b) => b.created_at.localeCompare(a.created_at));
      const first = sorted[0];
      engagements.push({
        key: engagementKey,
        label:
          engagementKey === "__none__"
            ? "Unattributed"
            : `#${first.engagement_number} · ${first.engagement_description}`,
        lastActivity: sorted[0].created_at,
        items: sorted,
      });
    }
    engagements.sort((a, b) => b.lastActivity.localeCompare(a.lastActivity));
    clientGroups.push({
      key: clientKey,
      clientName: clientKey === "__unassigned__" ? "Unassigned" : clientKey,
      lastActivity: engagements[0]?.lastActivity ?? "",
      engagements,
    });
  }
  clientGroups.sort((a, b) => b.lastActivity.localeCompare(a.lastActivity));
  return clientGroups;
}

export function QueryHistorySidebar({
  history,
  onSelect,
  onNewQuestion,
  onHide,
  onDeleteQuery,
  onDeleteSession,
  highlightedId,
  sessionLabels = {},
}: QueryHistorySidebarProps) {
  const [clientFilter, setClientFilter] = useState("");
  // Highlight matches instead of hiding non-matches, so filtering by client
  // never makes the rest of the question history disappear.
  const matchedIds = clientFilter.trim()
    ? new Set(
        history
          .filter((h) => h.client_ref?.toLowerCase().includes(clientFilter.trim().toLowerCase()))
          .map((h) => h.id)
      )
    : null;
  const clientGroups = groupByClientEngagement(history);
  const hasAnyClientRef = history.some((h) => h.client_ref);

  const itemRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    if (!highlightedId) return;
    itemRefs.current.get(highlightedId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlightedId]);

  return (
    <div className="flex h-full w-56 shrink-0 flex-col border-r border-border">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Questions</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onHide}
              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Hide questions"
            >
              <PanelLeftClose className="size-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Hide this panel to give the answer more room - click the arrow to bring it back</TooltipContent>
        </Tooltip>
      </div>
      <div className="space-y-2 border-b border-border p-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="sm" className="w-full gap-1.5" onClick={onNewQuestion}>
              <Plus className="size-4" />
              New question
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Start a fresh conversation thread - clears the current answer. You can attach it to the same or a
            different engagement above.
          </TooltipContent>
        </Tooltip>
        {hasAnyClientRef && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Input
                value={clientFilter}
                onChange={(e) => setClientFilter(e.target.value)}
                placeholder="Highlight by client..."
                className="h-8 text-xs"
              />
            </TooltipTrigger>
            <TooltipContent>Type a client name to highlight their questions below - the rest stay visible, just dimmed</TooltipContent>
          </Tooltip>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {clientGroups.length === 0 && (
          <p className="p-3 text-xs text-muted-foreground">Your past questions will appear here.</p>
        )}
        {matchedIds && matchedIds.size === 0 && (
          <p className="p-3 text-xs text-muted-foreground">No questions for this client.</p>
        )}
        {clientGroups.map((client) => (
          <div key={client.key} className="mb-4">
            <div className="mb-1 flex items-center justify-between px-2">
              <p className="truncate text-xs font-semibold text-foreground">{client.clientName}</p>
              <span className="shrink-0 text-[10px] text-muted-foreground">
                {formatRelativeTime(client.lastActivity)}
              </span>
            </div>
            <div className="space-y-2">
              {client.engagements.map((engagementGroup) => (
                <div key={engagementGroup.key} className="border-l-2 border-border/70 pl-2">
                  <div className="mb-0.5 flex items-center justify-between gap-1 px-1">
                    <p className="line-clamp-1 text-[11px] font-medium text-muted-foreground">
                      {engagementGroup.label}
                    </p>
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {formatRelativeTime(engagementGroup.lastActivity)}
                    </span>
                  </div>
                  <div className="space-y-0.5">
                    {groupBySession(engagementGroup.items, sessionLabels).map((row) => {
                      if (row.type === "single") {
                        return (
                          <ItemRow
                            key={row.item.id}
                            item={row.item}
                            highlightedId={highlightedId}
                            matchedIds={matchedIds}
                            itemRefs={itemRefs}
                            onSelect={onSelect}
                            onDeleteQuery={onDeleteQuery}
                          />
                        );
                      }
                      return (
                        <div key={row.sessionId} className="mb-1">
                          <div className="group/qsession flex items-center justify-between gap-1">
                            <p className="line-clamp-1 px-2 py-1 text-[11px] font-medium text-muted-foreground">
                              {row.label}
                            </p>
                            <div className="opacity-0 transition-opacity group-hover/qsession:opacity-100">
                              <ResourceRowActions
                                label="conversation"
                                actions={{ delete: () => onDeleteSession(row.sessionId) }}
                              />
                            </div>
                          </div>
                          <div className="space-y-0.5 border-l border-border pl-2">
                            {row.items.map((item) => (
                              <ItemRow
                                key={item.id}
                                item={item}
                                highlightedId={highlightedId}
                                matchedIds={matchedIds}
                                itemRefs={itemRefs}
                                onSelect={onSelect}
                                onDeleteQuery={onDeleteQuery}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface ItemRowProps {
  item: QueryListItem;
  highlightedId?: string | null;
  matchedIds: Set<string> | null;
  itemRefs: RefObject<Map<string, HTMLButtonElement>>;
  onSelect: (id: string) => void;
  onDeleteQuery: (id: string) => void;
}

// A single past question, shared between the direct-under-engagement case and
// the multi-turn-conversation sub-group case.
function ItemRow({ item, highlightedId, matchedIds, itemRefs, onSelect, onDeleteQuery }: ItemRowProps) {
  const isHighlighted = item.id === highlightedId || matchedIds?.has(item.id);
  const isDimmed = matchedIds !== null && !matchedIds.has(item.id);
  return (
    <div className="group/qrow flex items-start gap-0.5">
      <button
        ref={(el) => {
          if (el) itemRefs.current.set(item.id, el);
          else itemRefs.current.delete(item.id);
        }}
        onClick={() => onSelect(item.id)}
        className={cn(
          "flex min-w-0 flex-1 items-start gap-2 rounded-lg border-l-2 border-transparent px-2 py-1.5 text-left text-sm transition-all",
          "text-foreground hover:bg-muted",
          isHighlighted && "border-accent bg-accent/10",
          isDimmed && "opacity-40"
        )}
      >
        <MessageSquare className="mt-0.5 size-3.5 shrink-0 opacity-60" />
        <span className="flex-1 space-y-1">
          <span className="line-clamp-2 block leading-snug">{item.question}</span>
          {item.re_research_status && (
            <span className="flex flex-wrap items-center gap-1">
              <ReResearchBadge status={item.re_research_status} />
            </span>
          )}
        </span>
      </button>
      <div className="pt-1 opacity-0 transition-opacity group-hover/qrow:opacity-100">
        <ResourceRowActions label="question" actions={{ delete: () => onDeleteQuery(item.id) }} />
      </div>
    </div>
  );
}
