import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET() {
  const response = await proxyToBackend("/settings/me");
  return forwardResponse(response);
}

export async function PATCH(request: Request) {
  const body = await request.text();
  const response = await proxyToBackend("/settings/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}
