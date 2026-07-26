"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { citationColor, citationReference, type SourceCitation } from "@/components/SourcesPanel";

const STALE_AFTER_DAYS = 30;

function daysSince(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

function formatRefreshedDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-AU", { year: "numeric", month: "short" });
}

// react-markdown treats "[1]" as plain text (it isn't valid link syntax on
// its own) - rewrite citation markers into real markdown links pointing at
// the matching source anchor before handing the text to the renderer.
export function linkifyCitations(text: string): string {
  return text.replace(/\[(\d+)\]/g, "[[$1]](#source-$1)");
}

// Shared ReactMarkdown component config, extracted from query/page.tsx so the
// query answer AND the in-app document viewer render identically. Citations are
// optional: with a citations array, `#source-N` links get the currency tooltip
// + stale dot; without one (plain documents), links render as normal anchors.
//
// Every citation marker in the answer carries its own currency, not just the
// sources panel off to the side - the mechanism (last_scraped_at) already
// existed but wasn't visible at the point a reader actually relies on it. Fresh
// citations get a quiet hover date; stale ones (30+ days) also get an amber dot
// so the flag is visible without hovering.
export function buildMarkdownComponents(citations?: SourceCitation[]): Components {
  return {
    h1: ({ children }) => <h3 className="mt-4 mb-1.5 text-base font-semibold first:mt-0">{children}</h3>,
    h2: ({ children }) => <h3 className="mt-4 mb-1.5 text-base font-semibold first:mt-0">{children}</h3>,
    h3: ({ children }) => <h4 className="mt-3 mb-1 text-sm font-semibold first:mt-0">{children}</h4>,
    p: ({ children }) => <p className="mb-2 text-sm leading-relaxed last:mb-0">{children}</p>,
    ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 text-sm">{children}</ul>,
    ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 text-sm">{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
    code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 text-xs">{children}</code>,
    table: ({ children }) => (
      <div className="mb-2 overflow-x-auto">
        <table className="w-full border-collapse text-sm">{children}</table>
      </div>
    ),
    th: ({ children }) => <th className="border border-border px-2 py-1 text-left font-semibold">{children}</th>,
    td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
    a: ({ href, children }) => {
      const match = typeof href === "string" ? href.match(/^#source-(\d+)$/) : null;
      if (!match || !citations) {
        return (
          <a href={href} className="font-medium text-accent hover:underline">
            {children}
          </a>
        );
      }
      const num = Number(match[1]);
      const citation = citations[num - 1];
      const refreshedIso = citation?.last_scraped_at ?? null;
      const stale = refreshedIso ? daysSince(refreshedIso) > STALE_AFTER_DAYS : false;
      const color = citationColor(num);
      // Reliance posture (business audit P1): a superseded/historical source
      // or the firm's own engagement memo used to look identical to a
      // current official source inline - only the trace panel's detail
      // toggle told them apart. Historical gets a solid amber ring (can't
      // miss it); an engagement memo gets a dashed outline instead of a
      // solid fill (it's the firm's own note, not a published authority) -
      // both distinguishable at a glance, not just on hover.
      const badgeStyle = citation?.is_historical
        ? cn(color.bg, color.text, "ring-2 ring-amber-500")
        : citation?.is_engagement_memo
          ? cn("border border-dashed bg-transparent", color.text, color.border)
          : cn(color.bg, color.text);
      // Same color as this citation's card in SourcesPanel (see
      // citationColor) - a superscript badge rather than inline "[1]" text,
      // so which passage came from which source reads as a color match
      // without following the link and comparing text.
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <a
              href={href}
              className={cn(
                "ml-0.5 inline-flex h-3.5 min-w-3.5 items-center justify-center rounded-full px-1 align-super text-[9px] font-bold no-underline",
                badgeStyle
              )}
            >
              {num}
            </a>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            {citation ? (
              <>
                <span className="block font-semibold">{citationReference(citation)}</span>
                {citation.is_historical && (
                  <span className="mt-1 block text-xs text-amber-300">
                    Historical{citation.superseded_by ? ` — superseded by ${citation.superseded_by}` : ""} - do
                    not treat as current law
                  </span>
                )}
                {citation.is_engagement_memo && (
                  <span className="mt-1 block text-xs text-muted-foreground">
                    Your firm&apos;s own note from a past engagement, not an official published source
                  </span>
                )}
                {stale && !citation.is_historical && (
                  <span className="mt-1 block text-xs text-amber-300">
                    Refreshed {refreshedIso ? formatRefreshedDate(refreshedIso) : "a while ago"} - check for a
                    newer version
                  </span>
                )}
              </>
            ) : (
              "Source unavailable"
            )}
          </TooltipContent>
        </Tooltip>
      );
    },
  };
}

// Shared markdown renderer. Pass `citations` to enable citation linkification +
// currency tooltips (query answers); omit it for plain documents.
export function MarkdownDocument({
  text,
  citations,
}: {
  text: string;
  citations?: SourceCitation[];
}) {
  return (
    <div>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents(citations)}>
        {citations ? linkifyCitations(text) : text}
      </ReactMarkdown>
    </div>
  );
}
