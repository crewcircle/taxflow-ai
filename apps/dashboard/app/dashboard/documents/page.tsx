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

interface DocumentRow {
  id: string;
  document_type: string;
  title: string;
  status: string;
  created_at: string;
}

interface DocumentTemplate {
  type: string;
  label: string;
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline"> = {
  draft: "outline",
  approved: "secondary",
  sent: "default",
  archived: "outline",
};

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ title: "", document_type: "advice_memo", content_md: "" });

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

  async function handleCreate() {
    if (!form.title.trim() || !form.content_md.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch("/api/documents/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!response.ok) throw new Error("Failed");
      setForm({ title: "", document_type: "advice_memo", content_md: "" });
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
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Documents</h1>
        <Button size="sm" variant={creating ? "outline" : "default"} onClick={() => setCreating((v) => !v)}>
          {creating ? "Cancel" : "New document"}
        </Button>
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
              <Label htmlFor="doc-content">Content</Label>
              <Textarea
                id="doc-content"
                rows={8}
                value={form.content_md}
                onChange={(e) => setForm({ ...form, content_md: e.target.value })}
                placeholder="Write or paste the document content..."
              />
            </div>
            <Button onClick={handleCreate} disabled={saving || !form.title.trim() || !form.content_md.trim()}>
              {saving ? "Creating..." : "Create document"}
            </Button>
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

      {documents && documents.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => (
                <TableRow key={doc.id}>
                  <TableCell className="font-medium">{doc.title}</TableCell>
                  <TableCell className="text-muted-foreground">{doc.document_type}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[doc.status] ?? "outline"}>{doc.status}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(doc.created_at).toLocaleDateString("en-AU")}
                  </TableCell>
                  <TableCell className="text-right">
                    <a
                      href={`/api/documents/${doc.id}/download?fmt=docx`}
                      className="text-accent hover:underline"
                    >
                      Download
                    </a>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
