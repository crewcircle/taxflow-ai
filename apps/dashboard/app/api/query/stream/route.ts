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

  const backendResponse = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/query/stream?question=${encodeURIComponent(question)}`,
    {
      headers: { Authorization: `Bearer ${session.access_token}` },
    }
  );

  return new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
