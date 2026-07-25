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
  role: "owner" | "reviewer" | "staff";
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
  role,
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

      <div className="ml-auto flex items-center gap-3">
        <div className="flex items-center gap-2">
          <NotificationBell />
          <AccountMenu />
        </div>

        {/* Everything demo-only lives in one clearly-marked cluster, set apart
            from the real account controls (Notifications/Settings/Sign out)
            above - previously a decorative corner ribbon was disconnected
            from the tour button and persona/role switcher, so "am I looking
            at demo controls or my own account" wasn't answerable at a
            glance. */}
        {businessName && isDemo && (
          <div
            className="flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/5 py-1 pl-2 pr-1.5"
            data-tour="identity-strip"
          >
            <span className="rounded-full bg-accent px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white">
              Demo
            </span>
            <OnboardingTour
              businessName={businessName}
              businessType={businessType}
              demoTagline={demoTagline}
              demoDescription={demoDescription}
              isDemo={isDemo}
            />
            <DemoPersonaSwitcher currentType={businessType} currentRole={role} />
          </div>
        )}
      </div>
    </header>
  );
}
