"use client";

import { useState } from "react";
import { ExternalLink, FileSearch, FileText, PanelRightClose } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { SourceDocumentViewer } from "@/components/SourceDocumentViewer";
import { cn } from "@/lib/utils";

export interface SourceCitation {
  citation: string;
  url: string;
  excerpt: string;
  // The source's own section/heading (e.g. "75-10 Amount of GST on a
  // taxable supply"), when it has one - lets a reference read as "GST Act,
  // s 75-10 - Amount of GST on a taxable supply" instead of only the bare
  // Act/ruling name.
  section?: string | null;
  source_object_key?: string | null;
  last_scraped_at?: string | null;
}

interface SourcesPanelProps {
  citations: SourceCitation[];
  onHide: () => void;
}

interface CitationGroup {
  citation: string;
  url: string;
  section: string | null;
  sourceObjectKey: string | null;
  lastScrapedAt: string | null;
  occurrences: { index: number; excerpt: string }[];
}

// One color per citation NUMBER (1-indexed, matching the [N] marker in the
// answer), shared between the inline superscript (MarkdownDocument) and this
// panel's excerpt cards, so "which source did this come from" is answerable
// by color alone, not just by following the link and reading. Cycles for
// citation counts beyond the palette rather than introducing a whole
// citation-color-assignment library for what's fundamentally a 6-8 item list
// per answer.
const CITATION_COLORS = [
  { text: "text-blue-700", bg: "bg-blue-50", border: "border-blue-300", dot: "bg-blue-500" },
  { text: "text-emerald-700", bg: "bg-emerald-50", border: "border-emerald-300", dot: "bg-emerald-500" },
  { text: "text-violet-700", bg: "bg-violet-50", border: "border-violet-300", dot: "bg-violet-500" },
  { text: "text-orange-700", bg: "bg-orange-50", border: "border-orange-300", dot: "bg-orange-500" },
  { text: "text-pink-700", bg: "bg-pink-50", border: "border-pink-300", dot: "bg-pink-500" },
  { text: "text-cyan-700", bg: "bg-cyan-50", border: "border-cyan-300", dot: "bg-cyan-500" },
] as const;

export function citationColor(oneIndexedCitationNumber: number) {
  return CITATION_COLORS[(oneIndexedCitationNumber - 1) % CITATION_COLORS.length];
}

// "GST Act, s 75-10 - Amount of GST on a taxable supply" - a proper
// reference to what was actually cited, not the raw legislative text quoted
// from it (that's what the excerpt is for, still visible in the Sources
// panel itself).
export function citationReference(citation: SourceCitation): string {
  return citation.section ? `${citation.citation}, ${citation.section}` : citation.citation;
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
        section: c.section ?? null,
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

export function SourcesPanel({ citations, onHide }: SourcesPanelProps) {
  const groups = groupByCitation(citations);
  // Which stored source is open in the in-app viewer modal (replaces the old
  // "View original PDF - highlighted" link that opened a whole new tab).
  const [openDoc, setOpenDoc] = useState<{ objectKey: string; excerpt: string; citation: string } | null>(null);

  return (
    <div className="flex h-full w-64 shrink-0 flex-col border-l border-border" data-tour="sources-panel">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <FileText className="size-4 text-muted-foreground" />
        <span className="text-sm font-semibold text-foreground">Sources</span>
        {groups.length > 0 && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {groups.length}
          </span>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onHide}
              className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Hide sources"
            >
              <PanelRightClose className="size-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Hide this panel to give the answer more room - click the arrow to bring it back</TooltipContent>
        </Tooltip>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {citations.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">
            Sources will appear here once an answer is ready.
          </p>
        ) : (
          <ol className="space-y-3">
            {groups.map((group) => {
              const color = citationColor(group.occurrences[0].index + 1);
              return (
              <li
                key={group.citation}
                id={`source-${group.occurrences[0].index + 1}`}
                className={cn(
                  "scroll-mt-4 rounded-lg border-l-4 border-y border-r border-border p-3 text-xs target:bg-accent/5",
                  color.border
                )}
              >
                <div className="mb-1 flex items-start justify-between gap-1.5">
                  {group.sourceObjectKey ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          onClick={() =>
                            setOpenDoc({
                              objectKey: group.sourceObjectKey!,
                              excerpt: group.occurrences[0].excerpt,
                              citation: group.citation,
                            })
                          }
                          className="flex items-center gap-1.5 text-left font-medium text-foreground hover:underline"
                        >
                          <span className={cn("inline-block size-2 shrink-0 rounded-full", color.dot)} />
                          {group.citation}
                          <FileSearch className="size-3 shrink-0 text-muted-foreground" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>
                        Opens our stored copy of the PDF here in the app, scrolled to the exact passage cited above
                      </TooltipContent>
                    </Tooltip>
                  ) : (
                    <p className="flex items-center gap-1.5 font-medium text-foreground">
                      <span className={cn("inline-block size-2 shrink-0 rounded-full", color.dot)} />
                      {group.citation}
                    </p>
                  )}
                  {group.occurrences.length > 1 && (
                    <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      cited {group.occurrences.length}×
                    </span>
                  )}
                </div>
                {group.section && (
                  <p className="mb-1.5 text-[11px] text-muted-foreground">{group.section}</p>
                )}
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
                {group.url && (
                  <div className="flex flex-wrap gap-3">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <a
                          href={withTextFragment(group.url, group.occurrences[0].excerpt)}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-accent hover:underline"
                        >
                          View source
                          <ExternalLink className="size-3" />
                        </a>
                      </TooltipTrigger>
                      <TooltipContent>
                        Opens the ATO page this citation came from in a new tab, jumping to the matching text where
                        supported
                      </TooltipContent>
                    </Tooltip>
                  </div>
                )}
              </li>
              );
            })}
          </ol>
        )}
      </div>

      <Dialog open={openDoc != null} onOpenChange={(open) => !open && setOpenDoc(null)}>
        <DialogContent className="sm:max-w-4xl">
          {openDoc && (
            <SourceDocumentViewer
              objectKey={openDoc.objectKey}
              excerpt={openDoc.excerpt}
              citation={openDoc.citation}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
