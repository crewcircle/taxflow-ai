import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET() {
  const response = await proxyToBackend("/staff");
  return forwardResponse(response);
}

export async function POST(request: Request) {
  const body = await request.text();
  const response = await proxyToBackend("/staff/invite", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}
