import { forwardResponse, proxyToBackend } from "@/lib/api";

// C8: approve a pending suggestion into authoritative firm knowledge.
export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/firm-knowledge/suggestions/${id}/approve`, {
    method: "POST",
  });
  return forwardResponse(response);
}
