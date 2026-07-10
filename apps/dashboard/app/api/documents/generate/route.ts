import { proxyToBackend } from "@/lib/api";

export async function POST(request: Request) {
  const body = await request.text();
  const response = await proxyToBackend("/documents/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return new Response(response.body, { status: response.status, headers: response.headers });
}
