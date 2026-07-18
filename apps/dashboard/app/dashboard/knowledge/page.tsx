"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface KnowledgeRow {
  id: string;
  file_name: string;
  file_type: string;
  usage_count: number;
  created_at: string;
}

interface KnowledgeDetail extends KnowledgeRow {
  content: string;
}

export default function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeRow[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  function load() {
    fetch("/api/firm-knowledge")
      .then((r) => (r.ok ? r.json() : []))
      .then(setItems)
      .catch(() => {});
  }

  useEffect(load, []);

  async function toggleExpand(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    setExpandedId(id);
    setDetail(null);
    setDetailLoading(true);
    try {
      const response = await fetch(`/api/firm-knowledge/${id}`);
      if (response.ok) setDetail(await response.json());
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleUpload() {
    const file = fileInput.current?.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch("/api/firm-knowledge/upload", { method: "POST", body: formData });
      if (!response.ok) throw new Error("Upload failed");
      if (fileInput.current) fileInput.current.value = "";
      load();
    } catch {
      setError("Could not upload this file - supported types are PDF, DOCX, TXT");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: string) {
    await fetch(`/api/firm-knowledge/${id}`, { method: "DELETE" });
    load();
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Firm Knowledge</h1>
        <p className="text-sm text-muted-foreground">
          Upload your firm&apos;s own precedents, templates, or internal guidance. Research
          answers blend these in alongside the AU tax knowledge base.
        </p>
      </div>

      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center gap-4 py-4 text-center">
          <Upload className="size-6 text-muted-foreground" />
          <Tooltip>
            <TooltipTrigger asChild>
              <input ref={fileInput} type="file" accept=".pdf,.docx,.txt" className="text-sm" />
            </TooltipTrigger>
            <TooltipContent>PDF, DOCX, or TXT - the content is blended into future research answers alongside the AU tax knowledge base</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button onClick={handleUpload} disabled={uploading}>
                {uploading ? "Uploading..." : "Upload document"}
              </Button>
            </TooltipTrigger>
            <TooltipContent>Adds the selected file to your firm&apos;s knowledge base</TooltipContent>
          </Tooltip>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No documents uploaded yet.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {items.map((item) => (
            <li key={item.id}>
              <div className="flex w-full items-center justify-between gap-3 px-4 py-2 hover:bg-muted">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      onClick={() => toggleExpand(item.id)}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium">{item.file_name}</p>
                        <p className="text-xs text-muted-foreground">
                          {item.file_type.toUpperCase()} · used in {item.usage_count} answers
                        </p>
                      </div>
                      {expandedId === item.id ? (
                        <ChevronUp className="size-4 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
                      )}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {expandedId === item.id ? "Collapse this document" : "Expand to read the full saved content"}
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="link"
                      size="sm"
                      className="shrink-0 text-destructive"
                      onClick={() => handleDelete(item.id)}
                    >
                      Remove
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Permanently removes this from Firm Knowledge - it will no longer be used in research answers</TooltipContent>
                </Tooltip>
              </div>
              {expandedId === item.id && (
                <div className="border-t border-border bg-muted/30 px-4 py-3">
                  {detailLoading ? (
                    <p className="text-xs text-muted-foreground">Loading...</p>
                  ) : (
                    <p className="max-h-80 overflow-y-auto whitespace-pre-wrap text-sm text-foreground">
                      {detail?.content ?? "Could not load this document."}
                    </p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
