"use client";

import { useEffect, useRef, useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

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

      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center gap-4 py-4 text-center">
          <Upload className="size-6 text-muted-foreground" />
          <input ref={fileInput} type="file" accept=".pdf,.docx,.txt" className="text-sm" />
          <Button onClick={handleUpload} disabled={uploading}>
            {uploading ? "Uploading..." : "Upload document"}
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

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
              <Button variant="link" size="sm" className="text-destructive" onClick={() => handleDelete(item.id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
