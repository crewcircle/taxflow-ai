// Single-sourced operator gate. The analytics feature is operator-only, gated
// on the ADMIN_EMAILS allowlist (comma-separated). Both the API proxy
// (app/api/admin/stats/route.ts) and the layout nav-link visibility check use
// this, so the rule lives in exactly one place.
export function isOperatorEmail(email?: string | null): boolean {
  if (!email) return false;
  const allowlist = (process.env.ADMIN_EMAILS ?? "")
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
  return allowlist.includes(email.toLowerCase());
}
