import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const body = await request.text();
  try {
    const backendResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/contact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const data = await backendResponse.text();
    return new NextResponse(data, {
      status: backendResponse.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json({ detail: "Could not send message - please try again" }, { status: 502 });
  }
}
