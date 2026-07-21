"use client";

import { useEffect, useState } from "react";
import { Users } from "lucide-react";

interface ClientDirectoryEntry {
  id: string;
  name: string;
  query_count: number;
  document_count: number;
  last_activity: string | null;
}

function formatLastActivity(iso: string | null): string {
  if (!iso) return "No activity yet";
  const date = new Date(iso);
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString("en-AU", { year: "numeric", month: "short", day: "numeric" });
}

// A real, browsable client list (Nisho's #5 recommendation) - the sidebar's
// "highlight by client" text filter only dims/undims a flat question list,
// which doesn't scale once a firm has hundreds of clients on file. This reads
// straight from firm_clients (the register the P0 client-picker fix made
// consistent) joined against actual query/document counts, so a principal can
// see "who have we done work for" as a list, not by scanning history.
export function ClientDirectory({ onSelectClient }: { onSelectClient: (name: string) => void }) {
  const [clients, setClients] = useState<ClientDirectoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/firm-clients/directory")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setClients)
      .catch(() => setError("Could not load your client list"));
  }, []);

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!clients) return <p className="text-sm text-muted-foreground">Loading...</p>;

  if (clients.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-12 text-center">
        <Users className="size-6 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          No clients yet - clients are added automatically the first time you tag a question or
          document to one.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted text-xs text-muted-foreground">
          <tr>
            <th className="px-4 py-2 text-left font-medium">Client</th>
            <th className="px-4 py-2 text-left font-medium">Questions</th>
            <th className="px-4 py-2 text-left font-medium">Documents</th>
            <th className="px-4 py-2 text-left font-medium">Last activity</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {clients.map((c) => (
            <tr
              key={c.id}
              onClick={() => onSelectClient(c.name)}
              className="cursor-pointer hover:bg-muted/50"
            >
              <td className="px-4 py-2.5 font-medium text-foreground">{c.name}</td>
              <td className="px-4 py-2.5 text-muted-foreground">{c.query_count}</td>
              <td className="px-4 py-2.5 text-muted-foreground">{c.document_count}</td>
              <td className="px-4 py-2.5 text-muted-foreground">
                {formatLastActivity(c.last_activity)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
