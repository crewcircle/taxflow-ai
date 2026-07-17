"use client";

import { useEffect, useRef, useState, use as usePromise } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { PDFDocumentProxy, PDFPageProxy, TextItem } from "pdfjs-dist/types/src/display/api";

// Loose match: normalise whitespace and compare a leading slice of the
// excerpt, since PDF text extraction can differ slightly in spacing from
// the chunk text stored at ingestion time.
function normalise(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLowerCase();
}

export default function SourceViewerPage({
  params,
  searchParams,
}: {
  params: Promise<{ objectKey: string }>;
  searchParams: Promise<{ excerpt?: string; citation?: string }>;
}) {
  const { objectKey } = usePromise(params);
  const { excerpt, citation } = usePromise(searchParams);

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

        let foundPage: number | null = null;

        for (let pageNum = 1; pageNum <= doc.numPages; pageNum++) {
          const page: PDFPageProxy = await doc.getPage(pageNum);
          const viewport = page.getViewport({ scale: 1.5 });

          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.className = "block border border-border shadow-sm";
          const ctx = canvas.getContext("2d");
          if (!ctx) continue;
          await page.render({ canvas, canvasContext: ctx, viewport }).promise;

          // "relative" so highlight overlays below can be positioned with
          // simple viewport-pixel coordinates, scoped to this page only.
          const pageWrapper = document.createElement("div");
          pageWrapper.className = "relative mx-auto mb-4 w-fit";
          pageWrapper.dataset.page = String(pageNum);
          pageWrapper.appendChild(canvas);
          container.appendChild(pageWrapper);

          if (needle && !foundPage) {
            const textContent = await page.getTextContent();
            const items = textContent.items as TextItem[];
            const pageText = normalise(items.map((i) => i.str).join(" "));
            const matchIndex = pageText.indexOf(needle);
            if (matchIndex !== -1) {
              foundPage = pageNum;
              // Find which text items overlap the matched slice by walking
              // items and accumulating normalised length until we cover the
              // match range, then convert each overlapping item's bounding
              // box into viewport (pixel) coordinates for the highlight.
              let cursor = 0;
              const matchEnd = matchIndex + needle.length;
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
          }
        }

        setMatchedPage(foundPage);
        setStatus("ready");

        if (foundPage) {
          const target = container.querySelector(`[data-page="${foundPage}"]`);
          target?.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      } catch {
        setStatus("error");
      }
    })();
  }, [objectKey, excerpt]);

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      <div className="mb-4 flex items-center justify-between border-b border-border pb-3">
        <div>
          <Link
            href="/dashboard/query"
            className="mb-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3" />
            Back to your question
          </Link>
          <h1 className="text-lg font-semibold">{citation ?? "Source document"}</h1>
          {excerpt && (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              Looking for: <span className="italic">&ldquo;{excerpt}&rdquo;</span>
            </p>
          )}
        </div>
        {status === "ready" && (
          <p className="text-xs text-muted-foreground">
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
