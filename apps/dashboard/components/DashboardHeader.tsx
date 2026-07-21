"use client";

import { Logo } from "@/components/Logo";
import { OnboardingTour } from "@/components/OnboardingTour";
import { DemoPersonaSwitcher } from "@/components/DemoPersonaSwitcher";
import { NotificationBell } from "@/components/NotificationBell";

interface DashboardHeaderProps {
  businessName: string;
  businessType: string;
  isDemo: boolean;
  demoTagline: string | null;
  demoDescription: string | null;
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

      <div className="flex items-center gap-2 pr-16">
        <NotificationBell />

        {businessName && isDemo && (
          <div className="flex items-center gap-3" data-tour="identity-strip">
            <OnboardingTour
              businessName={businessName}
              businessType={businessType}
              demoTagline={demoTagline}
              demoDescription={demoDescription}
              isDemo={isDemo}
            />
            <DemoPersonaSwitcher currentType={businessType} />
          </div>
        )}
      </div>

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
