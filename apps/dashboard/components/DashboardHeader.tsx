"use client";

import { Badge } from "@/components/ui/badge";
import { Logo } from "@/components/Logo";
import { OnboardingTour } from "@/components/OnboardingTour";
import { DemoPersonaSwitcher } from "@/components/DemoPersonaSwitcher";

interface DashboardHeaderProps {
  businessName: string;
  businessType: string;
  isDemo: boolean;
  demoTagline: string | null;
  demoDescription: string | null;
}

function humanizeType(type: string): string {
  return type.replace(/_/g, " ");
}

export function DashboardHeader({
  businessName,
  businessType,
  isDemo,
  demoTagline,
  demoDescription,
}: DashboardHeaderProps) {
  return (
    <header className="relative flex h-16 shrink-0 items-center justify-between border-b border-border px-4">
      <Logo href="/dashboard" />

      {businessName && (
        <div className={`flex items-center gap-3 ${isDemo ? "pr-16" : ""}`} data-tour="identity-strip">
          <span className="flex items-center gap-2 text-sm">
            <span className="font-medium text-foreground">{businessName}</span>
            <Badge variant="outline" className="text-[10px]">
              {humanizeType(businessType)}
            </Badge>
          </span>
          {isDemo && (
            <OnboardingTour
              businessName={businessName}
              businessType={businessType}
              demoTagline={demoTagline}
              demoDescription={demoDescription}
              isDemo={isDemo}
            />
          )}
          {isDemo && <DemoPersonaSwitcher currentType={businessType} />}
        </div>
      )}

      {isDemo && (
        <div className="pointer-events-none absolute right-0 top-0 h-20 w-20 overflow-hidden">
          <div className="absolute right-[-32px] top-[16px] w-[130px] rotate-45 bg-accent py-1 text-center text-[10px] font-bold uppercase tracking-wider text-white shadow-sm">
            Demo
          </div>
        </div>
      )}
    </header>
  );
}
