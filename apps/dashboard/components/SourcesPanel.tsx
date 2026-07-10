"use client";

import { ExternalLink, FileText } from "lucide-react";

export interface SourceCitation {
  citation: string;
  url: string;
  excerpt: string;
}

interface SourcesPanelProps {
  citations: SourceCitation[];
}

export function SourcesPanel({ citations }: SourcesPanelProps) {
  return (
    <div className="flex h-full w-72 shrink-0 flex-col border-l border-border">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <FileText className="size-4 text-muted-foreground" />
        <span className="text-sm font-semibold text-foreground">Sources</span>
        {citations.length > 0 && (
          <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {citations.length}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {citations.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">
            Sources will appear here once an answer is ready.
          </p>
        ) : (
          <ol className="space-y-3">
            {citations.map((c, i) => (
              <li
                key={i}
                id={`source-${i + 1}`}
                className="scroll-mt-4 rounded-lg border border-border p-3 text-xs target:border-accent target:bg-accent/5"
              >
                <div className="mb-1 flex items-start gap-1.5">
                  <span className="mt-0.5 shrink-0 font-semibold text-accent">{i + 1}</span>
                  <p className="font-medium text-foreground">{c.citation}</p>
                </div>
                <p className="mb-2 text-muted-foreground">{c.excerpt}</p>
                {c.url && (
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-accent hover:underline"
                  >
                    View source
                    <ExternalLink className="size-3" />
                  </a>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
