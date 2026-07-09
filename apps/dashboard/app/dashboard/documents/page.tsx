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

interface DocumentRow {
  id: string;
  document_type: string;
  title: string;
  status: string;
  created_at: string;
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

  useEffect(() => {
    fetch("/api/documents")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setDocuments)
      .catch(() => setError("Could not load documents"));
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Documents</h1>

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
