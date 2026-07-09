"use client";

import { useEffect, useRef, useState } from "react";

interface KnowledgeRow {
  id: string;
  file_name: string;
  file_type: string;
  usage_count: number;
  created_at: string;
}

export default function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeRow[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  function load() {
    fetch("/api/firm-knowledge")
      .then((r) => (r.ok ? r.json() : []))
      .then(setItems)
      .catch(() => {});
  }

  useEffect(load, []);

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

      <div className="rounded-lg border border-dashed border-border p-6 text-center">
        <input ref={fileInput} type="file" accept=".pdf,.docx,.txt" className="mx-auto block text-sm" />
        <button
          onClick={handleUpload}
          disabled={uploading}
          className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-all duration-200 hover:bg-accent disabled:opacity-50"
        >
          {uploading ? "Uploading..." : "Upload document"}
        </button>
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No documents uploaded yet.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {items.map((item) => (
            <li key={item.id} className="flex items-center justify-between px-4 py-2">
              <div>
                <p className="font-medium">{item.file_name}</p>
                <p className="text-xs text-muted-foreground">
                  {item.file_type.toUpperCase()} · used in {item.usage_count} answers
                </p>
              </div>
              <button
                onClick={() => handleDelete(item.id)}
                className="text-xs text-destructive hover:underline"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
