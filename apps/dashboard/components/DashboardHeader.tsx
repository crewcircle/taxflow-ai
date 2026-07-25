"use client";

import { Logo } from "@/components/Logo";
import { HeaderNavLink } from "@/components/HeaderNavLink";
import { AccountMenu } from "@/components/AccountMenu";
import { OnboardingTour } from "@/components/OnboardingTour";
import { DemoPersonaSwitcher } from "@/components/DemoPersonaSwitcher";
import { NotificationBell } from "@/components/NotificationBell";
import { GlobalSearch } from "@/components/GlobalSearch";

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
  email: string | null;
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
  email,
}: DashboardHeaderProps) {
  return (
    // A 3-column grid, not absolute-positioned nav over a flex row - the nav
    // previously stayed mathematically centered regardless of how wide its
    // siblings got, so a wide demo cluster could visually overlap it as the
    // viewport narrowed. Grid tracks can't overlap: the left and right
    // columns each get an equal share (1fr) of whatever space the center
    // column's actual content doesn't use, so growing/shrinking content on
    // either side can now only push into ITS OWN column, never the nav's.
    <header className="grid h-14 shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-3 border-b border-border px-4">
      <div className="flex min-w-0 items-center gap-2">
        <Logo href="/dashboard" />

        {/* Everything demo-only lives in one clearly-marked cluster right
            after the logo, set apart from the real account controls
            (Notifications/Settings/Sign out) on the far right - previously a
            decorative corner ribbon was disconnected from the tour button
            and persona/role switcher, so "am I looking at demo controls or
            my own account" wasn't answerable at a glance. Shrinks its own
            controls (icon-only tour button, narrower selects) below `lg`
            instead of overflowing its grid column. */}
        {businessName && isDemo && (
          <div
            className="flex min-w-0 items-center gap-1.5 rounded-lg border border-accent/30 bg-accent/5 py-1 pl-2 pr-1.5 sm:gap-2"
            data-tour="identity-strip"
          >
            <span className="shrink-0 rounded-full bg-accent px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white">
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

      <nav className="flex items-center gap-1" data-tour="nav-sidebar">
        {navLinks.map((link) => (
          <HeaderNavLink key={link.href} href={link.href} icon={link.icon}>
            {link.label}
          </HeaderNavLink>
        ))}
      </nav>

      <div className="flex min-w-0 items-center justify-end gap-2">
        <GlobalSearch />
        <NotificationBell />
        <AccountMenu businessName={businessName} role={role} email={email} />
      </div>
    </header>
  );
}
