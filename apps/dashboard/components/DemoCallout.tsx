"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { startDemoLogin } from "@/lib/demo-login";

export function DemoCallout() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handleDemoLogin() {
    setLoading(true);
    const result = await startDemoLogin();
    if (result.ok) {
      router.push("/dashboard");
    } else {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-xl rounded-2xl border-2 border-accent/30 bg-accent/5 p-6 text-center shadow-sm ring-1 ring-accent/10">
      <p className="mb-1 flex items-center justify-center gap-1.5 text-sm font-semibold text-accent">
        <Sparkles className="h-4 w-4" />
        See it with real data - no signup
      </p>
      <p className="mb-4 text-sm text-muted-foreground">
        Explore a fully seeded account as one of five real accounting firm types - dental,
        property, general SME advisory, hospitality, or construction/trades - and switch between
        them anytime.
      </p>
      <Button
        size="lg"
        disabled={loading}
        onClick={handleDemoLogin}
        className="bg-accent text-accent-foreground hover:opacity-90"
      >
        {loading ? "Loading demo..." : "Try the live demo"}
      </Button>
    </div>
  );
}
