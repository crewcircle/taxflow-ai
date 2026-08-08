"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ChevronDown, ChevronUp, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  assigned_to: string | null;
}

interface StaffMember {
  id: string;
  email: string;
  role: "owner" | "reviewer" | "staff";
  display_name: string | null;
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
  const [items, setItems] = useState<KnowledgeRow[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [expandedSuggestionId, setExpandedSuggestionId] = useState<string | null>(null);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [assigningId, setAssigningId] = useState<string | null>(null);
  // Approve/reject is Owner-only, enforced server-side (rbac.py
  // "knowledge.approve") - this just decides whether to show those buttons at
  // all, not the actual security boundary.
  const [currentRole, setCurrentRole] = useState<"owner" | "reviewer" | "staff" | null>(null);
  const [owners, setOwners] = useState<StaffMember[]>([]);

  const [deleteTarget, setDeleteTarget] = useState<KnowledgeRow | null>(null);
  // Rejecting a suggestion is just as final as deleting a precedent (no undo
  // in the UI either way) but used to fire straight from the onClick - one
  // misclick discarded a colleague's promoted answer with no chance to back
  // out. Confirmed the same way delete already is.
  const [rejectTarget, setRejectTarget] = useState<Suggestion | null>(null);
  const [editTarget, setEditTarget] = useState<
    { id: string; title: string; content_md: string } | null
  >(null);
  const mutation = useResourceMutation({ onSuccess: load });

  function load() {
    fetch("/api/firm-knowledge")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setItems)
      .catch(() => {
        setItems([]);
        toast.error("Could not load your firm's precedents");
      });
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
    fetch("/api/settings/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setCurrentRole(data?.client?.role ?? null))
      .catch(() => {});
    fetch("/api/staff")
      .then((r) => (r.ok ? r.json() : []))
      .then((data: StaffMember[]) => setOwners(Array.isArray(data) ? data.filter((u) => u.role === "owner") : []))
      .catch(() => {});
  }, []);

  const canDecide = currentRole === "owner";

  async function decideSuggestion(id: string, action: "approve" | "reject") {
    setDecidingId(id);
    try {
      const response = await fetch(`/api/firm-knowledge/suggestions/${id}/${action}`, {
        method: "POST",
      });
      if (!response.ok) {
        toast.error(
          action === "approve"
            ? "Could not approve this suggestion - please try again"
            : "Could not reject this suggestion - please try again"
        );
        return;
      }
      // Approved suggestions become firm knowledge items; refresh both lists so
      // the approved note shows up above and drops out of the pending list.
      loadSuggestions();
      if (action === "approve") load();
      toast.success(action === "approve" ? "Added to Firm Knowledge" : "Suggestion rejected");
    } finally {
      setDecidingId(null);
    }
  }

  async function assignSuggestion(id: string, userId: string | null) {
    setAssigningId(id);
    try {
      const response = await fetch(`/api/firm-knowledge/suggestions/${id}/assign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
      if (!response.ok) {
        toast.error("Could not update the assignee - please try again");
        return;
      }
      const updated = await response.json();
      setSuggestions((prev) => prev.map((s) => (s.id === id ? { ...s, assigned_to: updated.assigned_to } : s)));
    } finally {
      setAssigningId(null);
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
      toast.success("File uploaded");
    } catch {
      setError("Could not upload this file - supported types are PDF, DOCX, TXT");
      toast.error("Could not upload this file - supported types are PDF, DOCX, TXT");
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
      toast.error("Could not open this document for editing");
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
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    {/* Explicit ownership so a pending suggestion doesn't just
                        sit there for "whoever notices the badge" - only
                        Owners can ever approve/reject (rbac.py), so only
                        Owners are assignable here. */}
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div>
                          <Select
                            value={suggestion.assigned_to ?? "__unassigned"}
                            disabled={assigningId === suggestion.id}
                            onValueChange={(value) =>
                              assignSuggestion(suggestion.id, value === "__unassigned" ? null : value)
                            }
                          >
                            <SelectTrigger size="sm" className="h-7 w-[150px] text-xs">
                              <SelectValue placeholder="Unassigned" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__unassigned">Unassigned</SelectItem>
                              {owners.map((owner) => (
                                <SelectItem key={owner.id} value={owner.id}>
                                  {owner.display_name || owner.email}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>Who&apos;s reviewing this suggestion - only an Owner can be assigned, since only an Owner can decide it</TooltipContent>
                    </Tooltip>
                    <div className="flex items-center gap-2">
                      {canDecide ? (
                        <>
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
                                onClick={() => setRejectTarget(suggestion)}
                              >
                                Reject
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Dismisses this suggestion without saving it</TooltipContent>
                          </Tooltip>
                        </>
                      ) : (
                        <Badge variant="outline" className="text-[10px] text-muted-foreground">
                          Owner approval required
                        </Badge>
                      )}
                    </div>
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

      {items === null ? (
        <div className="divide-y divide-border rounded-lg border border-border">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-2.5">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="ml-auto h-4 w-24" />
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
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
                    <div className="space-y-1.5">
                      <Skeleton className="h-3.5 w-full" />
                      <Skeleton className="h-3.5 w-11/12" />
                      <Skeleton className="h-3.5 w-3/5" />
                    </div>
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

      <ConfirmDialog
        open={!!rejectTarget}
        onOpenChange={(open) => {
          if (!open) setRejectTarget(null);
        }}
        title="Reject this suggestion?"
        description={
          rejectTarget
            ? `"${rejectTarget.title}" will be dismissed without being added to Firm Knowledge. This cannot be undone.`
            : undefined
        }
        confirmLabel="Reject"
        destructive
        pending={decidingId === rejectTarget?.id}
        onConfirm={async () => {
          if (!rejectTarget) return;
          await decideSuggestion(rejectTarget.id, "reject");
          setRejectTarget(null);
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
