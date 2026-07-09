"use client";

import { useEffect, useState } from "react";

interface DocumentRow {
  id: string;
  document_type: string;
  title: string;
  status: string;
  created_at: string;
}

const STATUS_STYLE: Record<string, string> = {
  draft: "bg-muted text-muted-foreground",
  approved: "bg-green-50 text-green-800",
  sent: "bg-blue-50 text-blue-800",
  archived: "bg-neutral-100 text-neutral-500",
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
          <table className="w-full text-sm">
            <thead className="bg-muted text-left text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-2">Title</th>
                <th className="px-4 py-2">Type</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Created</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id} className="border-t border-border">
                  <td className="px-4 py-2 font-medium">{doc.title}</td>
                  <td className="px-4 py-2 text-muted-foreground">{doc.document_type}</td>
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[doc.status] ?? ""}`}>
                      {doc.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {new Date(doc.created_at).toLocaleDateString("en-AU")}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <a
                      href={`/api/documents/${doc.id}/download?fmt=docx`}
                      className="text-accent hover:underline"
                    >
                      Download
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
