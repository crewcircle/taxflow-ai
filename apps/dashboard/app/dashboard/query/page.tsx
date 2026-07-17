"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { QueryHistorySidebar, type QueryListItem } from "@/components/QueryHistorySidebar";
import { SourcesPanel, type SourceCitation } from "@/components/SourcesPanel";

interface DocumentTemplate {
  type: string;
  label: string;
}

interface FirmKnowledgeRow {
  id: string;
  file_name: string;
  created_at: string;
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
}

const MAX_CHARS = 2000;

function AnswerWithCitationLinks({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap text-sm">
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (!match) return <span key={i}>{part}</span>;
        return (
          <a key={i} href={`#source-${match[1]}`} className="font-medium text-accent hover:underline">
            {part}
          </a>
        );
      })}
    </p>
  );
}

function VerificationBadge({ verification }: { verification: Verification }) {
  if (verification.overall_status === "verified") {
    return (
      <Badge variant="outline" className="gap-1 border-green-600/30 text-green-700">
        <CheckCircle2 className="size-3" />
        Verified against sources
      </Badge>
    );
  }
  if (verification.overall_status === "parse_error") return null;

  const critical = verification.issues.filter((i) => i.severity === "critical");
  const label =
    critical.length > 0
      ? `${critical.length} claim${critical.length > 1 ? "s" : ""} need review`
      : `${verification.issues.length} note${verification.issues.length === 1 ? "" : "s"}`;

  return (
    <Badge variant="outline" className="gap-1 border-amber-600/30 bg-amber-50 text-amber-800">
      <AlertTriangle className="size-3" />
      {label}
    </Badge>
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
  const [copied, setCopied] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(true);

  const [history, setHistory] = useState<QueryListItem[]>([]);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [docType, setDocType] = useState("advice_memo");
  const [savingDoc, setSavingDoc] = useState(false);
  const [savedDocId, setSavedDocId] = useState<string | null>(null);

  const [documentCount, setDocumentCount] = useState(0);
  const [firmKnowledge, setFirmKnowledge] = useState<FirmKnowledgeRow[]>([]);

  const hasAutoLoaded = useRef(false);

  const loadHistory = useCallback(() => {
    fetch("/api/query")
      .then((r) => (r.ok ? r.json() : []))
      .then(setHistory)
      .catch(() => {});
  }, []);

  useEffect(loadHistory, [loadHistory]);

  useEffect(() => {
    fetch("/api/documents/templates")
      .then((r) => (r.ok ? r.json() : []))
      .then(setTemplates)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch("/api/documents")
      .then((r) => (r.ok ? r.json() : []))
      .then((d: unknown[]) => setDocumentCount(d.length))
      .catch(() => {});
    fetch("/api/firm-knowledge")
      .then((r) => (r.ok ? r.json() : []))
      .then(setFirmKnowledge)
      .catch(() => {});
  }, []);

  // Session continuity: the first time history loads with content, resume
  // straight into the most recent conversation (answer + sources) as if
  // the user never left - but leave the ask box empty so they're prompted
  // for a follow-up rather than seeing their old question repeated.
  useEffect(() => {
    if (hasAutoLoaded.current || history.length === 0) return;
    hasAutoLoaded.current = true;
    const mostRecent = history[0];
    const t = setTimeout(async () => {
      try {
        const response = await fetch(`/api/query/${mostRecent.id}`);
        if (!response.ok) return;
        const data = await response.json();
        setResult({
          answer: data.final_answer ?? "",
          citations: data.citations ?? [],
          model_used: data.model_used,
          query_id: data.id ?? mostRecent.id,
        });
        setClientRef(mostRecent.client_ref ?? "");
        // Continue the restored conversation: reuse its session_id so a typed
        // follow-up folds into that session's context rather than starting a new
        // one. Fall back to the freshly-minted id if the row predates session_id.
        if (data.session_id) setSessionId(data.session_id);
        if (data.verification_result?.overall_status) {
          setVerification(data.verification_result);
        }
      } catch {
        // Non-fatal - falls back to the empty-state prompt.
      }
    }, 0);
    return () => clearTimeout(t);
  }, [history]);

  function resetPane() {
    setResult(null);
    setStreamedAnswer("");
    setVerification(null);
    setVerifying(false);
    setSavedDocId(null);
    setDocType("advice_memo");
    setError(null);
  }

  function handleNewQuestion() {
    setQuestion("");
    setClientRef("");
    setSessionId(crypto.randomUUID());
    resetPane();
  }

  // Selecting a past question - from the sidebar or a scenario tag - loads
  // it back into the ask box for re-asking. It does not replay the old
  // answer as if it just happened live.
  function handleSelectHistory(id: string) {
    const item = history.find((h) => h.id === id);
    if (!item) return;
    resetPane();
    setQuestion(item.question);
    setClientRef(item.client_ref ?? "");
    // Re-asking a past question starts a fresh conversation, so mint a new
    // session id rather than folding it into the current session's context.
    setSessionId(crypto.randomUUID());
  }

  async function handleSubmit() {
    setLoading(true);
    resetPane();

    try {
      const gate = await fetch("/api/query/stream?question=", { method: "HEAD" }).catch(() => null);
      if (gate && gate.status === 402) {
        window.location.assign("/upgrade");
        return;
      }

      const streamUrl = `/api/query/stream?question=${encodeURIComponent(question)}${
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
                : { answer, citations, model_used: parsed.model_used ?? null, query_id: null },
            );
          } else if (parsed.type === "verification") {
            setVerifying(false);
            setVerification({
              overall_status: parsed.overall_status ?? "parse_error",
              issues: parsed.issues ?? [],
            });
            loadHistory();
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
          title: question.slice(0, 80),
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

  // Scenario tags: one per distinct topic_tag in this firm's history, newest
  // first, each linked to the question it came from.
  const topicTags = Array.from(
    new Map(history.filter((h) => h.topic_tag).map((h) => [h.topic_tag as string, h.id])).entries()
  );

  return (
    <div className="flex h-[calc(100vh-8rem)] min-h-[420px] w-full min-w-0 overflow-hidden rounded-xl border border-border">
      {historyOpen && (
        <QueryHistorySidebar history={history} onSelect={handleSelectHistory} onNewQuestion={handleNewQuestion} />
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <Button variant="ghost" size="sm" onClick={() => setHistoryOpen((v) => !v)}>
            {historyOpen ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
            {historyOpen ? "Hide questions" : "Show questions"}
          </Button>
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
            {verification && <VerificationBadge verification={verification} />}
          </div>
          <Button variant="ghost" size="sm" onClick={() => setSourcesOpen((v) => !v)}>
            {sourcesOpen ? "Hide sources" : "Show sources"}
            {sourcesOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
          </Button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-6">
          <div className="grid grid-cols-3 gap-3">
            <button
              type="button"
              onClick={() => setHistoryOpen(true)}
              className="text-left transition hover:opacity-80"
            >
              <Card>
                <CardHeader className="pb-0">
                  <p className="text-xs text-muted-foreground">Questions asked</p>
                </CardHeader>
                <CardContent>
                  <p className="text-xl font-semibold">{history.length}</p>
                </CardContent>
              </Card>
            </button>
            <Link href="/dashboard/documents" className="transition hover:opacity-80">
              <Card>
                <CardHeader className="pb-0">
                  <p className="text-xs text-muted-foreground">Documents generated</p>
                </CardHeader>
                <CardContent>
                  <p className="text-xl font-semibold">{documentCount}</p>
                </CardContent>
              </Card>
            </Link>
            <Link href="/dashboard/knowledge" className="transition hover:opacity-80">
              <Card>
                <CardHeader className="pb-0">
                  <p className="text-xs text-muted-foreground">Firm knowledge on file</p>
                </CardHeader>
                <CardContent>
                  <p className="text-xl font-semibold">{firmKnowledge.length}</p>
                </CardContent>
              </Card>
            </Link>
          </div>

          {topicTags.length > 0 && (
            <div className="flex flex-wrap gap-1.5" data-tour="suggested-question">
              {topicTags.map(([tag, id]) => (
                <button
                  key={tag}
                  onClick={() => handleSelectHistory(id)}
                  className="rounded-full border border-border bg-background px-3 py-1 text-xs text-foreground hover:border-accent hover:text-accent"
                >
                  {tag}
                </button>
              ))}
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
              <AnswerWithCitationLinks text={result.answer} />

              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={handleCopy}>
                  {copied ? "Copied!" : "Copy"}
                </Button>
                {savedDocId ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href="/dashboard/documents">View saved document →</Link>
                  </Button>
                ) : (
                  <>
                    <Select value={docType} onValueChange={setDocType}>
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
                    <Button variant="outline" size="sm" disabled={savingDoc} onClick={handleSaveAsDocument}>
                      {savingDoc ? "Saving..." : "Save as document"}
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <div className="border-t border-border p-4">
          <Input
            value={clientRef}
            onChange={(e) => setClientRef(e.target.value)}
            placeholder="Client (optional)"
            className="mb-2 h-8 max-w-xs text-xs"
          />
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
            <Button onClick={handleSubmit} disabled={loading || !question.trim()}>
              {loading ? "Thinking..." : "Ask TaxFlow"}
            </Button>
          </div>
        </div>
      </div>

      {sourcesOpen && <SourcesPanel citations={displayedCitations} />}
    </div>
  );
}
