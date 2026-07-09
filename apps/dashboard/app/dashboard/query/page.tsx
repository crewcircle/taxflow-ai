"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

interface Citation {
  citation: string;
  url: string;
  excerpt: string;
}

interface QueryResult {
  query_id: string;
  answer: string;
  citations: Citation[];
  confidence: number;
  model_used: "haiku" | "sonnet";
}

const MAX_CHARS = 2000;

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [copied, setCopied] = useState(false);

  async function handleSubmit() {
    setLoading(true);
    setError(null);
    setResult(null);
    setStreamedAnswer("");

    try {
      // Trial gate check runs on the non-stream endpoint; EventSource cannot
      // surface response bodies, so probe caps first and route 402 to /upgrade.
      const gate = await fetch("/api/query/stream?question=", { method: "HEAD" }).catch(() => null);
      if (gate && gate.status === 402) {
        window.location.assign("/upgrade");
        return;
      }

      const source = new EventSource(`/api/query/stream?question=${encodeURIComponent(question)}`);
      let answer = "";

      await new Promise<void>((resolve, reject) => {
        source.onmessage = (event) => {
          if (event.data === "[DONE]") {
            source.close();
            resolve();
            return;
          }
          const parsed: { type: string; text?: string; citations?: Citation[] } = JSON.parse(event.data);
          if (parsed.type === "token" && parsed.text) {
            answer += parsed.text;
            setStreamedAnswer(answer);
          } else if (parsed.type === "final") {
            setResult({
              query_id: "",
              answer,
              citations: parsed.citations ?? [],
              confidence: 1,
              model_used: "haiku",
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

      {loading && streamedAnswer && (
        <Card>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm">{streamedAnswer}</p>
          </CardContent>
        </Card>
      )}

      {result && (
        <Card>
          <CardContent className="space-y-4">
            {result.model_used === "sonnet" && (
              <Badge variant="outline" className="gap-1 border-accent/30 text-accent">
                <Sparkles className="size-3" />
                Complex query - used enhanced model
              </Badge>
            )}

            <p className="whitespace-pre-wrap text-sm">{result.answer}</p>

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
                    <li key={i}>
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
