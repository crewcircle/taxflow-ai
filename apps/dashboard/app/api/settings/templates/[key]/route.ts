import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function PUT(request: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const body = await request.text();
  const response = await proxyToBackend(`/settings/templates/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}

export async function DELETE(_request: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const response = await proxyToBackend(`/settings/templates/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
  return forwardResponse(response);
}
