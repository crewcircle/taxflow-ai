"use client";

import { useState } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { startDemoLogin } from "@/lib/demo-login";

const PERSONAS = [
  { value: "dental", label: "Coogee Bay Dental Group" },
  { value: "property", label: "Riverside Property Partners" },
  { value: "accounting", label: "Chen & Associates" },
  { value: "hospitality", label: "Enmore Hospitality Accountants" },
  { value: "construction", label: "Nepean Tradie Accountants" },
];

// RBAC role switcher (Phase 1): lets a demo visitor see how the SAME
// dashboard looks and behaves for each role - Owner (full access), Reviewer
// (can approve, can't manage billing/staff), Staff (everyday use, no
// approve). Not every persona has a seeded Reviewer/Staff login yet; the
// backend falls back to any demo persona that does rather than erroring, so
// switching role can also switch which firm you're viewing - the header
// re-renders with the new firm's name either way.
const ROLES = [
  { value: "owner", label: "Owner" },
  { value: "reviewer", label: "Reviewer" },
  { value: "staff", label: "Staff" },
];

export function DemoPersonaSwitcher({
  currentType,
  currentRole,
}: {
  currentType: string;
  currentRole: "owner" | "reviewer" | "staff";
}) {
  const [switching, setSwitching] = useState(false);

  async function handleChange(persona: string, role: string) {
    if (persona === currentType && role === currentRole) return;
    setSwitching(true);
    const result = await startDemoLogin(persona, role);
    if (result.ok) {
      window.location.reload();
    } else {
      setSwitching(false);
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <Select value={currentType} onValueChange={(v) => handleChange(v, currentRole)} disabled={switching}>
        <SelectTrigger size="sm" className="h-7 w-[190px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="end">
          {PERSONAS.map((p) => (
            <SelectItem key={p.value} value={p.value}>
              {p.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={currentRole} onValueChange={(v) => handleChange(currentType, v)} disabled={switching}>
        <SelectTrigger size="sm" className="h-7 w-[100px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="end">
          {ROLES.map((r) => (
            <SelectItem key={r.value} value={r.value}>
              {r.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
