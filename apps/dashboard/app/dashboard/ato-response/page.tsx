"use client";

import { useEffect, useRef, useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EngagementPicker, type EngagementSelection } from "@/components/EngagementPicker";

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
  context_note: string | null;
  created_at: string;
}

interface HistoryDetail {
  id: string;
  title: string;
  status: string;
  content_md: string;
  created_at: string;
}

function humanizeTitle(title: string): string {
  return title.replace(/_/g, " ");
}

export default function AtoResponsePage() {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  // Phase 2: attribute the uploaded letter to a first-class engagement. This is
  // the fix for the flow that previously dropped attribution entirely — both
  // engagement_id and the end-client name (client_ref) are now sent on upload.
  const [engagement, setEngagement] = useState<EngagementSelection | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  function loadHistory() {
    fetch("/api/ato-response")
      .then((r) => (r.ok ? r.json() : []))
      .then(setHistory)
      .catch(() => {});
  }

  useEffect(loadHistory, [result]);

  async function handleSelectHistory(id: string) {
    setActiveId(id);
    setResult(null);
    setDetail(null);
    setDetailLoading(true);
    try {
      const response = await fetch(`/api/ato-response/${id}`);
      if (!response.ok) throw new Error("Could not load this response");
      setDetail(await response.json());
    } catch {
      setError("Could not load this response");
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleApprove() {
    if (!detail) return;
    setApproving(true);
    try {
      const response = await fetch(`/api/ato-response/${detail.id}/approve`, { method: "POST" });
      if (!response.ok) throw new Error("Failed");
      setDetail({ ...detail, status: "approved" });
      loadHistory();
    } catch {
      setError("Could not approve this response - please try again");
    } finally {
      setApproving(false);
    }
  }

  async function handleUpload() {
    const file = fileInput.current?.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    setResult(null);
    setDetail(null);
    setActiveId(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (engagement) {
        formData.append("engagement_id", engagement.engagement.id);
        formData.append("client_ref", engagement.clientName);
      }
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
          Approved responses also appear in Documents.
        </p>
      </div>

      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center gap-4 py-4 text-center">
          <Upload className="size-6 text-muted-foreground" />
          <input ref={fileInput} type="file" accept="application/pdf" className="text-sm" />
          <EngagementPicker
            value={engagement}
            onChange={setEngagement}
            triggerLabel="Choose client & engagement"
            disabled={uploading}
          />
          <Button onClick={handleUpload} disabled={uploading || !engagement}>
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

      {detailLoading && <p className="text-sm text-muted-foreground">Loading...</p>}

      {detail && (
        <Card>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">{humanizeTitle(detail.title)}</p>
              <Badge variant={detail.status === "approved" ? "secondary" : "outline"}>
                {detail.status}
              </Badge>
            </div>

            <div>
              <p className="mb-1 text-xs font-semibold text-muted-foreground">DRAFT RESPONSE</p>
              <p className="whitespace-pre-wrap rounded-lg bg-muted p-3 text-sm">
                {detail.content_md}
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {detail.status !== "approved" && (
                <Button size="sm" disabled={approving} onClick={handleApprove}>
                  {approving ? "Approving..." : "Approve"}
                </Button>
              )}
              <Button asChild variant="outline" size="sm">
                <a href={`/api/documents/${detail.id}/download?fmt=docx`}>Download as .docx</a>
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {history.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">HISTORY</p>
          <ul className="divide-y divide-border rounded-lg border border-border text-sm">
            {history.map((h) => (
              <li key={h.id}>
                <button
                  onClick={() => handleSelectHistory(h.id)}
                  className={`flex w-full items-start justify-between gap-4 px-4 py-2 text-left transition-colors hover:bg-muted ${
                    h.id === activeId ? "bg-muted" : ""
                  }`}
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      {humanizeTitle(h.title)}
                      <Badge variant={h.status === "approved" ? "secondary" : "outline"} className="text-[10px]">
                        {h.status}
                      </Badge>
                    </span>
                    {h.context_note && (
                      <span className="block truncate text-xs text-muted-foreground">{h.context_note}</span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {new Date(h.created_at).toLocaleDateString("en-AU")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
