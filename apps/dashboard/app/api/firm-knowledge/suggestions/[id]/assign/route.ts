import { forwardResponse, proxyToBackend } from "@/lib/api";

// Routes a pending suggestion to an explicit Owner reviewer instead of
// leaving it for "whoever notices the badge". Pass { user_id: null } to
// unassign.
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.text();
  const response = await proxyToBackend(`/firm-knowledge/suggestions/${id}/assign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  return forwardResponse(response);
}
