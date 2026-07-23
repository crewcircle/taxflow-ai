// Client-side mirror of the backend's fixed-role permission matrix
// (apps/backend/src/taxflow/rbac.py). This gates VIEW/UX only — hide/disable
// controls a role can't use — the real enforcement is server-side via
// require_permission on each endpoint. Same three-tier shape as lib/admin.ts's
// isOperatorEmail: one small pure function per capability, single-sourced.
export type Role = "owner" | "reviewer" | "staff";

export function canManageBilling(role?: Role | null): boolean {
  return role === "owner";
}

export function canManageStaff(role?: Role | null): boolean {
  return role === "owner";
}

export function canApprove(role?: Role | null): boolean {
  return role === "owner" || role === "reviewer";
}

export function canDeleteAnyWork(role?: Role | null): boolean {
  return role === "owner";
}
