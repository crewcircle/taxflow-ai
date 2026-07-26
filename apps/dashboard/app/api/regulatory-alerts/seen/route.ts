import { forwardResponse, proxyToBackend } from "@/lib/api";

// Server-side "seen" cursor for the regulatory alert feed - replaces the old
// per-browser localStorage marker so it follows the user across devices,
// like every other notification kind already does.
export async function GET() {
  const response = await proxyToBackend("/regulatory-alerts/seen");
  return forwardResponse(response);
}

export async function POST() {
  const response = await proxyToBackend("/regulatory-alerts/seen", { method: "POST" });
  return forwardResponse(response);
}
