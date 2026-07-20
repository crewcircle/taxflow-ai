"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ResourceRowActions } from "@/components/resource-actions/ResourceRowActions";
import { ConfirmDialog } from "@/components/resource-actions/ConfirmDialog";
import { ResourceEditDialog } from "@/components/resource-actions/ResourceEditDialog";
import { useResourceMutation } from "@/components/resource-actions/useResourceMutation";

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

interface Suggestion {
  id: string;
  title: string;
  content: string;
  reason: string | null;
  status: string;
  source_query_id: string | null;
  source_document_id: string | null;
  created_at: string;
}

// Human-readable label for where a suggestion came from (backend `reason` value).
const REASON_LABELS: Record<string, string> = {
  thumbs_up: "Approved research answer",
  saved_memo: "Saved advice memo",
};

function reasonLabel(reason: string | null): string {
  if (!reason) return "Suggestion";
  return REASON_LABELS[reason] ?? reason;
}

export default function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeRow[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [expandedSuggestionId, setExpandedSuggestionId] = useState<string | null>(null);
  const [decidingId, setDecidingId] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<KnowledgeRow | null>(null);
  const [editTarget, setEditTarget] = useState<
    { id: string; title: string; content_md: string } | null
  >(null);
  const mutation = useResourceMutation({ onSuccess: load });

  function load() {
    fetch("/api/firm-knowledge")
      .then((r) => (r.ok ? r.json() : []))
      .then(setItems)
      .catch(() => {});
  }

  function loadSuggestions() {
    fetch("/api/firm-knowledge/suggestions?status=pending")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setSuggestions(Array.isArray(data) ? data : []))
      .catch(() => {});
  }

  useEffect(() => {
    load();
    loadSuggestions();
  }, []);

  async function decideSuggestion(id: string, action: "approve" | "reject") {
    setDecidingId(id);
    try {
      const response = await fetch(`/api/firm-knowledge/suggestions/${id}/${action}`, {
        method: "POST",
      });
      if (!response.ok) return;
      // Approved suggestions become firm knowledge items; refresh both lists so
      // the approved note shows up above and drops out of the pending list.
      loadSuggestions();
      if (action === "approve") load();
    } finally {
      setDecidingId(null);
    }
  }

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

  async function openEdit(item: KnowledgeRow) {
    // The list row does not carry content; fetch the full item first.
    try {
      const res = await fetch(`/api/firm-knowledge/${item.id}`);
      if (!res.ok) throw new Error("Failed");
      const full = await res.json();
      setEditTarget({
        id: item.id,
        title: item.file_name,
        content_md: full.content ?? "",
      });
    } catch {
      setError("Could not open this document for editing");
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Our Firm&apos;s Precedents</h1>
        <p className="text-sm text-muted-foreground">
          Upload your firm&apos;s own precedents, templates, or internal guidance. Research
          answers blend these in alongside TaxFlow&apos;s Reference Library.
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

      {suggestions.length > 0 && (
        <div className="space-y-3">
          <div>
            <h2 className="text-base font-semibold">Suggestions</h2>
            <p className="text-sm text-muted-foreground">
              Pending suggestions from approved research answers and saved memos. Approve to add
              them to Firm Knowledge, or reject to dismiss.
            </p>
          </div>
          <ul className="divide-y divide-border rounded-lg border border-border text-sm">
            {suggestions.map((suggestion) => (
              <li key={suggestion.id}>
                <div className="flex w-full items-start justify-between gap-3 px-4 py-3">
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedSuggestionId(
                        expandedSuggestionId === suggestion.id ? null : suggestion.id
                      )
                    }
                    className="flex min-w-0 flex-1 items-start gap-3 text-left"
                  >
                    <div className="min-w-0 space-y-1">
                      <p className="truncate font-medium">{suggestion.title}</p>
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary">{reasonLabel(suggestion.reason)}</Badge>
                      </div>
                      <p className="line-clamp-2 text-xs text-muted-foreground">
                        {suggestion.content}
                      </p>
                    </div>
                    {expandedSuggestionId === suggestion.id ? (
                      <ChevronUp className="size-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
                    )}
                  </button>
                  <div className="flex shrink-0 items-center gap-2">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          size="sm"
                          disabled={decidingId === suggestion.id}
                          onClick={() => decideSuggestion(suggestion.id, "approve")}
                        >
                          Approve
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        Adds this to Firm Knowledge so it is used in future research answers
                      </TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="link"
                          size="sm"
                          className="text-destructive"
                          disabled={decidingId === suggestion.id}
                          onClick={() => decideSuggestion(suggestion.id, "reject")}
                        >
                          Reject
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Dismisses this suggestion without saving it</TooltipContent>
                    </Tooltip>
                  </div>
                </div>
                {expandedSuggestionId === suggestion.id && (
                  <div className="border-t border-border bg-muted/30 px-4 py-3">
                    <p className="max-h-80 overflow-y-auto whitespace-pre-wrap text-sm text-foreground">
                      {suggestion.content}
                    </p>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

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
                <ResourceRowActions
                  label="precedent"
                  actions={{
                    edit: () => openEdit(item),
                    delete: () => setDeleteTarget(item),
                  }}
                />
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

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title="Remove precedent?"
        description={
          deleteTarget
            ? `"${deleteTarget.file_name}" will be permanently removed and no longer used in research answers. This cannot be undone.`
            : undefined
        }
        confirmLabel="Remove"
        destructive
        pending={mutation.pending}
        onConfirm={async () => {
          if (!deleteTarget) return;
          const deletedId = deleteTarget.id;
          const ok = await mutation.remove(`/api/firm-knowledge/${deletedId}`, "Precedent removed");
          if (ok) {
            setDeleteTarget(null);
            if (expandedId === deletedId) {
              setExpandedId(null);
              setDetail(null);
            }
          }
        }}
      />

      {editTarget && (
        <ResourceEditDialog
          open={!!editTarget}
          onOpenChange={(open) => {
            if (!open) setEditTarget(null);
          }}
          initial={{ title: editTarget.title, content_md: editTarget.content_md }}
          pending={mutation.pending}
          onSave={async (fields) => {
            // Firm-knowledge stores a single `content` field; the title here is
            // the (read-only) file name, so only the body is persisted.
            const ok = await mutation.patch(
              `/api/firm-knowledge/${editTarget.id}`,
              { content: fields.content_md },
              "Precedent updated"
            );
            if (ok) {
              setEditTarget(null);
              if (expandedId === editTarget.id) {
                setDetail((prev) => (prev ? { ...prev, content: fields.content_md } : prev));
              }
            }
          }}
        />
      )}
    </div>
  );
}
