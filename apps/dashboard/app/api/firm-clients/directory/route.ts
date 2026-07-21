import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET() {
  const response = await proxyToBackend("/firm-clients/directory");
  return forwardResponse(response);
}
