import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET() {
  const response = await proxyToBackend("/query/sessions");
  return forwardResponse(response);
}
