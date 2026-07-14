"use client";

import { useState } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { startDemoLogin } from "@/lib/demo-login";

const PERSONAS = [
  { value: "dental", label: "Bayside Dental Group" },
  { value: "property", label: "Riverside Property Partners" },
  { value: "accounting", label: "Chen & Associates" },
];

export function DemoPersonaSwitcher({ currentType }: { currentType: string }) {
  const [switching, setSwitching] = useState(false);

  async function handleChange(value: string) {
    if (value === currentType) return;
    setSwitching(true);
    const result = await startDemoLogin(value);
    if (result.ok) {
      window.location.reload();
    } else {
      setSwitching(false);
    }
  }

  return (
    <Select value={currentType} onValueChange={handleChange} disabled={switching}>
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
  );
}
