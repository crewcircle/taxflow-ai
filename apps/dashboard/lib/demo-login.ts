import { createClient } from "@/lib/supabase/client";

// Logs the visitor into the shared demo account with zero email round-trip:
// the backend generates+verifies a Supabase magic link server-side and hands
// back real session tokens, which we apply directly via setSession().
export async function startDemoLogin(): Promise<{ ok: true } | { ok: false; error: string }> {
  try {
    const response = await fetch("/api/demo-login", { method: "POST" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      return { ok: false, error: body.detail ?? "Could not start the demo - please try again" };
    }

    const { access_token, refresh_token } = await response.json();
    const supabase = createClient();
    const { error } = await supabase.auth.setSession({ access_token, refresh_token });
    if (error) throw error;

    return { ok: true };
  } catch {
    return { ok: false, error: "Could not start the demo - please try again" };
  }
}
