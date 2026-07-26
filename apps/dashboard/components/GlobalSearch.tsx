"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BookOpen,
  Briefcase,
  FileText,
  MessageSquareText,
  Scale,
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

interface FirmKnowledgeResult {
  id: string;
  file_name: string;
}

interface RegulatoryAlertResult {
  id: string;
  title: string;
  source: string;
}

// One entry point for "find anything" - clients/engagements, past
// conversations, documents, and now the Library (the firm's own uploaded
// precedents + the regulatory alert feed). Client-side filtering over an
// already-loaded list doesn't scale to the full published reference corpus
// (600+ sources), so THAT stays out of scope - but firm_knowledge and
// regulatory_alerts are both small, already-fetched-in-full lists (same
// shape as engagements/conversations/documents below), so there's no reason
// for Library to be the one content type this box silently excludes.
// Static navigation, cmdk/Linear-style. Data is fetched lazily on first
// open, not on every page load - this needs to be mounted once in the
// dashboard layout, not per-page.
export function GlobalSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [engagements, setEngagements] = useState<EngagementResult[]>([]);
  const [conversations, setConversations] = useState<ConversationResult[]>([]);
  const [documents, setDocuments] = useState<DocumentResult[]>([]);
  const [firmKnowledge, setFirmKnowledge] = useState<FirmKnowledgeResult[]>([]);
  const [regulatoryAlerts, setRegulatoryAlerts] = useState<RegulatoryAlertResult[]>([]);

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
        fetch("/api/firm-knowledge").then((r) => (r.ok ? r.json() : [])),
        fetch("/api/regulatory-alerts").then((r) => (r.ok ? r.json() : [])),
      ])
        .then(([engagementRows, queryRows, documentRows, firmKnowledgeRows, alertRows]) => {
          setEngagements(engagementRows);
          setConversations(queryRows);
          setDocuments(documentRows);
          setFirmKnowledge(firmKnowledgeRows);
          setRegulatoryAlerts(alertRows);
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
        <CommandInput placeholder="Search clients, conversations, documents, library…" />
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

          {firmKnowledge.length > 0 && (
            <CommandGroup heading="Library — your firm's precedents">
              {firmKnowledge.map((k) => (
                <CommandItem
                  key={k.id}
                  value={`${k.file_name} library precedent knowledge`}
                  onSelect={() => go("/dashboard/library")}
                >
                  <BookOpen />
                  <span className="min-w-0 flex-1 truncate">{k.file_name}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}

          {regulatoryAlerts.length > 0 && (
            <CommandGroup heading="Library — regulatory updates">
              {regulatoryAlerts.map((a) => (
                <CommandItem
                  key={a.id}
                  value={`${a.title} ${a.source} regulatory library`}
                  onSelect={() => go("/dashboard/library?tab=reference")}
                >
                  <Scale />
                  <span className="min-w-0 flex-1 truncate">{a.title}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </CommandList>
      </CommandDialog>
    </>
  );
}
