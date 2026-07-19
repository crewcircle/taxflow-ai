import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

// Approval-gated learning loop (Task C5/C8): suggests a research answer for
// firm knowledge rather than writing it directly. A partner approves the
// suggestion before it becomes authoritative firm knowledge.
export async function POST(request: NextRequest) {
  const body = await request.json();
  const response = await proxyToBackend("/firm-knowledge/suggestions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return forwardResponse(response);
}

// C8: list suggestions for the review UI, forwarding the optional ?status filter
// (e.g. ?status=pending) through to the backend list endpoint.
export async function GET(request: NextRequest) {
  const status = request.nextUrl.searchParams.get("status");
  const path = status
    ? `/firm-knowledge/suggestions?status=${encodeURIComponent(status)}`
    : "/firm-knowledge/suggestions";
  const response = await proxyToBackend(path);
  return forwardResponse(response);
}
