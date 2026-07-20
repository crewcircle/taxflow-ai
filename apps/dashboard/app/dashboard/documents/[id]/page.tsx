"use client";

import { use as usePromise, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { AnnotatableMarkdown } from "@/components/AnnotatableMarkdown";

interface DocumentDetail {
  id: string;
  document_type: string;
  title: string;
  status: string;
  client_ref: string | null;
  content_md: string;
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline"> = {
  draft: "outline",
  approved: "secondary",
  sent: "default",
  archived: "outline",
};

export default function DocumentViewerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = usePromise(params);
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/documents/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setDoc)
      .catch((e) => setError(e.message === "404" ? "Document not found" : "Could not load document"));
  }, [id]);

  if (error) {
    return (
      <div className="space-y-3">
        <Link href="/dashboard/documents" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" /> All documents
        </Link>
        <p className="text-sm text-destructive">{error}</p>
      </div>
    );
  }

  if (!doc) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link
            href="/dashboard/documents"
            className="mb-1.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" /> All documents
          </Link>
          <h1 className="text-xl font-semibold">{doc.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">{doc.document_type}</Badge>
            <Badge variant={STATUS_VARIANT[doc.status] ?? "outline"}>{doc.status}</Badge>
            {doc.client_ref && <span>· {doc.client_ref}</span>}
            <span>· Created {new Date(doc.created_at).toLocaleDateString("en-AU")}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <a
            href={`/api/documents/${doc.id}/download?fmt=docx`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-muted"
          >
            <Download className="size-3.5" /> .docx
          </a>
          <a
            href={`/api/documents/${doc.id}/download?fmt=pdf`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-muted"
          >
            <Download className="size-3.5" /> .pdf
          </a>
        </div>
      </div>

      <div className="rounded-xl border border-border p-6">
        <AnnotatableMarkdown
          targetType="document"
          targetId={doc.id}
          sourceMarkdown={doc.content_md ?? ""}
        />
      </div>
    </div>
  );
}
