import { forwardResponse, proxyToBackend } from "@/lib/api";

export async function POST(_request: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const response = await proxyToBackend(
    `/settings/templates/${encodeURIComponent(key)}/reset-to-default`,
    { method: "POST" },
  );
  return forwardResponse(response);
}
