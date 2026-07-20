import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: NextRequest) {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const question = request.nextUrl.searchParams.get("question");
  if (!question) {
    return NextResponse.json({ error: "question required" }, { status: 400 });
  }
  const clientRef = request.nextUrl.searchParams.get("client_ref");
  const sessionId = request.nextUrl.searchParams.get("session_id");
  const engagementId = request.nextUrl.searchParams.get("engagement_id");

  const backendUrl = new URL(`${process.env.NEXT_PUBLIC_API_URL}/query/stream`);
  backendUrl.searchParams.set("question", question);
  if (clientRef) backendUrl.searchParams.set("client_ref", clientRef);
  if (sessionId) backendUrl.searchParams.set("session_id", sessionId);
  if (engagementId) backendUrl.searchParams.set("engagement_id", engagementId);

  const backendResponse = await fetch(backendUrl, {
    headers: { Authorization: `Bearer ${session.access_token}` },
  });

  return new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
