import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/firm-knowledge/${id}`);
  return forwardResponse(response);
}

export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/firm-knowledge/${id}`, { method: "DELETE" });
  return forwardResponse(response);
}
