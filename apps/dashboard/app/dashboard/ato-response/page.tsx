"use client";

import { useEffect, useRef, useState } from "react";

interface UploadResult {
  document_id: string;
  classification: {
    letter_type: string;
    confidence: number;
    ato_reference: string;
    deadline_days: number | null;
    key_issue: string;
  };
  handler_result: {
    response_strategy: string;
    evidence_checklist: string[];
    timeline: string;
  };
  draft_response: string;
}

interface HistoryRow {
  id: string;
  title: string;
  status: string;
  created_at: string;
}

export default function AtoResponsePage() {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/ato-response")
      .then((r) => (r.ok ? r.json() : []))
      .then(setHistory)
      .catch(() => {});
  }, [result]);

  async function handleUpload() {
    const file = fileInput.current?.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch("/api/ato-response/upload", { method: "POST", body: formData });
      if (!response.ok) throw new Error("Upload failed");
      setResult(await response.json());
    } catch {
      setError("Could not process this letter - please try again");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">ATO Correspondence</h1>
        <p className="text-sm text-muted-foreground">
          Upload an ATO letter (PDF) to get a classification, response strategy, and drafted reply.
        </p>
      </div>

      <div className="rounded-lg border border-dashed border-border p-6 text-center">
        <input ref={fileInput} type="file" accept="application/pdf" className="mx-auto block text-sm" />
        <button
          onClick={handleUpload}
          disabled={uploading}
          className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-all duration-200 hover:bg-accent disabled:opacity-50"
        >
          {uploading ? "Analysing letter..." : "Upload and analyse"}
        </button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {result && (
        <div className="space-y-4 rounded-lg border border-border p-4">
          <div className="flex items-center justify-between">
            <span className="rounded bg-muted px-2 py-0.5 text-xs font-medium">
              {result.classification.letter_type.replace(/_/g, " ")}
            </span>
            {result.classification.deadline_days !== null && (
              <span className="text-xs text-destructive">
                Deadline: {result.classification.deadline_days} days
              </span>
            )}
          </div>
          <p className="text-sm">{result.classification.key_issue}</p>

          <div>
            <p className="mb-1 text-xs font-semibold text-muted-foreground">RESPONSE STRATEGY</p>
            <p className="text-sm">{result.handler_result.response_strategy}</p>
          </div>

          <div>
            <p className="mb-1 text-xs font-semibold text-muted-foreground">EVIDENCE CHECKLIST</p>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {result.handler_result.evidence_checklist.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>

          <div>
            <p className="mb-1 text-xs font-semibold text-muted-foreground">DRAFT RESPONSE</p>
            <p className="whitespace-pre-wrap rounded bg-muted p-3 text-sm">{result.draft_response}</p>
          </div>

          <a
            href={`/api/documents/${result.document_id}/download?fmt=docx`}
            className="inline-block rounded border border-border px-3 py-1 text-xs hover:bg-muted"
          >
            Download as .docx
          </a>
        </div>
      )}

      {history.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">HISTORY</p>
          <ul className="divide-y divide-border rounded-lg border border-border text-sm">
            {history.map((h) => (
              <li key={h.id} className="flex items-center justify-between px-4 py-2">
                <span>{h.title}</span>
                <span className="text-xs text-muted-foreground">
                  {new Date(h.created_at).toLocaleDateString("en-AU")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
