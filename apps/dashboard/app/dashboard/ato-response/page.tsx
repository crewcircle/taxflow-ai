"use client";

import { useEffect, useRef, useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

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

      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center gap-4 py-4 text-center">
          <Upload className="size-6 text-muted-foreground" />
          <input ref={fileInput} type="file" accept="application/pdf" className="text-sm" />
          <Button onClick={handleUpload} disabled={uploading}>
            {uploading ? "Analysing letter..." : "Upload and analyse"}
          </Button>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {result && (
        <Card>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Badge variant="outline">{result.classification.letter_type.replace(/_/g, " ")}</Badge>
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
              <p className="whitespace-pre-wrap rounded-lg bg-muted p-3 text-sm">
                {result.draft_response}
              </p>
            </div>

            <Button asChild variant="outline" size="sm">
              <a href={`/api/documents/${result.document_id}/download?fmt=docx`}>
                Download as .docx
              </a>
            </Button>
          </CardContent>
        </Card>
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
