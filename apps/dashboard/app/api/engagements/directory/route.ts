import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET() {
  const response = await proxyToBackend("/engagements/directory");
  return forwardResponse(response);
}
