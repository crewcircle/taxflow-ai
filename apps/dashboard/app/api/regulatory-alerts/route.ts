import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET() {
  const response = await proxyToBackend("/regulatory-alerts");
  return forwardResponse(response);
}
