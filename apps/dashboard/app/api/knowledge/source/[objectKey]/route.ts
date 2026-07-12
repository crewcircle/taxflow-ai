import { proxyToBackend } from "@/lib/api";

export async function GET(_request: Request, { params }: { params: Promise<{ objectKey: string }> }) {
  const { objectKey } = await params;
  const response = await proxyToBackend(`/knowledge/source/${objectKey}`);
  return new Response(response.body, { status: response.status, headers: response.headers });
}
