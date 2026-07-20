import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET(request: NextRequest) {
  const targetType = request.nextUrl.searchParams.get("target_type") ?? "";
  const targetId = request.nextUrl.searchParams.get("target_id") ?? "";
  const query = new URLSearchParams({ target_type: targetType, target_id: targetId }).toString();
  const response = await proxyToBackend(`/annotations?${query}`);
  return forwardResponse(response);
}

export async function POST(request: Request) {
  const body = await request.text();
  const response = await proxyToBackend("/annotations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}
