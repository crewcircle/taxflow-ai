import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET(request: NextRequest) {
  const search = request.nextUrl.searchParams.get("search");
  const path = search ? `/firm-clients?search=${encodeURIComponent(search)}` : "/firm-clients";
  const response = await proxyToBackend(path);
  return forwardResponse(response);
}

export async function POST(request: Request) {
  const body = await request.text();
  const response = await proxyToBackend("/firm-clients", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}
