"use client";

import { Logo } from "@/components/Logo";
import { HeaderNavLink } from "@/components/HeaderNavLink";
import { AccountMenu } from "@/components/AccountMenu";
import { OnboardingTour } from "@/components/OnboardingTour";
import { DemoPersonaSwitcher } from "@/components/DemoPersonaSwitcher";
import { NotificationBell } from "@/components/NotificationBell";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

interface DashboardHeaderProps {
  navLinks: NavItem[];
  businessName: string;
  businessType: string;
  isDemo: boolean;
  demoTagline: string | null;
  demoDescription: string | null;
}

// The main nav (Ask TaxFlow / Workspace / Library) used to live in a
// permanent left sidebar - moved here so the answer pane (already competing
// with the conversation list and Sources panel for width) gets the space
// back. Account-level actions (Settings, Sign out) are folded into one menu
// at the far right instead of two standalone rows at the sidebar's bottom.
export function DashboardHeader({
  navLinks,
  businessName,
  businessType,
  isDemo,
  demoTagline,
  demoDescription,
}: DashboardHeaderProps) {
  return (
    <header className="relative flex h-14 shrink-0 items-center gap-4 border-b border-border px-4">
      <Logo href="/dashboard" />

      <nav
        className="absolute left-1/2 flex -translate-x-1/2 items-center gap-1"
        data-tour="nav-sidebar"
      >
        {navLinks.map((link) => (
          <HeaderNavLink key={link.href} href={link.href} icon={link.icon}>
            {link.label}
          </HeaderNavLink>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-2 pr-10">
        <NotificationBell />

        {isDemo && (
          <OnboardingTour
            businessName={businessName}
            businessType={businessType}
            demoTagline={demoTagline}
            demoDescription={demoDescription}
            isDemo={isDemo}
          />
        )}

        <AccountMenu />

        {businessName && isDemo && (
          <div data-tour="identity-strip">
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
