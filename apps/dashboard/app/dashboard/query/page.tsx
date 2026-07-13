"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileText,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  ScrollText,
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

interface DocumentRow {
  id: string;
  title: string;
  created_at: string;
}

interface FirmKnowledgeRow {
  id: string;
  file_name: string;
  created_at: string;
}

interface AtoResponseRow {
  id: string;
  title: string;
  created_at: string;
}

interface ClientSettings {
  business_name: string;
  is_demo: boolean;
  demo_tagline: string | null;
}

type ActivityItem = {
  id: string;
  label: string;
  href: string;
  created_at: string;
  kind: "query" | "document";
};

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
}

const MAX_CHARS = 2000;

function relativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDiff = Math.round((startOfToday.getTime() - startOfDate.getTime()) / 86400000);

  if (dayDiff <= 0) return "Today";
  if (dayDiff === 1) return "Yesterday";
  if (dayDiff < 7) return `${dayDiff} days ago`;
  return date.toLocaleDateString("en-AU");
}

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [copied, setCopied] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(true);

  const [history, setHistory] = useState<QueryListItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [docType, setDocType] = useState("advice_memo");
  const [savingDoc, setSavingDoc] = useState(false);
  const [savedDocId, setSavedDocId] = useState<string | null>(null);

  const [client, setClient] = useState<ClientSettings | null>(null);
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [firmKnowledge, setFirmKnowledge] = useState<FirmKnowledgeRow[]>([]);
  const [atoResponses, setAtoResponses] = useState<AtoResponseRow[]>([]);

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
    fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setClient(d.client))
      .catch(() => {});
    fetch("/api/documents")
      .then((r) => (r.ok ? r.json() : []))
      .then(setDocuments)
      .catch(() => {});
    fetch("/api/firm-knowledge")
      .then((r) => (r.ok ? r.json() : []))
      .then(setFirmKnowledge)
      .catch(() => {});
    fetch("/api/ato-response")
      .then((r) => (r.ok ? r.json() : []))
      .then(setAtoResponses)
      .catch(() => {});
  }, []);

  const activity: ActivityItem[] = [
    ...history.map((q) => ({
      id: q.id,
      label: q.question,
      href: "/dashboard/query",
      created_at: q.created_at,
      kind: "query" as const,
    })),
    ...documents.map((d) => ({
      id: d.id,
      label: d.title,
      href: "/dashboard/documents",
      created_at: d.created_at,
      kind: "document" as const,
    })),
  ]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 6);

  function resetPane() {
    setResult(null);
    setStreamedAnswer("");
    setDrafting(false);
    setVerification(null);
    setVerifying(false);
    setSavedDocId(null);
    setDocType("advice_memo");
    setError(null);
  }

  function handleNewQuestion() {
    setActiveId(null);
    setQuestion("");
    setClientRef("");
    resetPane();
  }

  function handleUseSuggestion(suggestion: string) {
    setQuestion(suggestion);
  }

  async function handleSelectHistory(id: string) {
    setActiveId(id);
    resetPane();
    setLoading(true);
    try {
      const response = await fetch(`/api/query/${id}`);
      if (!response.ok) throw new Error("Could not load this question");
      const data = await response.json();
      setQuestion(data.question);
      setClientRef(data.client_ref ?? "");
      setResult({
        answer: data.final_answer ?? "",
        citations: data.citations ?? [],
        model_used: data.model_used,
      });
      if (data.verification_result?.overall_status) {
        setVerification(data.verification_result);
      }
    } catch {
      setError("Could not load this question");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit() {
    setActiveId(null);
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
      }`;
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
            overall_status?: Verification["overall_status"];
            issues?: VerificationIssue[];
          } = JSON.parse(event.data);

          if (parsed.type === "token" && parsed.text) {
            answer += parsed.text;
            setStreamedAnswer(answer);
          } else if (parsed.type === "final") {
            citations = parsed.citations ?? [];
            setResult({ answer, citations, model_used: "haiku" });
            setDrafting(true);
          } else if (parsed.type === "draft" && parsed.text) {
            setDrafting(false);
            setResult({ answer: parsed.text, citations, model_used: "haiku" });
            setVerifying(true);
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
          query_id: activeId,
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

  return (
    <div className="flex h-[75vh] min-h-[520px] overflow-hidden rounded-xl border border-border">
      <QueryHistorySidebar
        history={history}
        activeId={activeId}
        onSelect={handleSelectHistory}
        onNewQuestion={handleNewQuestion}
      />

      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-6 py-3">
          <h1 className="text-sm font-semibold text-foreground">Ask TaxFlow</h1>
          <div className="flex items-center gap-2">
            {result?.model_used === "sonnet" && (
              <Badge variant="outline" className="gap-1 border-accent/30 text-accent">
                <Sparkles className="size-3" />
                Enhanced model
              </Badge>
            )}
            {drafting && (
              <Badge variant="outline" className="text-muted-foreground">
                Drafting advice memo...
              </Badge>
            )}
            {verifying && (
              <Badge variant="outline" className="text-muted-foreground">
                Verifying...
              </Badge>
            )}
            {verification && <VerificationBadge verification={verification} />}
            <Button variant="ghost" size="sm" onClick={() => setSourcesOpen((v) => !v)}>
              {sourcesOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
              {sourcesOpen ? "Hide sources" : "Show sources"}
            </Button>
          </div>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto p-6">
          {!result && !loading && (
            <div className="space-y-6">
              <div className="grid grid-cols-3 gap-3">
                <Card>
                  <CardHeader className="pb-0">
                    <p className="text-xs text-muted-foreground">Questions asked</p>
                  </CardHeader>
                  <CardContent>
                    <p className="text-xl font-semibold">{history.length}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-0">
                    <p className="text-xs text-muted-foreground">Documents generated</p>
                  </CardHeader>
                  <CardContent>
                    <p className="text-xl font-semibold">{documents.length}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-0">
                    <p className="text-xs text-muted-foreground">Firm knowledge on file</p>
                  </CardHeader>
                  <CardContent>
                    <p className="text-xl font-semibold">{firmKnowledge.length}</p>
                  </CardContent>
                </Card>
              </div>

              {client?.is_demo && (
                <Card className="border-accent/30 bg-accent/5">
                  <CardContent className="space-y-3 pt-6">
                    <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <Sparkles className="size-4 text-accent" />
                      Your scenario: {client.business_name}
                    </p>
                    {client.demo_tagline && (
                      <p className="text-sm text-muted-foreground">{client.demo_tagline}</p>
                    )}

                    {history.length > 0 && (
                      <div className="space-y-1.5" data-tour="suggested-question">
                        <p className="text-xs font-semibold text-muted-foreground">
                          TRY ONE OF THIS FIRM&apos;S QUESTIONS
                        </p>
                        <div className="flex flex-col gap-1.5">
                          {history.slice(0, 3).map((q) => (
                            <button
                              key={q.id}
                              onClick={() => handleUseSuggestion(q.question)}
                              className="rounded-lg border border-border bg-background p-2.5 text-left text-sm hover:border-accent"
                            >
                              {q.question}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="grid gap-2 sm:grid-cols-2">
                      <Link
                        href="/dashboard/ato-response"
                        className="flex items-center justify-between rounded-lg border border-border bg-background p-3 text-sm hover:border-accent"
                      >
                        <span className="flex items-center gap-2">
                          <ScrollText className="size-4 text-muted-foreground" />
                          {atoResponses.length > 0
                            ? atoResponses[0].title.replace(/_/g, " ")
                            : "ATO correspondence"}
                        </span>
                        <ArrowRight className="size-3.5 text-muted-foreground" />
                      </Link>
                      <Link
                        href="/dashboard/knowledge"
                        className="flex items-center justify-between rounded-lg border border-border bg-background p-3 text-sm hover:border-accent"
                      >
                        <span className="flex items-center gap-2">
                          <FileText className="size-4 text-muted-foreground" />
                          {firmKnowledge.length > 0 ? firmKnowledge[0].file_name : "Firm knowledge"}
                        </span>
                        <ArrowRight className="size-3.5 text-muted-foreground" />
                      </Link>
                    </div>
                  </CardContent>
                </Card>
              )}

              {activity.length > 0 && (
                <div>
                  <p className="mb-2 text-xs font-semibold text-muted-foreground">RECENT ACTIVITY</p>
                  <ul className="divide-y divide-border rounded-lg border border-border text-sm">
                    {activity.map((item) => (
                      <li key={`${item.kind}-${item.id}`}>
                        <Link
                          href={item.href}
                          className="flex items-center justify-between gap-4 px-4 py-2 hover:bg-muted"
                        >
                          <span className="flex items-center gap-2 truncate">
                            <Badge variant="outline" className="shrink-0 text-[10px]">
                              {item.kind === "query" ? (
                                <MessageSquare className="size-3" />
                              ) : (
                                <FileText className="size-3" />
                              )}
                            </Badge>
                            <span className="truncate">{item.label}</span>
                          </span>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {relativeTime(item.created_at)}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {activity.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  Ask a question below to get started.
                </p>
              )}
            </div>
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
            placeholder="Ask an Australian tax question..."
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
