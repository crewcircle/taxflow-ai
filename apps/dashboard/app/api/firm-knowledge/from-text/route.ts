import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const response = await proxyToBackend("/firm-knowledge/from-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return forwardResponse(response);
}
