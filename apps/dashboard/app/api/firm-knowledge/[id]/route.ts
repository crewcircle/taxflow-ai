import { proxyToBackend } from "@/lib/api";

export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/firm-knowledge/${id}`, { method: "DELETE" });
  return new Response(response.body, { status: response.status, headers: response.headers });
}
