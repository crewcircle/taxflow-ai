"use client";

import { ExternalLink, FileText } from "lucide-react";

export interface SourceCitation {
  citation: string;
  url: string;
  excerpt: string;
  source_object_key?: string | null;
  last_scraped_at?: string | null;
}

interface SourcesPanelProps {
  citations: SourceCitation[];
}

interface CitationGroup {
  citation: string;
  url: string;
  sourceObjectKey: string | null;
  lastScrapedAt: string | null;
  occurrences: { index: number; excerpt: string }[];
}

function groupByCitation(citations: SourceCitation[]): CitationGroup[] {
  const groups = new Map<string, CitationGroup>();
  citations.forEach((c, i) => {
    const existing = groups.get(c.citation);
    if (existing) {
      existing.occurrences.push({ index: i, excerpt: c.excerpt });
    } else {
      groups.set(c.citation, {
        citation: c.citation,
        url: c.url,
        sourceObjectKey: c.source_object_key ?? null,
        lastScrapedAt: c.last_scraped_at ?? null,
        occurrences: [{ index: i, excerpt: c.excerpt }],
      });
    }
  });
  return Array.from(groups.values());
}

function formatRefreshedDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-AU", { year: "numeric", month: "short" });
}

// Appends the browser-native Text Fragments directive (#:~:text=) so
// Chrome/Edge auto-scroll to and highlight the matching passage on the
// external page - the only highlighting lever available for sources we
// don't hold a copy of. Degrades gracefully (plain link) elsewhere.
function withTextFragment(url: string, excerpt: string): string {
  const words = excerpt.replace(/…$/, "").trim().split(/\s+/).slice(0, 12).join(" ");
  if (!words) return url;
  return `${url}#:~:text=${encodeURIComponent(words)}`;
}

export function SourcesPanel({ citations }: SourcesPanelProps) {
  const groups = groupByCitation(citations);

  return (
    <div className="flex h-full w-64 shrink-0 flex-col border-l border-border" data-tour="sources-panel">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <FileText className="size-4 text-muted-foreground" />
        <span className="text-sm font-semibold text-foreground">Sources</span>
        {groups.length > 0 && (
          <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {groups.length}
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
            {groups.map((group) => (
              <li
                key={group.citation}
                id={`source-${group.occurrences[0].index + 1}`}
                className="scroll-mt-4 rounded-lg border border-border p-3 text-xs target:border-accent target:bg-accent/5"
              >
                <div className="mb-1 flex items-start justify-between gap-1.5">
                  <p className="font-medium text-foreground">{group.citation}</p>
                  {group.occurrences.length > 1 && (
                    <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      cited {group.occurrences.length}×
                    </span>
                  )}
                </div>
                {group.lastScrapedAt && (
                  <p className="mb-1.5 text-[10px] text-muted-foreground">
                    Refreshed {formatRefreshedDate(group.lastScrapedAt)}
                  </p>
                )}
                <div className="mb-2 space-y-1.5">
                  {group.occurrences.map((occ) => (
                    <p key={occ.index} id={`source-${occ.index + 1}`} className="scroll-mt-4 text-muted-foreground">
                      {occ.excerpt}
                    </p>
                  ))}
                </div>
                <div className="flex flex-wrap gap-3">
                  {group.url && (
                    <a
                      href={withTextFragment(group.url, group.occurrences[0].excerpt)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-accent hover:underline"
                    >
                      View source
                      <ExternalLink className="size-3" />
                    </a>
                  )}
                  {group.sourceObjectKey && (
                    <a
                      href={`/dashboard/sources/${group.sourceObjectKey}?${new URLSearchParams({
                        excerpt: group.occurrences[0].excerpt,
                        citation: group.citation,
                      })}`}
                      className="inline-flex items-center gap-1 text-accent hover:underline"
                    >
                      View original PDF - highlighted
                      <ExternalLink className="size-3" />
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
