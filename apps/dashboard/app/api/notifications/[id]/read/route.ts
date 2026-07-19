import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/notifications/${id}/read`, { method: "POST" });
  return forwardResponse(response);
}
