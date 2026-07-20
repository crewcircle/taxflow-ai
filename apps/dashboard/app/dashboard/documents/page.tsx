"use client";

import { useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ClientAutocomplete } from "@/components/ClientAutocomplete";
import { EngagementPicker, type EngagementSelection } from "@/components/EngagementPicker";
import { ResourceRowActions } from "@/components/resource-actions/ResourceRowActions";
import { ConfirmDialog } from "@/components/resource-actions/ConfirmDialog";
import { ResourceEditDialog } from "@/components/resource-actions/ResourceEditDialog";
import { useResourceMutation } from "@/components/resource-actions/useResourceMutation";

interface DocumentRow {
  id: string;
  document_type: string;
  title: string;
  status: string;
  client_ref: string | null;
  context_note: string | null;
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
  edited_at?: string | null;
}

interface DocumentTemplate {
  type: string;
  label: string;
}

interface StaffMember {
  name: string;
  role: string;
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline"> = {
  draft: "outline",
  approved: "secondary",
  sent: "default",
  archived: "outline",
};

// Internal working paper vs. what actually leaves the firm vs. what goes to
// the ATO - three different audiences, not one flat document list. Matches
// document_graph.py's TEMPLATE_REGISTRY.
type Bucket = "all" | "internal" | "client" | "ato";
const BUCKETS: Record<Exclude<Bucket, "all">, string[]> = {
  internal: ["advice_memo"],
  client: ["client_letter", "engagement_letter"],
  ato: [
    "ato_response",
    "remission_request",
    "objection_letter",
    "private_ruling_application",
    "payg_variation",
    "fbt_declaration",
  ],
};
const BUCKET_LABELS: Record<Bucket, string> = {
  all: "All",
  internal: "Internal",
  client: "Client-facing",
  ato: "ATO-facing",
};

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [clientFilter, setClientFilter] = useState("");
  const [bucket, setBucket] = useState<Bucket>("all");
  const [staffDirectory, setStaffDirectory] = useState<StaffMember[]>([]);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [approvingAs, setApprovingAs] = useState("");
  // Phase 2: optionally attribute a hand-written document to a first-class
  // engagement. Selecting one mirrors the end-client name into form.client_ref.
  const [engagement, setEngagement] = useState<EngagementSelection | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentRow | null>(null);
  const [editTarget, setEditTarget] = useState<
    { id: string; title: string; content_md: string } | null
  >(null);
  const mutation = useResourceMutation({ onSuccess: loadDocuments });
  const [form, setForm] = useState({
    title: "",
    document_type: "advice_memo",
    content_md: "",
    client_ref: "",
  });

  // Header "Documents generated" dropdown deep-links here with ?client=X to
  // pre-select that client's documents.
  useEffect(() => {
    const client = new URLSearchParams(window.location.search).get("client");
    if (!client) return;
    window.history.replaceState(null, "", window.location.pathname);
    const t = setTimeout(() => setClientFilter(client), 0);
    return () => clearTimeout(t);
  }, []);

  function loadDocuments() {
    fetch("/api/documents")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setDocuments)
      .catch(() => setError("Could not load documents"));
  }

  useEffect(loadDocuments, []);

  useEffect(() => {
    fetch("/api/documents/templates")
      .then((r) => (r.ok ? r.json() : []))
      .then(setTemplates)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setStaffDirectory(d?.client?.staff_directory ?? []))
      .catch(() => {});
  }, []);

  async function handleApprove(documentId: string) {
    if (!approvingAs) return;
    try {
      const response = await fetch(`/api/documents/${documentId}/approve`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved_by: approvingAs }),
      });
      if (!response.ok) throw new Error("Failed");
      setApprovingId(null);
      setApprovingAs("");
      loadDocuments();
    } catch {
      setError("Could not approve this document - please try again");
    }
  }

  async function openEdit(documentId: string) {
    // The list row does not carry content_md; fetch the full document first.
    try {
      const res = await fetch(`/api/documents/${documentId}`);
      if (!res.ok) throw new Error("Failed");
      const doc = await res.json();
      setEditTarget({
        id: documentId,
        title: doc.title ?? "",
        content_md: doc.content_md ?? "",
      });
    } catch {
      setError("Could not open this document for editing");
    }
  }

  async function handleCreate() {
    if (!form.title.trim() || !form.content_md.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch("/api/documents/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          client_ref: form.client_ref.trim() || null,
          engagement_id: engagement?.engagement.id ?? null,
        }),
      });
      if (!response.ok) throw new Error("Failed");
      setForm({ title: "", document_type: "advice_memo", content_md: "", client_ref: "" });
      setEngagement(null);
      setCreating(false);
      loadDocuments();
    } catch {
      setError("Could not create this document - please try again");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Documents</h1>
          <p className="text-sm text-muted-foreground">
            Every generated document - advice memos, letters, and approved ATO responses. Draft a new
            ATO reply from ATO Correspondence; anything else, create it here.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {documents && documents.some((d) => d.client_ref) && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Input
                  value={clientFilter}
                  onChange={(e) => setClientFilter(e.target.value)}
                  placeholder="Filter by client..."
                  className="h-8 w-48 text-xs"
                />
              </TooltipTrigger>
              <TooltipContent>Type a client name to show only their documents</TooltipContent>
            </Tooltip>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="sm" variant={creating ? "outline" : "default"} onClick={() => setCreating((v) => !v)}>
                {creating ? "Cancel" : "New document"}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {creating ? "Close this form without saving" : "Write a document from scratch, rather than saving one from a research answer"}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {(Object.keys(BUCKET_LABELS) as Bucket[]).map((b) => (
          <button
            key={b}
            type="button"
            onClick={() => setBucket(b)}
            className={
              bucket === b
                ? "rounded-full bg-foreground px-3 py-1 text-xs font-medium text-background"
                : "rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:border-foreground/40"
            }
          >
            {BUCKET_LABELS[b]}
          </button>
        ))}
      </div>

      {creating && (
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div className="space-y-1.5">
              <Label htmlFor="doc-title">Title</Label>
              <Input
                id="doc-title"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="e.g. Engagement Letter - Smith Dental Practice"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="doc-type">Type</Label>
              <Select
                value={form.document_type}
                onValueChange={(v) => setForm({ ...form, document_type: v })}
              >
                <SelectTrigger id="doc-type" className="w-full">
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
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="doc-client-ref">Client (optional)</Label>
              <div className="flex items-center gap-2">
                <ClientAutocomplete
                  value={form.client_ref}
                  onChange={(v) => setForm({ ...form, client_ref: v })}
                  placeholder="e.g. Smith Dental Practice"
                />
                <EngagementPicker
                  value={engagement}
                  onChange={(selection) => {
                    setEngagement(selection);
                    if (selection) setForm((f) => ({ ...f, client_ref: selection.clientName }));
                  }}
                  triggerLabel="Attach engagement"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="doc-content">Content</Label>
              <Textarea
                id="doc-content"
                rows={8}
                value={form.content_md}
                onChange={(e) => setForm({ ...form, content_md: e.target.value })}
                placeholder="Write or paste the document content..."
              />
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button onClick={handleCreate} disabled={saving || !form.title.trim() || !form.content_md.trim()}>
                  {saving ? "Creating..." : "Create document"}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Saves this as a new document, tagged to the client above if you entered one</TooltipContent>
            </Tooltip>
          </CardContent>
        </Card>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!documents && !error && <p className="text-sm text-muted-foreground">Loading...</p>}
      {documents && documents.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No documents yet - generate one from a research answer or ATO correspondence.
        </p>
      )}

      {documents && documents.length > 0 && (() => {
        let filtered = documents;
        if (bucket !== "all") {
          filtered = filtered.filter((d) => BUCKETS[bucket].includes(d.document_type));
        }
        if (clientFilter.trim()) {
          filtered = filtered.filter((d) => d.client_ref?.toLowerCase().includes(clientFilter.trim().toLowerCase()));
        }
        if (filtered.length === 0) {
          return <p className="text-sm text-muted-foreground">No documents in this view.</p>;
        }
        return (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Client</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell className="max-w-xs font-medium">
                      <span className="block truncate">{doc.title}</span>
                      {doc.context_note && (
                        <span className="block truncate text-xs font-normal text-muted-foreground">
                          {doc.context_note}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {doc.client_ref ? <Badge variant="outline">{doc.client_ref}</Badge> : "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{doc.document_type}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[doc.status] ?? "outline"}>{doc.status}</Badge>
                      {doc.approved_by && doc.approved_at && (
                        <span className="mt-1 block text-[11px] text-muted-foreground">
                          Reviewed and approved by {doc.approved_by} ·{" "}
                          {new Date(doc.approved_at).toLocaleDateString("en-AU")}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(doc.created_at).toLocaleDateString("en-AU")}
                      {doc.edited_at && (
                        <span className="mt-1 block text-[11px] text-muted-foreground">
                          Edited {new Date(doc.edited_at).toLocaleDateString("en-AU")}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-3">
                        {doc.status !== "approved" &&
                          (approvingId === doc.id ? (
                            <div className="flex items-center gap-1.5">
                              <Select value={approvingAs} onValueChange={setApprovingAs}>
                                <SelectTrigger size="sm" className="h-7 w-[150px] text-xs">
                                  <SelectValue placeholder="Sign off as..." />
                                </SelectTrigger>
                                <SelectContent>
                                  {staffDirectory.map((m) => (
                                    <SelectItem key={m.name} value={m.name}>
                                      {m.name} · {m.role}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <Button size="sm" className="h-7 px-2 text-xs" disabled={!approvingAs} onClick={() => handleApprove(doc.id)}>
                                Confirm
                              </Button>
                              <button
                                type="button"
                                className="text-xs text-muted-foreground hover:text-foreground"
                                onClick={() => setApprovingId(null)}
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <button
                                  type="button"
                                  className="text-accent hover:underline disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline"
                                  disabled={staffDirectory.length === 0}
                                  onClick={() => setApprovingId(doc.id)}
                                >
                                  Approve
                                </button>
                              </TooltipTrigger>
                              <TooltipContent>
                                {staffDirectory.length === 0
                                  ? "Add staff in Settings first"
                                  : "Record a reviewed-and-approved-by sign-off on this document"}
                              </TooltipContent>
                            </Tooltip>
                          ))}
                        <ResourceRowActions
                          label="document"
                          actions={{
                            view: () => {
                              window.location.href = `/dashboard/documents/${doc.id}`;
                            },
                            edit: () => openEdit(doc.id),
                            delete: () => setDeleteTarget(doc),
                            download: {
                              docx: `/api/documents/${doc.id}/download?fmt=docx`,
                              pdf: `/api/documents/${doc.id}/download?fmt=pdf`,
                            },
                          }}
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        );
      })()}

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title="Delete document?"
        description={
          deleteTarget
            ? `"${deleteTarget.title}" will be permanently deleted. This cannot be undone.`
            : undefined
        }
        confirmLabel="Delete"
        destructive
        pending={mutation.pending}
        onConfirm={async () => {
          if (!deleteTarget) return;
          const ok = await mutation.remove(
            `/api/documents/${deleteTarget.id}`,
            "Document deleted"
          );
          if (ok) setDeleteTarget(null);
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
            const ok = await mutation.patch(
              `/api/documents/${editTarget.id}`,
              fields,
              "Document updated"
            );
            if (ok) setEditTarget(null);
          }}
        />
      )}
    </div>
  );
}
