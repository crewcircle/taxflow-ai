"use client";

import { useState } from "react";
import Link from "next/link";
import { Settings, LogOut } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { createClient } from "@/lib/supabase/client";

const ROLE_LABEL: Record<"owner" | "reviewer" | "staff", string> = {
  owner: "Owner",
  reviewer: "Reviewer",
  staff: "Staff",
};

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

// Settings + sign out, folded into one top-right menu instead of two
// standalone rows at the bottom of the old vertical sidebar - both are
// account-level actions, not destinations you browse between like the main
// nav links. The trigger used to be a bare generic-person icon with no
// indication of WHICH firm or WHAT role you were signed in as - now an
// initials avatar (matching the same pattern annotation authors already use
// elsewhere in the app) that opens straight onto that identity.
export function AccountMenu({
  businessName,
  role,
  email,
}: {
  businessName: string;
  role: "owner" | "reviewer" | "staff";
  email?: string | null;
}) {
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    window.location.assign("/login");
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-xs font-semibold text-accent transition-colors hover:bg-accent/25"
        >
          {businessName ? initials(businessName) : "?"}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="flex flex-col gap-1 font-normal">
          <span className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-foreground">
              {businessName || "Your firm"}
            </span>
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {ROLE_LABEL[role]}
            </Badge>
          </span>
          {email && <span className="truncate text-xs text-muted-foreground">{email}</span>}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/dashboard/settings" className="flex items-center gap-2">
            <Settings className="size-4" />
            Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={handleSignOut} disabled={signingOut} variant="destructive">
          <LogOut className="size-4" />
          {signingOut ? "Signing out..." : "Sign out"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
