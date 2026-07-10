import { proxyToBackend } from "@/lib/api";

export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await proxyToBackend(`/ato-response/${id}/approve`, { method: "POST" });
  return new Response(response.body, { status: response.status, headers: response.headers });
}
