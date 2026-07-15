"use client";

import { useState } from "react";
import { Plus, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
  created_at: string;
}

interface QueryHistorySidebarProps {
  history: QueryListItem[];
  onSelect: (id: string) => void;
  onNewQuestion: () => void;
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
}: QueryHistorySidebarProps) {
  const [clientFilter, setClientFilter] = useState("");
  const filtered = clientFilter.trim()
    ? history.filter((h) => h.client_ref?.toLowerCase().includes(clientFilter.trim().toLowerCase()))
    : history;
  const groups = groupByRecency(filtered);
  const hasAnyClientRef = history.some((h) => h.client_ref);

  return (
    <div className="flex h-full w-56 shrink-0 flex-col border-r border-border">
      <div className="space-y-2 border-b border-border p-3">
        <Button size="sm" className="w-full gap-1.5" onClick={onNewQuestion}>
          <Plus className="size-4" />
          New question
        </Button>
        {hasAnyClientRef && (
          <Input
            value={clientFilter}
            onChange={(e) => setClientFilter(e.target.value)}
            placeholder="Filter by client..."
            className="h-8 text-xs"
          />
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {groups.length === 0 && (
          <p className="p-3 text-xs text-muted-foreground">
            {clientFilter.trim() ? "No questions for this client." : "Your past questions will appear here."}
          </p>
        )}
        {groups.map((group) => (
          <div key={group.label} className="mb-4">
            <p className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {group.label}
            </p>
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => onSelect(item.id)}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-sm transition-colors",
                    "text-foreground hover:bg-muted"
                  )}
                >
                  <MessageSquare className="mt-0.5 size-3.5 shrink-0 opacity-60" />
                  <span className="flex-1 space-y-1">
                    <span className="line-clamp-2 block leading-snug">{item.question}</span>
                    {item.client_ref && (
                      <Badge variant="outline" className="text-[9px]">
                        {item.client_ref}
                      </Badge>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
