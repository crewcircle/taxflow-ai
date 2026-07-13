"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { OnboardingTour } from "@/components/OnboardingTour";
import { startDemoLogin } from "@/lib/demo-login";

interface DashboardIdentityStripProps {
  businessName: string;
  businessType: string;
  isDemo: boolean;
  demoTagline: string | null;
  demoDescription: string | null;
}

function humanizeType(type: string): string {
  return type.replace(/_/g, " ");
}

export function DashboardIdentityStrip({
  businessName,
  businessType,
  isDemo,
  demoTagline,
  demoDescription,
}: DashboardIdentityStripProps) {
  const [switching, setSwitching] = useState(false);

  async function handleSwitch() {
    setSwitching(true);
    const result = await startDemoLogin();
    if (result.ok) {
      window.location.reload();
    } else {
      setSwitching(false);
    }
  }

  if (!isDemo) {
    return (
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-sm">
        <span className="font-medium text-foreground">{businessName}</span>
        <Badge variant="outline" className="text-[10px]">
          {humanizeType(businessType)}
        </Badge>
      </div>
    );
  }

  return (
    <div
      className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2 text-sm"
      data-tour="identity-strip"
    >
      <span className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 text-accent" />
        <span>
          Viewing a live demo as <strong>{businessName}</strong>
        </span>
        <Badge variant="outline" className="text-[10px]">
          {humanizeType(businessType)}
        </Badge>
      </span>
      <div className="flex gap-2">
        <OnboardingTour
          businessName={businessName}
          businessType={businessType}
          demoTagline={demoTagline}
          demoDescription={demoDescription}
          isDemo={isDemo}
        />
        <Button variant="outline" size="sm" disabled={switching} onClick={handleSwitch}>
          {switching ? "Switching..." : "Try a different scenario"}
        </Button>
      </div>
    </div>
  );
}
