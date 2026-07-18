import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET() {
  const response = await proxyToBackend("/knowledge/graph");
  return forwardResponse(response);
}
