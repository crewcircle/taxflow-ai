"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Copy,
  FileDown,
  Sparkles,
  User,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { QueryHistorySidebar, type QueryListItem } from "@/components/QueryHistorySidebar";
import { SourcesPanel, type SourceCitation } from "@/components/SourcesPanel";
import { AnswerTracePanel, type AnswerTrace } from "@/components/AnswerTracePanel";
import { CollapsedPanelRail } from "@/components/CollapsedPanelRail";
import { cn } from "@/lib/utils";

interface DocumentTemplate {
  type: string;
  label: string;
}

interface VerificationIssue {
  claim: string;
  issue: string;
  severity: "critical" | "warning" | "note";
}

interface Verification {
  overall_status: "verified" | "needs_correction" | "unreliable" | "parse_error";
  issues: VerificationIssue[];
}

interface QueryResult {
  answer: string;
  citations: SourceCitation[];
  model_used: string | null;
  query_id: string | null;
  askedQuestion: string;
}

const MAX_CHARS = 2000;

// react-markdown treats "[1]" as plain text (it isn't valid link syntax on
// its own) - rewrite citation markers into real markdown links pointing at
// the matching source anchor before handing the text to the renderer.
function linkifyCitations(text: string): string {
  return text.replace(/\[(\d+)\]/g, "[[$1]](#source-$1)");
}

const markdownComponents: Components = {
  h1: ({ children }) => <h3 className="mt-4 mb-1.5 text-base font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-4 mb-1.5 text-base font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-3 mb-1 text-sm font-semibold first:mt-0">{children}</h4>,
  p: ({ children }) => <p className="mb-2 text-sm leading-relaxed last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 text-sm">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 text-sm">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 text-xs">{children}</code>,
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border border-border px-2 py-1 text-left font-semibold">{children}</th>,
  td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
  a: ({ href, children }) => (
    <a href={href} className="font-medium text-accent hover:underline">
      {children}
    </a>
  ),
};

function AnswerWithCitationLinks({ text }: { text: string }) {
  return (
    <div>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {linkifyCitations(text)}
      </ReactMarkdown>
    </div>
  );
}

interface FirmKnowledgeSuggestionProps {
  repeatCount: number;
  defaultTitle: string;
  content: string;
}

