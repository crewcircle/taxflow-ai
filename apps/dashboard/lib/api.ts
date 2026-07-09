import { createClient } from "@/lib/supabase/server";

// Server-side proxy helper: forwards a request to the FastAPI backend with the
// current user's Supabase access token, and mirrors the response back verbatim.
export async function proxyToBackend(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const backendResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}${path}`, {
      ...init,
      headers: {
        ...init.headers,
        Authorization: `Bearer ${session.access_token}`,
      },
    });
    return backendResponse;
  } catch {
    return Response.json(
      { detail: "Service unavailable - please try again shortly" },
      { status: 502 }
    );
  }
}
