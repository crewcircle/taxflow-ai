import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const response = await proxyToBackend("/firm-knowledge/upload", {
    method: "POST",
    body: formData,
  });
  return forwardResponse(response);
}
