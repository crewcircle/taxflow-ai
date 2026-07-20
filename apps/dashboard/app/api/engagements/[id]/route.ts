import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/engagements/${id}`);
  return forwardResponse(response);
}
