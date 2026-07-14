import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function POST(request: Request) {
  const body = await request.text();
  const response = await proxyToBackend("/documents/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}
