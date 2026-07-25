"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BookOpen,
  Briefcase,
  FileText,
  MessageSquareText,
  Search,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

interface EngagementResult {
  id: string;
  engagement_number: number;
  description: string;
  firm_client_name: string;
  last_question_id: string | null;
}

interface ConversationResult {
  id: string;
  question: string;
  firm_client_name: string | null;
}

interface DocumentResult {
  id: string;
  title: string;
  client_ref: string | null;
}

// One entry point for "find anything" - clients/engagements, past
// conversations, and documents (Library/regulatory content is deliberately
// out of scope for now: that content needs a real backend search index,
// client-side filtering over an already-loaded list doesn't work for a
// 600+ source corpus), plus static navigation, cmdk/Linear-style. Data is
// fetched lazily on first open, not on every page load - this needs to be
// mounted once in the dashboard layout, not per-page.
export function GlobalSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [engagements, setEngagements] = useState<EngagementResult[]>([]);
  const [conversations, setConversations] = useState<ConversationResult[]>([]);
  const [documents, setDocuments] = useState<DocumentResult[]>([]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open || loaded) return;
    // Deferred to a 0ms timer so every state update below happens in a
    // callback, not synchronously in the effect body.
    const t = setTimeout(() => {
      setLoaded(true);
      Promise.all([
        fetch("/api/engagements/directory").then((r) => (r.ok ? r.json() : [])),
        fetch("/api/query").then((r) => (r.ok ? r.json() : [])),
        fetch("/api/documents").then((r) => (r.ok ? r.json() : [])),
      ])
        .then(([engagementRows, queryRows, documentRows]) => {
          setEngagements(engagementRows);
          setConversations(queryRows);
          setDocuments(documentRows);
        })
        .catch(() => {});
    }, 0);
    return () => clearTimeout(t);
  }, [open, loaded]);

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="Search"
      >
        <Search className="size-3.5" />
        <span className="hidden lg:inline">Search…</span>
        <kbd className="hidden shrink-0 rounded border border-border bg-muted px-1 font-mono text-[10px] lg:inline">
          ⌘K
        </kbd>
      </button>

      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder="Search clients, conversations, documents…" />
        <CommandList>
          <CommandEmpty>{loaded ? "Nothing found." : "Loading…"}</CommandEmpty>

          <CommandGroup heading="Go to">
            <CommandItem value="go research ask taxflow" onSelect={() => go("/dashboard/query")}>
              <MessageSquareText />
              Research
            </CommandItem>
            <CommandItem value="go new conversation new question" onSelect={() => go("/dashboard/query?new=1")}>
              <Sparkles />
              New conversation
            </CommandItem>
            <CommandItem value="go workspace clients documents" onSelect={() => go("/dashboard/workspace")}>
              <Briefcase />
              Workspace
            </CommandItem>
            <CommandItem value="go library reference regulatory" onSelect={() => go("/dashboard/library")}>
              <BookOpen />
              Library
            </CommandItem>
            <CommandItem value="go settings" onSelect={() => go("/dashboard/settings")}>
              <Settings />
              Settings
            </CommandItem>
          </CommandGroup>

          {engagements.length > 0 && (
            <CommandGroup heading="Clients & engagements">
              {engagements.map((e) => (
                <CommandItem
                  key={e.id}
                  value={`${e.firm_client_name} ${e.description} engagement`}
                  onSelect={() => go(e.last_question_id ? `/dashboard/query?query=${e.last_question_id}` : "/dashboard/workspace")}
                >
                  <Users />
                  <span className="min-w-0 flex-1 truncate">
                    {e.firm_client_name} <span className="text-muted-foreground">· #{e.engagement_number} {e.description}</span>
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}

          {conversations.length > 0 && (
            <CommandGroup heading="Conversations">
              {conversations.slice(0, 50).map((c) => (
                <CommandItem
                  key={c.id}
                  value={`${c.question} ${c.firm_client_name ?? ""} conversation question`}
                  onSelect={() => go(`/dashboard/query?query=${c.id}`)}
                >
                  <MessageSquareText />
                  <span className="min-w-0 flex-1 truncate">{c.question}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}

          {documents.length > 0 && (
            <CommandGroup heading="Documents">
              {documents.map((d) => (
                <CommandItem
                  key={d.id}
                  value={`${d.title} ${d.client_ref ?? ""} document`}
                  onSelect={() => go(`/dashboard/documents/${d.id}`)}
                >
                  <FileText />
                  <span className="min-w-0 flex-1 truncate">{d.title}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </CommandList>
      </CommandDialog>
    </>
  );
}
