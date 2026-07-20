import { forwardResponse } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

// The backend /admin/stats endpoint is operator-global, gated behind a static
// X-Admin-Token header rather than a per-user bearer token. There is no
// staff/RBAC role in the app, so this proxy enforces access itself: only a
// signed-in user whose email is in the ADMIN_EMAILS allowlist may reach it.
//
// This is deliberately NOT proxyToBackend - that helper forwards the caller's
// Supabase bearer token and drops query params, neither of which fits here.
// We forward the query string (so ?window= reaches the backend) and inject the
// server-side-only admin token, which must never be exposed to the browser.
export async function GET(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const allowlist = (process.env.ADMIN_EMAILS ?? "")
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean);
  const email = user.email?.toLowerCase();

  if (!email || !allowlist.includes(email)) {
    return Response.json({ error: "Forbidden" }, { status: 403 });
  }

  const searchParams = new URL(request.url).searchParams;
  const query = searchParams.toString();
  const url = `${process.env.NEXT_PUBLIC_API_URL}/admin/stats${query ? `?${query}` : ""}`;

  try {
    const backendResponse = await fetch(url, {
      headers: {
        "X-Admin-Token": process.env.BACKEND_ADMIN_API_TOKEN ?? "",
      },
    });
    return forwardResponse(backendResponse);
  } catch {
    return Response.json(
      { detail: "Service unavailable - please try again shortly" },
      { status: 502 }
    );
  }
}
