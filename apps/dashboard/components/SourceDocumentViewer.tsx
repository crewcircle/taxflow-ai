"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy, PDFPageProxy, TextItem } from "pdfjs-dist/types/src/display/api";

// Loose match: normalise whitespace and compare a leading slice of the
// excerpt, since PDF text extraction can differ slightly in spacing from
// the chunk text stored at ingestion time.
function normalise(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLowerCase();
}

// Renders a stored source PDF, auto-scrolled and highlighted to the passage
// a citation actually quoted. Extracted from the old standalone
// /dashboard/sources/[objectKey] page so it can also render inline in a
// Dialog (clicking a citation name in SourcesPanel) instead of only as a
// full-page, new-tab navigation.
export function SourceDocumentViewer({
  objectKey,
  excerpt,
  citation,
}: {
  objectKey: string;
  excerpt?: string;
  citation?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [pageCount, setPageCount] = useState(0);
  const [matchedPage, setMatchedPage] = useState<number | null>(null);
  const hasRun = useRef(false);

  useEffect(() => {
    if (hasRun.current) return;
    hasRun.current = true;

    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url
        ).toString();

        const doc: PDFDocumentProxy = await pdfjs.getDocument({
          url: `/api/knowledge/source/${objectKey}`,
        }).promise;
        setPageCount(doc.numPages);

        const needle = excerpt ? normalise(excerpt).slice(0, 60) : null;
        const container = containerRef.current;
        if (!container) return;

        // Pass 1: text-only scan (no rendering) to find the matched page fast.
        // Rendering every page's canvas before the one we actually need is
        // what made a 20+ page ruling take ages to reach its highlight - text
        // extraction alone is a fraction of the cost of a full canvas render.
        let foundPage: number | null = null;
        const pageTextCache = new Map<number, TextItem[]>();
        if (needle) {
          for (let pageNum = 1; pageNum <= doc.numPages; pageNum++) {
            const page: PDFPageProxy = await doc.getPage(pageNum);
            const textContent = await page.getTextContent();
            const items = textContent.items as TextItem[];
            pageTextCache.set(pageNum, items);
            const pageText = normalise(items.map((i) => i.str).join(" "));
            if (pageText.indexOf(needle) !== -1) {
              foundPage = pageNum;
              break;
            }
          }
        }

        async function renderPage(pageNum: number) {
          const page: PDFPageProxy = await doc.getPage(pageNum);
          const viewport = page.getViewport({ scale: 1.5 });

          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.className = "block border border-border shadow-sm";
          const ctx = canvas.getContext("2d");
          if (!ctx) return;
          await page.render({ canvas, canvasContext: ctx, viewport }).promise;

          // "relative" so highlight overlays below can be positioned with
          // simple viewport-pixel coordinates, scoped to this page only.
          const pageWrapper = document.createElement("div");
          pageWrapper.className = "relative mx-auto mb-4 w-fit";
          pageWrapper.dataset.page = String(pageNum);
          pageWrapper.appendChild(canvas);

          if (pageNum === foundPage) {
            const items = pageTextCache.get(pageNum) ?? (await page.getTextContent()).items as TextItem[];
            const pageText = normalise(items.map((i) => i.str).join(" "));
            const matchIndex = pageText.indexOf(needle!);
            // Find which text items overlap the matched slice by walking
            // items and accumulating normalised length until we cover the
            // match range, then convert each overlapping item's bounding
            // box into viewport (pixel) coordinates for the highlight.
            let cursor = 0;
            const matchEnd = matchIndex + needle!.length;
            for (const item of items) {
              const itemLen = normalise(item.str).length + 1;
              const itemStart = cursor;
              const itemEnd = cursor + itemLen;
              cursor = itemEnd;
              if (itemEnd < matchIndex || itemStart > matchEnd) continue;
              const tx = pdfjs.Util.transform(viewport.transform, item.transform);
              const height = Math.hypot(tx[2], tx[3]);
              const width = item.width * viewport.scale;
              const highlight = document.createElement("div");
              highlight.className =
                "pointer-events-none absolute rounded-sm bg-amber-300/50 ring-2 ring-amber-400";
              highlight.style.left = `${tx[4]}px`;
              highlight.style.top = `${tx[5] - height}px`;
              highlight.style.width = `${width}px`;
              highlight.style.height = `${height}px`;
              pageWrapper.appendChild(highlight);
            }
          }

          return pageWrapper;
        }

        // Render the matched page (or page 1) first so the reader sees the
        // relevant passage immediately, then fill in the rest in order.
        const priorityPage = foundPage ?? 1;
        const priorityWrapper = await renderPage(priorityPage);
        if (priorityWrapper) container.appendChild(priorityWrapper);

        setMatchedPage(foundPage);
        setStatus("ready");

        if (foundPage) {
          // Scroll to the highlight itself, not just the page wrapper - a
          // rendered page (scale 1.5) is routinely taller than the viewport,
          // so centering the wrapper can leave the actual highlighted line
          // off-screen when it sits low on the page.
          const pageEl = container.querySelector(`[data-page="${foundPage}"]`);
          const highlightEl = pageEl?.querySelector(".bg-amber-300\\/50");
          (highlightEl ?? pageEl)?.scrollIntoView({ behavior: "smooth", block: "center" });
        }

        // Fill in the rest of the document AFTER the initial scroll fires.
        // Forward pages append below the priority page - harmless, nothing
        // above the viewport moves. Backward pages must be PREPENDED, which
        // would otherwise push the priority page (and the in-flight smooth
        // scroll targeting it) further down the container; compensate by
        // shifting scrollTop by the inserted height so the visible position
        // never moves.
        for (let pageNum = priorityPage + 1; pageNum <= doc.numPages; pageNum++) {
          const wrapper = await renderPage(pageNum);
          if (wrapper) container.appendChild(wrapper);
        }
        const scrollParent = container.parentElement;
        for (let pageNum = priorityPage - 1; pageNum >= 1; pageNum--) {
          const wrapper = await renderPage(pageNum);
          if (!wrapper) continue;
          const prevScrollTop = scrollParent?.scrollTop ?? 0;
          const prevHeight = container.scrollHeight;
          container.insertBefore(wrapper, container.firstChild);
          if (scrollParent) {
            scrollParent.scrollTop = prevScrollTop + (container.scrollHeight - prevHeight);
          }
        }
      } catch {
        setStatus("error");
      }
    })();
  }, [objectKey, excerpt]);

  return (
    <div className="flex h-[75vh] flex-col">
      <div className="mb-3 flex items-center justify-between border-b border-border pb-3">
        <div>
          <h2 className="text-base font-semibold">{citation ?? "Source document"}</h2>
          {excerpt && (
            <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
              Looking for: <span className="italic">&ldquo;{excerpt}&rdquo;</span>
            </p>
          )}
        </div>
        {status === "ready" && (
          <p className="shrink-0 text-xs text-muted-foreground">
            {matchedPage
              ? `Highlighted on page ${matchedPage} of ${pageCount}`
              : `${pageCount} page${pageCount === 1 ? "" : "s"} - exact passage not auto-located`}
          </p>
        )}
      </div>

      <div className="relative flex-1 overflow-y-auto">
        {status === "loading" && (
          <p className="p-6 text-sm text-muted-foreground">Loading document…</p>
        )}
        {status === "error" && (
          <p className="p-6 text-sm text-destructive">
            Could not load this source document. It may no longer be available.
          </p>
        )}
        <div ref={containerRef} />
      </div>
    </div>
  );
}
