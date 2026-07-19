import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET(request: NextRequest) {
  const search = request.nextUrl.searchParams.get("search");
  const path = search ? `/firm-clients?search=${encodeURIComponent(search)}` : "/firm-clients";
  const response = await proxyToBackend(path);
  return forwardResponse(response);
}
