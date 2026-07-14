import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const persona = request.nextUrl.searchParams.get("persona");
    const url = `${process.env.NEXT_PUBLIC_API_URL}/auth/demo-login${
      persona ? `?persona=${encodeURIComponent(persona)}` : ""
    }`;
    const backendResponse = await fetch(url, { method: "POST" });
    const data = await backendResponse.text();
    return new NextResponse(data, {
      status: backendResponse.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json(
      { detail: "Demo login unavailable - please try again shortly" },
      { status: 502 }
    );
  }
}
