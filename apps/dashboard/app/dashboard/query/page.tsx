"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

interface Citation {
  citation: string;
  url: string;
  excerpt: string;
}

interface VerificationIssue {
  claim: string;
  issue: string;
  severity: "critical" | "warning" | "note";
  source_says: string;
  suggested_correction: string;
}

interface Verification {
  overall_status: "verified" | "needs_correction" | "unreliable" | "parse_error";
  issues: VerificationIssue[];
  overall_confidence?: number;
}

interface QueryResult {
  answer: string;
  citations: Citation[];
  model_used: "haiku" | "sonnet";
}

const MAX_CHARS = 2000;

// Renders the answer with [N] markers turned into clickable anchors that
// jump to the matching entry in the Sources list below.
function AnswerWithCitationLinks({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap text-sm">
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (!match) return <span key={i}>{part}</span>;
        return (
          <a
            key={i}
            href={`#source-${match[1]}`}
            className="font-medium text-accent hover:underline"
          >
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

  if (verification.overall_status === "parse_error") {
    return null;
  }

  const critical = verification.issues.filter((i) => i.severity === "critical");
  const label =
    critical.length > 0
      ? `${critical.length} claim${critical.length > 1 ? "s" : ""} need review`
      : `${verification.issues.length} note${verification.issues.length === 1 ? "" : "s"} on this answer`;

  return (
    <details className="group">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 rounded-full border border-amber-600/30 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800">
        <AlertTriangle className="size-3" />
        {label}
      </summary>
      <ul className="mt-2 space-y-2 border-l-2 border-amber-200 pl-3 text-xs text-muted-foreground">
        {verification.issues.map((issue, i) => (
          <li key={i}>
            <span
              className={
                issue.severity === "critical" ? "font-semibold text-destructive" : "font-medium text-foreground"
              }
            >
              {issue.severity === "critical" ? "Critical: " : issue.severity === "warning" ? "Check: " : "Note: "}
            </span>
            {issue.issue}
          </li>
        ))}
      </ul>
    </details>
  );
}

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleSubmit() {
    setLoading(true);
    setError(null);
    setResult(null);
    setStreamedAnswer("");
    setVerification(null);
    setVerifying(false);

    try {
      // Trial gate check runs on the stream endpoint itself; EventSource cannot
      // surface response bodies, so probe with HEAD first and route 402 to /upgrade.
      const gate = await fetch("/api/query/stream?question=", { method: "HEAD" }).catch(() => null);
      if (gate && gate.status === 402) {
        window.location.assign("/upgrade");
        return;
      }

      const source = new EventSource(`/api/query/stream?question=${encodeURIComponent(question)}`);
      let answer = "";
      let citations: Citation[] = [];

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
            citations?: Citation[];
            overall_status?: Verification["overall_status"];
            issues?: VerificationIssue[];
            overall_confidence?: number;
          } = JSON.parse(event.data);

          if (parsed.type === "token" && parsed.text) {
            answer += parsed.text;
            setStreamedAnswer(answer);
          } else if (parsed.type === "final") {
            citations = parsed.citations ?? [];
            setResult({ answer, citations, model_used: "haiku" });
            setVerifying(true);
          } else if (parsed.type === "verification") {
            setVerifying(false);
            setVerification({
              overall_status: parsed.overall_status ?? "parse_error",
              issues: parsed.issues ?? [],
              overall_confidence: parsed.overall_confidence,
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

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Ask TaxFlow</h1>

      <Textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value.slice(0, MAX_CHARS))}
        rows={5}
        placeholder="Ask an Australian tax question..."
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {question.length}/{MAX_CHARS} characters
        </span>
        <Button onClick={handleSubmit} disabled={loading || !question.trim()}>
          {loading ? "Thinking..." : "Ask TaxFlow"}
        </Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading && streamedAnswer && !result && (
        <Card>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm">{streamedAnswer}</p>
          </CardContent>
        </Card>
      )}

      {result && (
        <Card>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              {result.model_used === "sonnet" && (
                <Badge variant="outline" className="gap-1 border-accent/30 text-accent">
                  <Sparkles className="size-3" />
                  Complex query - used enhanced model
                </Badge>
              )}
              {verifying && (
                <Badge variant="outline" className="gap-1 text-muted-foreground">
                  Verifying against sources...
                </Badge>
              )}
              {verification && <VerificationBadge verification={verification} />}
            </div>

            <AnswerWithCitationLinks text={result.answer} />

            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={handleCopy}>
                {copied ? "Copied!" : "Copy"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => alert("Document generation coming in Week 3")}
              >
                Save as document
                <span className="ml-1 text-muted-foreground">DEMO</span>
              </Button>
            </div>

            {result.citations.length > 0 && (
              <div className="space-y-2 border-t border-border pt-3 text-xs text-muted-foreground">
                <p className="font-medium text-foreground">Sources</p>
                <ol className="list-decimal space-y-2 pl-4">
                  {result.citations.map((c, i) => (
                    <li key={i} id={`source-${i + 1}`} className="scroll-mt-4 target:rounded target:bg-accent/10">
                      <p className="text-foreground">{c.citation}</p>
                      <p>{c.excerpt}</p>
                      {c.url && (
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-accent hover:underline"
                        >
                          View source
                        </a>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
