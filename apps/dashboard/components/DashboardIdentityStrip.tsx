"use client";

import { useState } from "react";
import { Info, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { startDemoLogin } from "@/lib/demo-login";

interface DashboardIdentityStripProps {
  businessName: string;
  businessType: string;
  isDemo: boolean;
  demoTagline: string | null;
}

function humanizeType(type: string): string {
  return type.replace(/_/g, " ");
}

export function DashboardIdentityStrip({
  businessName,
  businessType,
  isDemo,
  demoTagline,
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

  if (isDemo) {
    return (
      <TooltipProvider>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2 text-sm">
          <span className="flex flex-wrap items-center gap-2">
            <Sparkles className="size-4 text-accent" />
            <span>
              Viewing a live demo as <strong>{businessName}</strong>
            </span>
            <Badge variant="outline" className="text-[10px]">
              {humanizeType(businessType)}
            </Badge>
            {demoTagline && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="flex items-center text-muted-foreground hover:text-foreground"
                    aria-label="What's this demo?"
                  >
                    <Info className="size-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-xs text-left">
                  <p>{demoTagline}</p>
                  <p className="mt-1 text-background/70">
                    You&apos;re viewing seeded sample data for a fictional firm.
                  </p>
                </TooltipContent>
              </Tooltip>
            )}
          </span>
          <Button variant="outline" size="sm" disabled={switching} onClick={handleSwitch}>
            {switching ? "Switching..." : "Try a different scenario"}
          </Button>
        </div>
      </TooltipProvider>
    );
  }

  return (
    <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-sm">
      <span className="font-medium text-foreground">{businessName}</span>
      <Badge variant="outline" className="text-[10px]">
        {humanizeType(businessType)}
      </Badge>
    </div>
  );
}
