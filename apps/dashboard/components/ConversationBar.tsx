"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Briefcase, Check, MessagesSquare, Plus, Search, User } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import type { Engagement, EngagementSelection } from "@/components/EngagementPicker";
import type { QueryListItem } from "@/components/QueryHistorySidebar";
import { cn } from "@/lib/utils";

interface FirmClient {
  id: string;
  name: string;
}

interface FirmClientSuggestion {
  id: string | null;
  name: string;
  registered: boolean;
}

interface ConversationInfo {
  sessionId: string;
  label: string;
  latestQueryId: string;
  turnCount: number;
}

function defaultDescription(): string {
  return `General tax research — ${new Date().toISOString().slice(0, 10)}`;
}

// Derives the list of conversations under one engagement straight from the
// already-fetched query history - a "conversation" is just a session_id, and
// the backend already carries engagement_id per query row, so there's no
// separate endpoint to call here.
function conversationsForEngagement(history: QueryListItem[], engagementId: string): ConversationInfo[] {
  const items = history.filter((h) => h.engagement_id === engagementId);
  const bySession = new Map<string, QueryListItem[]>();
  for (const item of items) {
    const key = item.session_id ?? item.id;
    const list = bySession.get(key) ?? [];
    list.push(item);
    bySession.set(key, list);
  }
  const rows: ConversationInfo[] = [];
  for (const [sessionId, sessionItems] of bySession) {
    const sorted = [...sessionItems].sort((a, b) => b.created_at.localeCompare(a.created_at));
    rows.push({
      sessionId,
      label: sorted[sorted.length - 1].question,
      latestQueryId: sorted[0].id,
      turnCount: sorted.length,
    });
  }
  return rows;
}