// Shown after an answer completes when the client has asked essentially the
// same question before (backend-computed repeat_count) - a signal this
// answer is worth keeping as reusable firm guidance rather than re-deriving
// it from scratch next time.
function FirmKnowledgeSuggestion({ repeatCount, defaultTitle, content }: FirmKnowledgeSuggestionProps) {
  const [dismissed, setDismissed] = useState(false);
  const [title, setTitle] = useState(defaultTitle);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (dismissed || repeatCount < 1) return null;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const response = await fetch("/api/firm-knowledge/from-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim() || defaultTitle, content }),
      });
      if (!response.ok) throw new Error("Failed");
      setSaved(true);
    } catch {
      setError("Could not save to Firm Knowledge - please try again");
    } finally {
      setSaving(false);
    }
  }

  if (saved) {
    return (
      <Card className="border-accent/30 bg-accent/5">
        <CardContent className="flex items-center gap-2 py-3 text-sm text-foreground">
          <BookOpen className="size-4 text-accent" />
          Saved to Firm Knowledge.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-accent/30 bg-accent/5">
      <CardContent className="space-y-2 py-3">
        <p className="flex items-center gap-2 text-sm font-medium text-foreground">
          <BookOpen className="size-4 text-accent" />
          You&apos;ve asked something like this {repeatCount === 1 ? "once" : `${repeatCount} times`} before.
        </p>
        <p className="text-sm text-muted-foreground">Save this answer to Firm Knowledge for next time?</p>
        {editing && (
          <Input value={title} onChange={(e) => setTitle(e.target.value)} className="h-8 max-w-md text-sm" />
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="flex flex-wrap gap-2 pt-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="sm" disabled={saving} onClick={handleSave}>
                {saving ? "Saving..." : "Save to Firm Knowledge"}
              </Button>
            </TooltipTrigger>
            <TooltipContent>Saves this answer as reusable firm guidance, so future questions like it can draw on it directly</TooltipContent>
          </Tooltip>
          {!editing && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                  Edit title
                </Button>
              </TooltipTrigger>
              <TooltipContent>Rename this entry before saving - the default title is just the question text</TooltipContent>
            </Tooltip>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" onClick={() => setDismissed(true)}>
                Not now
              </Button>
            </TooltipTrigger>
            <TooltipContent>Dismiss this suggestion - nothing is saved</TooltipContent>
          </Tooltip>
        </div>
      </CardContent>
    </Card>
  );
}

function VerificationBadge({
  verification,
  expanded,
  onToggle,
}: {
  verification: Verification;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (verification.overall_status === "verified") {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className="gap-1 border-green-600/30 text-green-700">
            <CheckCircle2 className="size-3" />
            Verified against sources
          </Badge>
        </TooltipTrigger>
        <TooltipContent>A second pass checked every claim in this answer against the cited sources and found no issues</TooltipContent>
      </Tooltip>
    );
  }
  if (verification.overall_status === "parse_error") return null;

  const critical = verification.issues.filter((i) => i.severity === "critical");
  const label =
    critical.length > 0
      ? `${critical.length} claim${critical.length > 1 ? "s" : ""} need review`
      : `${verification.issues.length} note${verification.issues.length === 1 ? "" : "s"}`;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" onClick={onToggle}>
          <Badge
            variant="outline"
            className="gap-1 border-amber-600/30 bg-amber-50 text-amber-800 hover:bg-amber-100"
          >
            <AlertTriangle className="size-3" />
            {label}
            {expanded ? " (hide details)" : " (click for details)"}
          </Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent>
        {expanded ? "Hide the list of flagged claims" : "Click to see exactly which claims were flagged and why"}
      </TooltipContent>
    </Tooltip>
  );
}

// Explains what "needs review" means: which specific claims were flagged and
// why, so clicking the badge is never a dead end.
function VerificationIssuesPanel({ issues }: { issues: VerificationIssue[] }) {
  return (
    <Card className="border-amber-600/30 bg-amber-50/60">
      <CardContent className="space-y-3 py-3">
        <p className="text-sm font-medium text-amber-900">
          The verification pass checked this answer against the cited sources and flagged the following:
        </p>
        <ul className="space-y-2">
          {issues.map((issue, i) => (
            <li key={i} className="rounded-md border border-amber-600/20 bg-background p-2 text-sm">
              <Badge
                variant="outline"
                className={cn(
                  "mb-1 text-[10px] uppercase",
                  issue.severity === "critical"
                    ? "border-destructive/30 text-destructive"
                    : "border-amber-600/30 text-amber-800"
                )}
              >
                {issue.severity}
              </Badge>
              <p className="font-medium text-foreground">&ldquo;{issue.claim}&rdquo;</p>
              <p className="text-muted-foreground">{issue.issue}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

interface AnswerActionsProps {
  copied: boolean;
  onCopy: () => void;
  savedDocId: string | null;
  savingDoc: boolean;
  docType: string;
  onDocTypeChange: (v: string) => void;
  templates: DocumentTemplate[];
  onSave: () => void;
  clientRef: string;
}

// The three things you can do with a finished answer, grouped so the
// consequence of each is obvious: copy the raw text, or turn it into a
// saved document (which needs a format choice first).
function AnswerActions({
  copied,
  onCopy,
  savedDocId,
  savingDoc,
  docType,
  onDocTypeChange,
  templates,
  onSave,
  clientRef,
}: AnswerActionsProps) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-muted/40 p-3">
      <p className="text-xs font-medium text-muted-foreground">What would you like to do with this answer?</p>
      <div className="flex flex-wrap items-center gap-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="secondary" size="sm" onClick={onCopy}>
              <Copy className="size-3.5" />
              {copied ? "Copied!" : "Copy"}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Copies the plain answer text to your clipboard - handy for pasting into an email or another document
          </TooltipContent>
        </Tooltip>

        <div className="h-6 w-px bg-border" aria-hidden />

        {savedDocId ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button asChild variant="secondary" size="sm">
                <Link href="/dashboard/documents">View saved document →</Link>
              </Button>
            </TooltipTrigger>
            <TooltipContent>Opens the Documents list where this was just saved</TooltipContent>
          </Tooltip>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Select value={docType} onValueChange={onDocTypeChange}>
                  <SelectTrigger size="sm" className="w-[220px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {templates.map((t) => (
                      <SelectItem key={t.type} value={t.type}>
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </TooltipTrigger>
              <TooltipContent>Choose the document style to generate - e.g. an advice memo vs. a client letter</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="secondary" size="sm" disabled={savingDoc} onClick={onSave}>
                  <FileDown className="size-3.5" />
                  {savingDoc ? "Saving..." : "Save as document"}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Saves this answer as a new {templates.find((t) => t.type === docType)?.label.toLowerCase() ?? "document"}{" "}
                under Documents{clientRef.trim() ? `, tagged to ${clientRef.trim()}` : " (no client tagged)"}
              </TooltipContent>
            </Tooltip>
          </div>
        )}
      </div>
    </div>
  );
}

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [clientRef, setClientRef] = useState("");
  // Session memory (Task D3): a UUID minted per conversation and reused across
  // every follow-up so the backend can load prior turns for this session. Reset
  // to a fresh id on "new question" / when loading a different past query, so
  // context never leaks across unrelated conversations.
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [verificationExpanded, setVerificationExpanded] = useState(false);
  const [trace, setTrace] = useState<AnswerTrace | null>(null);
  const [repeatCount, setRepeatCount] = useState(0);
  const [copied, setCopied] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const [historyHighlighted, setHistoryHighlighted] = useState(false);

  const [history, setHistory] = useState<QueryListItem[]>([]);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [docType, setDocType] = useState("advice_memo");
  const [savingDoc, setSavingDoc] = useState(false);
  const [savedDocId, setSavedDocId] = useState<string | null>(null);
  const [highlightedHistoryId, setHighlightedHistoryId] = useState<string | null>(null);

  const hasAutoLoaded = useRef(false);

  const loadHistory = useCallback(() => {
    fetch("/api/query")
      .then((r) => (r.ok ? r.json() : []))
      .then(setHistory)
      .catch(() => {});
  }, []);

  useEffect(loadHistory, [loadHistory]);

  // Header "Questions asked" link deep-links here with ?focus=history so it can
  // open the history sidebar (or just flash it if already open) from any page.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("focus") !== "history") return;
    window.history.replaceState(null, "", window.location.pathname);
    const openTimer = setTimeout(() => {
      setHistoryOpen(true);
      setHistoryHighlighted(true);
    }, 0);
    const clearTimer = setTimeout(() => setHistoryHighlighted(false), 1500);
    return () => {
      clearTimeout(openTimer);
      clearTimeout(clearTimer);
    };
  }, []);

  useEffect(() => {
    fetch("/api/documents/templates")
      .then((r) => (r.ok ? r.json() : []))
      .then(setTemplates)
      .catch(() => {});
  }, []);

  function resetPane() {
    setResult(null);
    setStreamedAnswer("");
    setVerification(null);
    setVerifying(false);
    setVerificationExpanded(false);
    setTrace(null);
    setRepeatCount(0);
    setSavedDocId(null);
    setDocType("advice_memo");
    setError(null);
  }

  // Fetches a past query's full detail (answer + citations + verification)
  // and shows it exactly as it was, so browsing history reads like a real
  // conversation log rather than just a list of question text to re-ask.
  async function loadConversation(item: QueryListItem) {
    resetPane();
    setQuestion("");
    setClientRef(item.client_ref ?? "");
    try {
      const response = await fetch(`/api/query/${item.id}`);
      if (!response.ok) return;
      const data = await response.json();
      setResult({
        answer: data.final_answer ?? "",
        citations: data.citations ?? [],
        model_used: data.model_used,
        query_id: data.id ?? item.id,
        askedQuestion: data.question ?? item.question,
      });
      // Continue the restored conversation: reuse its session_id so a typed
      // follow-up folds into that session's context rather than starting a new
      // one. Fall back to a freshly-minted id if the row predates session_id.
      setSessionId(data.session_id ?? crypto.randomUUID());
      if (data.verification_result?.overall_status) {
        setVerification(data.verification_result);
      }
      if (data.trace) {
        setTrace(data.trace);
      }
    } catch {
      setError("Could not load this question");
    }
  }

  // Session continuity: the first time history loads with content, resume
  // straight into the most recent conversation as if the user never left -
  // unless the header's tag dropdown deep-linked here with ?tag=X, in which
  // case jump to and highlight the newest question carrying that tag instead.
  useEffect(() => {
    if (hasAutoLoaded.current || history.length === 0) return;
    hasAutoLoaded.current = true;

    const tag = new URLSearchParams(window.location.search).get("tag");
    const tagMatch = tag ? history.find((h) => h.topic_tag === tag) : null;
    if (tagMatch) {
      window.history.replaceState(null, "", window.location.pathname);
      const openTimer = setTimeout(() => {
        setHistoryOpen(true);
        setHighlightedHistoryId(tagMatch.id);
        loadConversation(tagMatch);
      }, 0);
      const clearTimer = setTimeout(() => setHighlightedHistoryId(null), 2000);
      return () => {
        clearTimeout(openTimer);
        clearTimeout(clearTimer);
      };
    }

    const t = setTimeout(() => loadConversation(history[0]), 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history]);

  function handleNewQuestion() {
    setQuestion("");
    setClientRef("");
    setSessionId(crypto.randomUUID());
    resetPane();
  }

  // Selecting a past question - from the sidebar or a scenario tag - shows
  // that conversation (answer + sources), same as the auto-loaded most
  // recent one. The ask box is left as-is so the user can type a follow-up.
  function handleSelectHistory(id: string) {
    const item = history.find((h) => h.id === id);
    if (!item) return;
    // loadConversation restores the item's answer/sources AND its session_id, so
    // a follow-up continues that conversation's context (D3 session memory).
    loadConversation(item);
  }

  async function handleSubmit() {
    setLoading(true);
    resetPane();
    // Snapshot the question text now - the textarea stays editable for a
    // follow-up while this streams, and the result must stay tied to what
    // was actually asked, not whatever the box holds when the stream ends.
    const askedQuestion = question;

    try {
      const gate = await fetch("/api/query/stream?question=", { method: "HEAD" }).catch(() => null);
      if (gate && gate.status === 402) {
        window.location.assign("/upgrade");
        return;
      }

      const streamUrl = `/api/query/stream?question=${encodeURIComponent(askedQuestion)}${
        clientRef.trim() ? `&client_ref=${encodeURIComponent(clientRef.trim())}` : ""
      }&session_id=${encodeURIComponent(sessionId)}`;
      const source = new EventSource(streamUrl);
      let answer = "";
      let citations: SourceCitation[] = [];

      await new Promise<void>((resolve, reject) => {
        source.onmessage = (event) => {
          if (event.data === "[DONE]") {
            source.close();
            resolve();
            return;
          }
          const parsed: {
            type: string;
            text?: string;
            citations?: SourceCitation[];
            query_id?: string;
            answer?: string;
            caveat?: string | null;
            model_used?: string | null;
            overall_status?: Verification["overall_status"];
            issues?: VerificationIssue[];
            count?: number;
            retrieval?: AnswerTrace["retrieval"];
            generation?: AnswerTrace["generation"];
            verification?: AnswerTrace["verification"];
            corrective_generation?: AnswerTrace["corrective_generation"];
          } = JSON.parse(event.data);

          if (parsed.type === "token" && parsed.text) {
            answer += parsed.text;
            setStreamedAnswer(answer);
          } else if (parsed.type === "final") {
            citations = parsed.citations ?? [];
            // A cache hit streams the whole answer as one token event, so pick it
            // up here if we didn't accumulate it token-by-token.
            if (!answer && parsed.answer) answer = parsed.answer;
            setResult({
              answer,
              citations,
              model_used: parsed.model_used ?? null,
              query_id: parsed.query_id ?? null,
              askedQuestion,
            });
            setVerifying(true);
          } else if (parsed.type === "correction") {
            // The verify pass produced a caveat or a corrective regeneration
            // replaced the streamed answer. Replace what we displayed so the UI
            // matches the authoritative stored answer (queries.final_answer).
            answer = parsed.answer ?? answer;
            citations = parsed.citations ?? citations;
            setStreamedAnswer(answer);
            setResult((prev) =>
              prev
                ? { ...prev, answer, citations, model_used: parsed.model_used ?? prev.model_used }
                : { answer, citations, model_used: parsed.model_used ?? null, query_id: null, askedQuestion },
            );
          } else if (parsed.type === "verification") {
            setVerifying(false);
            setVerification({
              overall_status: parsed.overall_status ?? "parse_error",
              issues: parsed.issues ?? [],
            });
            loadHistory();
          } else if (parsed.type === "repeat_count") {
            setRepeatCount(parsed.count ?? 0);
          } else if (parsed.type === "trace" && parsed.generation) {
            setTrace({
              retrieval: parsed.retrieval ?? null,
              generation: parsed.generation,
              verification: parsed.verification ?? null,
              corrective_generation: parsed.corrective_generation,
            });
          }
        };
        source.onerror = () => {
          source.close();
          reject(new Error("stream failed"));
        };
      });
    } catch {
      setError("Query failed - please try again");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    if (!result) return;
    await navigator.clipboard.writeText(result.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleSaveAsDocument() {
    if (!result) return;
    setSavingDoc(true);
    try {
      const response = await fetch("/api/documents/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query_id: result.query_id,
          document_type: docType,
          title: result.askedQuestion.slice(0, 80),
          content_md: result.answer,
          client_ref: clientRef.trim() || null,
        }),
      });
      if (!response.ok) throw new Error("Failed");
      const doc = await response.json();
      setSavedDocId(doc.id);
    } catch {
      setError("Could not save as a document - please try again");
    } finally {
      setSavingDoc(false);
    }
  }

  const displayedCitations = result?.citations ?? [];
  const hasBadges = result?.model_used === "sonnet" || verifying || Boolean(verification);

  return (
    <div className="flex h-[calc(100vh-8rem)] min-h-[420px] w-full min-w-0 overflow-hidden rounded-xl border border-border">
      {historyOpen ? (
        <div
          className={
            historyHighlighted ? "ring-2 ring-accent ring-inset transition-shadow duration-300" : "transition-shadow duration-300"
          }
        >
          <QueryHistorySidebar
            history={history}
            onSelect={handleSelectHistory}
            onNewQuestion={handleNewQuestion}
            onHide={() => setHistoryOpen(false)}
            highlightedId={highlightedHistoryId}
          />
        </div>
      ) : (
        <CollapsedPanelRail side="left" label="Show questions" onShow={() => setHistoryOpen(true)} />
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex-1 space-y-4 overflow-y-auto p-6">
          {hasBadges && (
            <div className="flex flex-wrap items-center gap-2">
              {result?.model_used === "sonnet" && (
                <Badge variant="outline" className="gap-1 border-accent/30 text-accent">
                  <Sparkles className="size-3" />
                  Enhanced model
                </Badge>
              )}
              {verifying && (
                <Badge variant="outline" className="text-muted-foreground">
                  Verifying...
                </Badge>
              )}
              {verification && (
                <VerificationBadge
                  verification={verification}
                  expanded={verificationExpanded}
                  onToggle={() => setVerificationExpanded((v) => !v)}
                />
              )}
            </div>
          )}

          {!result && !loading && history.length === 0 && (
            <p className="text-sm text-muted-foreground">Ask a question below to get started.</p>
          )}

          {loading && streamedAnswer && !result && (
            <p className="whitespace-pre-wrap text-sm">{streamedAnswer}</p>
          )}

          {result && (
            <div className="space-y-4">
              {result.askedQuestion && (
                <p className="text-sm text-muted-foreground">
                  <span className="font-medium text-foreground">You asked: </span>
                  {result.askedQuestion}
                </p>
              )}

              {verificationExpanded && verification && verification.issues.length > 0 && (
                <VerificationIssuesPanel issues={verification.issues} />
              )}

              <AnswerWithCitationLinks text={result.answer} />

              {trace && <AnswerTracePanel trace={trace} />}

              <FirmKnowledgeSuggestion
                repeatCount={repeatCount}
                defaultTitle={result.askedQuestion.slice(0, 80) || "Saved answer"}
                content={result.answer}
              />

              <AnswerActions
                copied={copied}
                onCopy={handleCopy}
                savedDocId={savedDocId}
                savingDoc={savingDoc}
                docType={docType}
                onDocTypeChange={setDocType}
                templates={templates}
                onSave={handleSaveAsDocument}
                clientRef={clientRef}
              />
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        {/* Ask TaxFlow input - part of the middle column, below the answer,
            so a follow-up is always right where the conversation is. */}
        <div className="shrink-0 border-t border-border p-4">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="relative mb-2 max-w-xs">
                <User className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={clientRef}
                  onChange={(e) => setClientRef(e.target.value)}
                  placeholder="Client (optional)"
                  className="h-8 border-accent/30 bg-accent/5 pl-7 text-xs"
                />
              </div>
            </TooltipTrigger>
            <TooltipContent>
              Tag this question with a client name - lets you highlight their questions in the history panel later,
              and carries through automatically if you save this answer as a document
            </TooltipContent>
          </Tooltip>
          <Textarea
            data-tour="question-textarea"
            value={question}
            onChange={(e) => setQuestion(e.target.value.slice(0, MAX_CHARS))}
            rows={3}
            placeholder={result ? "Ask a follow-up question..." : "Ask an Australian tax question..."}
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {question.length}/{MAX_CHARS} characters
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button onClick={handleSubmit} disabled={loading || !question.trim()}>
                  {loading ? "Thinking..." : "Ask TaxFlow"}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {result ? "Continues this conversation with your follow-up" : "Runs your question against the AU tax knowledge base"}
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>

      {sourcesOpen ? (
        <SourcesPanel citations={displayedCitations} onHide={() => setSourcesOpen(false)} />
      ) : (
        <CollapsedPanelRail side="right" label="Show sources" onShow={() => setSourcesOpen(true)} />
      )}
    </div>
  );
}
