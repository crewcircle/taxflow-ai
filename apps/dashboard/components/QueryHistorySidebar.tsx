"use client";

import { useEffect, useRef, useState } from "react";
import { Plus, MessageSquare, PanelLeftClose } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ReResearchBadge } from "@/components/ReResearchBadge";
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
}

interface QueryHistorySidebarProps {
  history: QueryListItem[];
  onSelect: (id: string) => void;
  onNewQuestion: () => void;
  onHide: () => void;
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

function groupByRecency(history: QueryListItem[]) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfWeek = new Date(startOfToday);
  startOfWeek.setDate(startOfWeek.getDate() - 7);

  const groups: { label: string; items: QueryListItem[] }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "This week", items: [] },
    { label: "Older", items: [] },
  ];

  for (const item of history) {
    const created = new Date(item.created_at);
    if (created >= startOfToday) groups[0].items.push(item);
    else if (created >= startOfYesterday) groups[1].items.push(item);
    else if (created >= startOfWeek) groups[2].items.push(item);
    else groups[3].items.push(item);
  }

  return groups.filter((g) => g.items.length > 0);
}

export function QueryHistorySidebar({
  history,
  onSelect,
  onNewQuestion,
  onHide,
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
  const groups = groupByRecency(history);
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
              New engagement
            </Button>
          </TooltipTrigger>
          <TooltipContent>Start a fresh conversation - clears the current answer and starts a new session</TooltipContent>
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
        {groups.length === 0 && (
          <p className="p-3 text-xs text-muted-foreground">Your past questions will appear here.</p>
        )}
        {matchedIds && matchedIds.size === 0 && (
          <p className="p-3 text-xs text-muted-foreground">No questions for this client.</p>
        )}
        {groups.map((group) => (
          <div key={group.label} className="mb-4">
            <p className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {group.label}
            </p>
            <div className="space-y-0.5">
              {groupBySession(group.items, sessionLabels).map((row) => {
                if (row.type === "single") {
                  const item = row.item;
                  const isHighlighted = item.id === highlightedId || matchedIds?.has(item.id);
                  const isDimmed = matchedIds !== null && !matchedIds.has(item.id);
                  return (
                    <button
                      key={item.id}
                      ref={(el) => {
                        if (el) itemRefs.current.set(item.id, el);
                        else itemRefs.current.delete(item.id);
                      }}
                      onClick={() => onSelect(item.id)}
                      className={cn(
                        "flex w-full items-start gap-2 rounded-lg border-l-2 border-transparent px-2 py-2 text-left text-sm transition-all",
                        "text-foreground hover:bg-muted",
                        isHighlighted && "border-accent bg-accent/10",
                        isDimmed && "opacity-40"
                      )}
                    >
                      <MessageSquare className="mt-0.5 size-3.5 shrink-0 opacity-60" />
                      <span className="flex-1 space-y-1">
                        <span className="line-clamp-2 block leading-snug">{item.question}</span>
                        {(item.client_ref || item.re_research_status) && (
                          <span className="flex flex-wrap items-center gap-1">
                            {item.client_ref && (
                              <Badge variant="outline" className="text-[9px]">
                                {item.client_ref}
                              </Badge>
                            )}
                            <ReResearchBadge status={item.re_research_status} />
                          </span>
                        )}
                      </span>
                    </button>
                  );
                }

                return (
                  <div key={row.sessionId} className="mb-1">
                    <p className="line-clamp-1 px-2 py-1 text-[11px] font-medium text-muted-foreground">
                      {row.label}
                    </p>
                    <div className="space-y-0.5 border-l border-border pl-2">
                      {row.items.map((item) => {
                        const isHighlighted = item.id === highlightedId || matchedIds?.has(item.id);
                        const isDimmed = matchedIds !== null && !matchedIds.has(item.id);
                        return (
                          <button
                            key={item.id}
                            ref={(el) => {
                              if (el) itemRefs.current.set(item.id, el);
                              else itemRefs.current.delete(item.id);
                            }}
                            onClick={() => onSelect(item.id)}
                            className={cn(
                              "flex w-full items-start gap-2 rounded-lg border-l-2 border-transparent px-2 py-1.5 text-left text-sm transition-all",
                              "text-foreground hover:bg-muted",
                              isHighlighted && "border-accent bg-accent/10",
                              isDimmed && "opacity-40"
                            )}
                          >
                            <MessageSquare className="mt-0.5 size-3.5 shrink-0 opacity-60" />
                            <span className="flex-1 space-y-1">
                              <span className="line-clamp-2 block leading-snug">{item.question}</span>
                              {(item.client_ref || item.re_research_status) && (
                                <span className="flex flex-wrap items-center gap-1">
                                  {item.client_ref && (
                                    <Badge variant="outline" className="text-[9px]">
                                      {item.client_ref}
                                    </Badge>
                                  )}
                                  <ReResearchBadge status={item.re_research_status} />
                                </span>
                              )}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
