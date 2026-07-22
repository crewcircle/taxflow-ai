"use client";

import { use as usePromise } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { SourceDocumentViewer } from "@/components/SourceDocumentViewer";

// Kept as a thin wrapper around SourceDocumentViewer for direct/bookmarked
// links - the normal path is now the in-app modal opened from SourcesPanel.
export default function SourceViewerPage({
  params,
  searchParams,
}: {
  params: Promise<{ objectKey: string }>;
  searchParams: Promise<{ excerpt?: string; citation?: string }>;
}) {
  const { objectKey } = usePromise(params);
  const { excerpt, citation } = usePromise(searchParams);

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      <Link
        href="/dashboard/query"
        className="mb-3 flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3" />
        Back to your question
      </Link>
      <SourceDocumentViewer objectKey={objectKey} excerpt={excerpt} citation={citation} />
    </div>
  );
}
