import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/api";

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const response = await proxyToBackend("/firm-knowledge/upload", {
    method: "POST",
    body: formData,
  });
  return new Response(response.body, { status: response.status, headers: response.headers });
}
