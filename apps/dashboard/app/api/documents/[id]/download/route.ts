import { NextRequest } from "next/server";
import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const fmt = request.nextUrl.searchParams.get("fmt") ?? "docx";
  const response = await proxyToBackend(`/documents/${id}/download?fmt=${fmt}`);
  return forwardResponse(response);
}
