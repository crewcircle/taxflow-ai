"use client";

import { useState } from "react";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

export function SignOutButton({ collapsed }: { collapsed?: boolean } = {}) {
  const [loading, setLoading] = useState(false);

  async function handleSignOut() {
    setLoading(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    window.location.assign("/login");
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={handleSignOut}
      disabled={loading}
      title={collapsed ? "Sign out" : undefined}
      className={collapsed ? "justify-center px-2" : "justify-start"}
    >
      <LogOut className="size-4" />
      {!collapsed && (loading ? "Signing out..." : "Sign out")}
    </Button>
  );
}
