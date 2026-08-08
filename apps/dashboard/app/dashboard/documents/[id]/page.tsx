"use client";

import { use as usePromise, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { AlertTriangle, ArrowLeft, Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { AnnotatableMarkdown } from "@/components/AnnotatableMarkdown";
import { DOCUMENT_STATUS_VARIANT } from "@/lib/documents";

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
  stale?: boolean;
  stale_since?: string | null;
}

export default function DocumentViewerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = usePromise(params);
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/documents/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setDoc)
      .catch((e) => {
        const message = e.message === "404" ? "Document not found" : "Could not load document";
        setError(message);
        toast.error(message);
      });
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
    return (
      <div className="space-y-4">
        <Skeleton className="h-4 w-32" />
        <div className="space-y-2">
          <Skeleton className="h-7 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
        </div>
        <div className="space-y-3 rounded-xl border border-border p-6">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      </div>
    );
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
            <Badge variant={DOCUMENT_STATUS_VARIANT[doc.status] ?? "outline"}>{doc.status}</Badge>
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

      {doc.stale && (
        <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2.5 text-sm text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            <span className="block font-medium">The underlying research answer has changed since this was generated</span>
            The answer this document came from was re-researched
            {doc.stale_since ? ` on ${new Date(doc.stale_since).toLocaleDateString("en-AU")}` : ""}
            {" "}after this document was created - the content below may no longer match what
            TaxFlow would say today. Worth reviewing before relying on it, especially if it&apos;s
            already been sent to a client.
          </span>
        </div>
      )}

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
