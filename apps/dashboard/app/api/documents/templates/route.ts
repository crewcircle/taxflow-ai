import { proxyToBackend } from "@/lib/api";

export async function GET() {
  const response = await proxyToBackend("/documents/templates");
  return new Response(response.body, { status: response.status, headers: response.headers });
}
