import { forwardResponse, proxyToBackend } from "@/lib/api";

// C8: reject a pending suggestion (status only — nothing is written to firm knowledge).
export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/firm-knowledge/suggestions/${id}/reject`, {
    method: "POST",
  });
  return forwardResponse(response);
}
