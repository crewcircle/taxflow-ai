import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET(request: NextRequest) {
  const firmClientId = request.nextUrl.searchParams.get("firm_client_id");
  const status = request.nextUrl.searchParams.get("status");
  const params = new URLSearchParams();
  if (firmClientId) params.set("firm_client_id", firmClientId);
  if (status) params.set("status", status);
  const qs = params.toString();
  const response = await proxyToBackend(`/engagements${qs ? `?${qs}` : ""}`);
  return forwardResponse(response);
}

export async function POST(request: Request) {
  const body = await request.text();
  const response = await proxyToBackend("/engagements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}
