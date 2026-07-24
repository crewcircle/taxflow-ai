import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const persona = request.nextUrl.searchParams.get("persona");
    const role = request.nextUrl.searchParams.get("role");
    const params = new URLSearchParams();
    if (persona) params.set("persona", persona);
    if (role) params.set("role", role);
    const query = params.toString();
    const url = `${process.env.NEXT_PUBLIC_API_URL}/auth/demo-login${query ? `?${query}` : ""}`;
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
