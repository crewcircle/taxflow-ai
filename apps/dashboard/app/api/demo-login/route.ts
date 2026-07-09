import { NextResponse } from "next/server";

export async function POST() {
  try {
    const backendResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/demo-login`, {
      method: "POST",
    });
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
