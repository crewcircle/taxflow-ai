import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.text();
  const response = await proxyToBackend(`/annotations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}

export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/annotations/${id}`, { method: "DELETE" });
  return forwardResponse(response);
}
