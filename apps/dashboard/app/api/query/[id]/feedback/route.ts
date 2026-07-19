import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

// C9: answer feedback control. Forwards {rating: "up"|"down", note?} to the
// backend `POST /query/{id}/feedback`. A thumbs-down WITH a note enqueues an
// async re-research (C2); a thumbs-up creates a pending firm-knowledge
// suggestion (C5). The backend response echoes the existing feedback shape plus
// `re_research_enqueued: bool`.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.text();
  const response = await proxyToBackend(`/query/${id}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}