// A single inline segment: a chip button that, when clicked, opens a
// search-and-pick panel beneath it. Closes on outside click or Escape.
function BarSegment({
  icon: Icon,
  label,
  value,
  placeholder,
  disabled,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | null;
  placeholder: string;
  disabled?: boolean;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative min-w-0 flex-1">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors",
          value ? "border-border bg-muted/40 hover:bg-muted/60" : "border-dashed border-accent/40 bg-accent/5 hover:bg-accent/10",
          disabled && "cursor-not-allowed opacity-60"
        )}
      >
        <Icon className={cn("size-4 shrink-0", value ? "text-muted-foreground" : "text-accent")} />
        <span className="min-w-0 flex-1">
          <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            {label}
          </span>
          <span className={cn("block truncate text-sm font-medium", value ? "text-foreground" : "text-accent")}>
            {value ?? placeholder}
          </span>
        </span>
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-80 rounded-lg border border-border bg-popover p-2 text-popover-foreground shadow-lg">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function ConversationBar({
  value,
  onChangeEngagement,
  history,
  currentSessionId,
  onSelectConversation,
  onNewConversation,
  disabled,
}: {
  value: EngagementSelection | null;
  onChangeEngagement: (selection: EngagementSelection | null) => void;
  history: QueryListItem[];
  currentSessionId: string;
  onSelectConversation: (queryId: string) => void;
  onNewConversation: () => void;
  disabled?: boolean;
}) {
  // --- client segment ---------------------------------------------------
  const [clientQuery, setClientQuery] = useState("");
  const [clientSuggestions, setClientSuggestions] = useState<FirmClientSuggestion[]>([]);
  const [creatingClient, setCreatingClient] = useState(false);

  useEffect(() => {
    const handle = setTimeout(() => {
      const search = clientQuery.trim();
      fetch(`/api/firm-clients${search ? `?search=${encodeURIComponent(search)}` : ""}`)
        .then((r) => (r.ok ? r.json() : []))
        .then((rows: FirmClientSuggestion[]) => setClientSuggestions(Array.isArray(rows) ? rows : []))
        .catch(() => setClientSuggestions([]));
    }, 200);
    return () => clearTimeout(handle);
  }, [clientQuery]);

  async function resolveClient(name: string): Promise<FirmClient> {
    const response = await fetch("/api/firm-clients", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!response.ok) throw new Error("Failed");
    return response.json();
  }

  async function selectClient(client: FirmClient, close: () => void) {
    onChangeEngagement(null);
    setPendingClient(client);
    close();
  }

  async function selectClientSuggestion(suggestion: FirmClientSuggestion, close: () => void) {
    if (suggestion.registered && suggestion.id) {
      await selectClient({ id: suggestion.id, name: suggestion.name }, close);
      return;
    }
    setCreatingClient(true);
    try {
      const resolved = await resolveClient(suggestion.name);
      await selectClient(resolved, close);
    } finally {
      setCreatingClient(false);
    }
  }

  // The client chosen so far this "pick a new engagement" flow - separate
  // from `value` (the committed selection) so switching clients doesn't
  // commit until an engagement is actually chosen underneath it.
  const [pendingClient, setPendingClient] = useState<FirmClient | null>(
    value ? { id: value.engagement.firm_client_id, name: value.clientName } : null
  );
  useEffect(() => {
    if (value) setPendingClient({ id: value.engagement.firm_client_id, name: value.clientName });
  }, [value]);

  // --- engagement segment -------------------------------------------------
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loadingEngagements, setLoadingEngagements] = useState(false);
  const [newEngagementDescription, setNewEngagementDescription] = useState("");
  const [creatingEngagement, setCreatingEngagement] = useState(false);
  const [showNewEngagementForm, setShowNewEngagementForm] = useState(false);

  const loadEngagements = useCallback((firmClientId: string) => {
    setLoadingEngagements(true);
    fetch(`/api/engagements?firm_client_id=${encodeURIComponent(firmClientId)}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: Engagement[]) => setEngagements(Array.isArray(rows) ? rows : []))
      .catch(() => setEngagements([]))
      .finally(() => setLoadingEngagements(false));
  }, []);

  useEffect(() => {
    if (!pendingClient) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setEngagements([]);
      return;
    }
    // Deferred to a 0ms timer so the state updates inside loadEngagements
    // happen in a callback, not synchronously in the effect body.
    const t = setTimeout(() => loadEngagements(pendingClient.id), 0);
    return () => clearTimeout(t);
  }, [pendingClient, loadEngagements]);

  function selectEngagement(engagement: Engagement, close: () => void) {
    if (!pendingClient) return;
    onChangeEngagement({ engagement, clientName: pendingClient.name });
    onNewConversation();
    close();
  }

  async function createEngagement(close: () => void) {
    if (!pendingClient) return;
    setCreatingEngagement(true);
    try {
      const body = {
        firm_client_id: pendingClient.id,
        description: newEngagementDescription.trim() === "" ? undefined : newEngagementDescription,
      };
      const response = await fetch("/api/engagements", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error("Failed");
      const created: Engagement = await response.json();
      onChangeEngagement({ engagement: created, clientName: pendingClient.name });
      onNewConversation();
      setNewEngagementDescription("");
      setShowNewEngagementForm(false);
      close();
    } catch {
      // Non-fatal - the form just stays open for a retry.
    } finally {
      setCreatingEngagement(false);
    }
  }

  // --- conversation segment ------------------------------------------------
  const [conversationFilter, setConversationFilter] = useState("");
  const conversations = value ? conversationsForEngagement(history, value.engagement.id) : [];
  const filteredConversations = conversationFilter.trim()
    ? conversations.filter((c) => c.label.toLowerCase().includes(conversationFilter.trim().toLowerCase()))
    : conversations;
  const currentConversation = conversations.find((c) => c.sessionId === currentSessionId) ?? null;

  const typedClient = clientQuery.trim();
  const hasExactClientMatch = clientSuggestions.some((c) => c.name.toLowerCase() === typedClient.toLowerCase());
  const showCreateClientRow = typedClient.length > 0 && !hasExactClientMatch;

  return (
    <div className="flex flex-wrap items-stretch gap-2">
      <BarSegment icon={User} label="Client" value={value?.clientName ?? null} placeholder="Choose client" disabled={disabled}>
        {(close) => (
          <div className="space-y-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                autoFocus
                value={clientQuery}
                onChange={(e) => setClientQuery(e.target.value)}
                placeholder="Search clients or type a new name…"
                className="h-8 pl-7 text-sm"
                autoComplete="off"
              />
            </div>
            <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-md border border-border">
              {clientSuggestions.map((c) => (
                <li key={c.id ?? c.name}>
                  <button
                    type="button"
                    disabled={creatingClient}
                    onClick={() => selectClientSuggestion(c, close)}
                    className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-muted"
                  >
                    <User className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{c.name}</span>
                  </button>
                </li>
              ))}
              {showCreateClientRow && (
                <li>
                  <button
                    type="button"
                    disabled={creatingClient}
                    onClick={async () => {
                      setCreatingClient(true);
                      try {
                        const created = await resolveClient(typedClient);
                        await selectClient(created, close);
                      } finally {
                        setCreatingClient(false);
                      }
                    }}
                    className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm text-accent hover:bg-muted"
                  >
                    <Plus className="size-3.5 shrink-0" />
                    {creatingClient ? "Creating…" : `Create new client "${typedClient}"`}
                  </button>
                </li>
              )}
              {clientSuggestions.length === 0 && !showCreateClientRow && (
                <li className="px-2.5 py-2 text-xs text-muted-foreground">Start typing to search or add a client.</li>
              )}
            </ul>
          </div>
        )}
      </BarSegment>

      <BarSegment
        icon={Briefcase}
        label="Engagement"
        value={value ? `#${value.engagement.engagement_number} — ${value.engagement.description}` : null}
        placeholder={pendingClient ? "Choose engagement" : "Pick a client first"}
        disabled={disabled || !pendingClient}
      >
        {(close) => (
          <div className="space-y-2">
            <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-md border border-border">
              {loadingEngagements && <li className="px-2.5 py-2 text-xs text-muted-foreground">Loading…</li>}
              {!loadingEngagements &&
                engagements.map((e) => (
                  <li key={e.id}>
                    <button
                      type="button"
                      onClick={() => selectEngagement(e, close)}
                      className={cn(
                        "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-muted",
                        value?.engagement.id === e.id && "bg-accent/10"
                      )}
                    >
                      <Briefcase className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate">
                        #{e.engagement_number} · {e.description}
                      </span>
                      {value?.engagement.id === e.id && <Check className="size-3.5 shrink-0 text-accent" />}
                    </button>
                  </li>
                ))}
            </ul>
            {showNewEngagementForm ? (
              <div className="space-y-1.5 rounded-md border border-border p-2">
                <Label htmlFor="cb_new_engagement" className="text-xs">
                  Description (optional)
                </Label>
                <Textarea
                  id="cb_new_engagement"
                  value={newEngagementDescription}
                  onChange={(e) => setNewEngagementDescription(e.target.value)}
                  rows={2}
                  placeholder={defaultDescription()}
                  className="text-xs"
                />
                <div className="flex justify-end gap-2">
                  <Button type="button" size="sm" variant="ghost" onClick={() => setShowNewEngagementForm(false)}>
                    Cancel
                  </Button>
                  <Button type="button" size="sm" disabled={creatingEngagement} onClick={() => createEngagement(close)}>
                    {creatingEngagement ? "Creating…" : "Create"}
                  </Button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowNewEngagementForm(true)}
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-accent hover:bg-muted"
              >
                <Plus className="size-3.5 shrink-0" />
                New engagement
              </button>
            )}
          </div>
        )}
      </BarSegment>

      <BarSegment
        icon={MessagesSquare}
        label="Conversation"
        value={currentConversation ? currentConversation.label.slice(0, 60) : value ? "New conversation" : null}
        placeholder={value ? "New conversation" : "Pick an engagement first"}
        disabled={disabled || !value}
      >
        {(close) => (
          <div className="space-y-2">
            {conversations.length > 3 && (
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  autoFocus
                  value={conversationFilter}
                  onChange={(e) => setConversationFilter(e.target.value)}
                  placeholder="Search this engagement's conversations…"
                  className="h-8 pl-7 text-sm"
                  autoComplete="off"
                />
              </div>
            )}
            <button
              type="button"
              onClick={() => {
                onNewConversation();
                close();
              }}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-accent hover:bg-muted"
            >
              <Plus className="size-3.5 shrink-0" />
              New conversation
            </button>
            <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-md border border-border">
              {filteredConversations
                .sort((a, b) => (a.sessionId === currentSessionId ? -1 : b.sessionId === currentSessionId ? 1 : 0))
                .map((c) => (
                  <li key={c.sessionId}>
                    <button
                      type="button"
                      onClick={() => {
                        onSelectConversation(c.latestQueryId);
                        close();
                      }}
                      className={cn(
                        "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-muted",
                        c.sessionId === currentSessionId && "bg-accent/10"
                      )}
                    >
                      <MessagesSquare className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate">{c.label}</span>
                      <span className="shrink-0 text-[10px] text-muted-foreground">{c.turnCount}t</span>
                      {c.sessionId === currentSessionId && <Check className="size-3.5 shrink-0 text-accent" />}
                    </button>
                  </li>
                ))}
              {filteredConversations.length === 0 && (
                <li className="px-2.5 py-2 text-xs text-muted-foreground">No conversations yet in this engagement.</li>
              )}
            </ul>
          </div>
        )}
      </BarSegment>
    </div>
  );
}
