"use client";

import { useState } from "react";

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

      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value.slice(0, MAX_CHARS))}
        rows={5}
        placeholder="Ask an Australian tax question..."
        className="w-full rounded border p-3"
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-neutral-500">
          {question.length}/{MAX_CHARS} characters
        </span>
        <button
          onClick={handleSubmit}
          disabled={loading || !question.trim()}
          className="rounded bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {loading ? "Thinking..." : "Ask TaxFlow"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {loading && streamedAnswer && (
        <div className="rounded border p-4">
          <p className="whitespace-pre-wrap text-sm">{streamedAnswer}</p>
        </div>
      )}

      {result && (
        <div className="space-y-4 rounded border p-4">
          {result.model_used === "sonnet" && (
            <span className="inline-block rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">
              Complex query - used enhanced model
            </span>
          )}

          <p className="whitespace-pre-wrap text-sm">{result.answer}</p>

          <div className="flex gap-2">
            <button onClick={handleCopy} className="rounded border px-3 py-1 text-xs">
              {copied ? "Copied!" : "Copy"}
            </button>
            <button
              onClick={() => alert("Document generation coming in Week 3")}
              className="rounded border px-3 py-1 text-xs"
            >
              Save as document <span className="ml-1 text-neutral-400">DEMO</span>
            </button>
          </div>

          {result.citations.length > 0 && (
            <div className="border-t pt-3 text-xs text-neutral-600">
              <p className="mb-1 font-medium">Sources</p>
              <ol className="list-decimal space-y-2 pl-4">
                {result.citations.map((c, i) => (
                  <li key={i}>
                    <p>{c.citation}</p>
                    <p className="text-neutral-400">{c.excerpt}</p>
                    {c.url && (
                      <a href={c.url} target="_blank" rel="noreferrer" className="text-blue-600">
                        View source
                      </a>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
