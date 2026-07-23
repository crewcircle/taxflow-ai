"use client";

import { useMemo, useState } from "react";
import { MessageSquare, MessagesSquare, PanelLeftClose, Search } from "lucide-react";
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
  firm_client_id?: string | null;
  firm_client_name?: string | null;
}

interface QueryHistorySidebarProps {
  history: QueryListItem[];
  onSelect: (id: string) => void;
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

// A "conversation" row: one or more questions sharing a session_id (or a
// single standalone question with none). Client/engagement attribution is
// now the top bar's job (ConversationBar) - this panel is purely a
// chronological, searchable history, not a second navigation hierarchy.
interface ConversationRow {
  key: string;
  items: QueryListItem[];
  lastActivity: string;
  label: string;
}

function groupIntoConversations(history: QueryListItem[], sessionLabels: Record<string, string>): ConversationRow[] {
  const rows: ConversationRow[] = [];
  const seen = new Set<string>();
  for (const item of history) {
    if (item.session_id) {
      if (seen.has(item.session_id)) continue;
      seen.add(item.session_id);
      const items = history
        .filter((h) => h.session_id === item.session_id)
        .sort((a, b) => b.created_at.localeCompare(a.created_at));
      rows.push({
        key: item.session_id,
        items,
        lastActivity: items[0].created_at,
        label: sessionLabels[item.session_id] ?? items[items.length - 1].question,
      });
      continue;
    }
    rows.push({ key: item.id, items: [item], lastActivity: item.created_at, label: item.question });
  }
  rows.sort((a, b) => b.lastActivity.localeCompare(a.lastActivity));
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

export function QueryHistorySidebar({
  history,
  onSelect,
  onHide,
  onDeleteQuery,
  onDeleteSession,
  highlightedId,
  sessionLabels = {},
}: QueryHistorySidebarProps) {
  const [search, setSearch] = useState("");

  const conversations = useMemo(() => groupIntoConversations(history, sessionLabels), [history, sessionLabels]);

  // One free-text box searches every past question's text (not just a
  // client tag) - a conversation matches if ANY of its turns match, so a
  // hit on an old follow-up still surfaces the whole thread.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) => c.items.some((i) => i.question.toLowerCase().includes(q)));
  }, [conversations, search]);

  return (
    <div className="flex h-full w-72 shrink-0 flex-col border-r border-border">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Conversations
        </span>
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
          <TooltipContent>Hide this panel - click the arrow to bring it back</TooltipContent>
        </Tooltip>
      </div>
      <div className="border-b border-border p-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search all past questions…"
            className="h-8 pl-7 text-xs"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {conversations.length === 0 && (
          <p className="p-3 text-xs text-muted-foreground">Your past conversations will appear here.</p>
        )}
        {conversations.length > 0 && filtered.length === 0 && (
          <p className="p-3 text-xs text-muted-foreground">No questions match &ldquo;{search}&rdquo;.</p>
        )}
        <div className="space-y-1">
          {filtered.map((row) =>
            row.items.length === 1 ? (
              <ItemRow
                key={row.key}
                item={row.items[0]}
                highlightedId={highlightedId}
                onSelect={onSelect}
                onDeleteQuery={onDeleteQuery}
              />
            ) : (
              <ConversationGroup
                key={row.key}
                row={row}
                highlightedId={highlightedId}
                onSelect={onSelect}
                onDeleteQuery={onDeleteQuery}
                onDeleteSession={onDeleteSession}
              />
            )
          )}
        </div>
      </div>
    </div>
  );
}

function ConversationGroup({
  row,
  highlightedId,
  onSelect,
  onDeleteQuery,
  onDeleteSession,
}: {
  row: ConversationRow;
  highlightedId?: string | null;
  onSelect: (id: string) => void;
  onDeleteQuery: (id: string) => void;
  onDeleteSession: (sessionId: string) => void;
}) {
  // Oldest-first turn numbers, since `row.items` is sorted newest-first for
  // display - "#1" should be the question that started the thread.
  const turnNumber = new Map([...row.items].reverse().map((item, i) => [item.id, i + 1]));
  return (
    <div className="mb-1.5">
      <div className="group/qsession flex items-center justify-between gap-1 rounded-t-md bg-muted/60 px-2 py-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <MessagesSquare className="size-3 shrink-0 text-accent" />
          <p className="line-clamp-1 text-[11px] font-medium text-foreground">{row.label}</p>
          <span className="shrink-0 rounded-full bg-accent/15 px-1.5 py-0.5 text-[9px] font-semibold text-accent">
            {row.items.length} turns
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span className="text-[10px] text-muted-foreground">{formatRelativeTime(row.lastActivity)}</span>
          <div className="opacity-0 transition-opacity group-hover/qsession:opacity-100">
            <ResourceRowActions label="conversation" actions={{ delete: () => onDeleteSession(row.key) }} />
          </div>
        </div>
      </div>
      <div className="space-y-0.5 rounded-b-md border-l-2 border-accent/40 bg-accent/[0.03] pl-2">
        {row.items.map((item) => (
          <ItemRow
            key={item.id}
            item={item}
            turnNumber={turnNumber.get(item.id)}
            highlightedId={highlightedId}
            onSelect={onSelect}
            onDeleteQuery={onDeleteQuery}
          />
        ))}
      </div>
    </div>
  );
}

interface ItemRowProps {
  item: QueryListItem;
  // Only set for a row inside a multi-turn thread group - "#2" etc, oldest
  // question first, so it reads as "this is turn 2 of one conversation"
  // rather than a second unrelated question.
  turnNumber?: number;
  highlightedId?: string | null;
  onSelect: (id: string) => void;
  onDeleteQuery: (id: string) => void;
}

// A single past question, shared between the standalone-conversation case and
// the multi-turn-conversation sub-group case.
function ItemRow({ item, turnNumber, highlightedId, onSelect, onDeleteQuery }: ItemRowProps) {
  const isHighlighted = item.id === highlightedId;
  return (
    <div className="group/qrow flex items-start gap-0.5">
      <button
        onClick={() => onSelect(item.id)}
        className={cn(
          "flex min-w-0 flex-1 items-start gap-2 rounded-lg border-l-2 border-transparent px-2 py-1.5 text-left text-sm transition-all",
          "text-foreground hover:bg-muted",
          isHighlighted && "border-accent bg-accent/10"
        )}
      >
        {turnNumber ? (
          <span className="mt-0.5 flex size-3.5 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[9px] font-semibold text-accent">
            {turnNumber}
          </span>
        ) : (
          <MessageSquare className="mt-0.5 size-3.5 shrink-0 opacity-60" />
        )}
        <span className="flex-1 space-y-1">
          <span className="line-clamp-2 block leading-snug">{item.question}</span>
          <span className="flex flex-wrap items-center gap-1.5">
            {item.firm_client_name && (
              <span className="text-[10px] text-muted-foreground">{item.firm_client_name}</span>
            )}
            {!turnNumber && (
              <span className="text-[10px] text-muted-foreground">· {formatRelativeTime(item.created_at)}</span>
            )}
            {item.re_research_status && <ReResearchBadge status={item.re_research_status} />}
          </span>
        </span>
      </button>
      <div className="pt-1 opacity-0 transition-opacity group-hover/qrow:opacity-100">
        <ResourceRowActions label="question" actions={{ delete: () => onDeleteQuery(item.id) }} />
      </div>
    </div>
  );
}
