import { redirect } from "next/navigation";
import {
  BookOpen,
  FileText,
  LineChart,
  MessageSquareText,
  Users,
} from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { isOperatorEmail } from "@/lib/admin";
import { DashboardHeader } from "@/components/DashboardHeader";
import { DashboardSidebar } from "@/components/DashboardSidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";

// 4 destinations by job, not 6-7 flat pages: Clients (which client/engagement
// needs attention right now - billing is per-engagement, so this is the "what
// should I work on" landing spot), Ask (research), Workspace (everything
// generated or in progress for a client - Documents + ATO correspondence used
// to be two doors to the same job), Library (where TaxFlow's knowledge comes
// from - firm precedents + shared reference library + the regulatory feed,
// previously three separate access patterns: a nav item, a header link, and a
// sidebar bell).
const NAV_LINKS = [
  { href: "/dashboard/clients", label: "Clients", icon: Users },
  { href: "/dashboard/query", label: "Ask TaxFlow", icon: MessageSquareText },
  { href: "/dashboard/workspace", label: "Workspace", icon: FileText },
  { href: "/dashboard/library", label: "Library", icon: BookOpen },
];

// The analytics page is operator-only (its backend is gated behind an admin
// allowlist), so only surface the nav link to allowlisted operators - normal
// users must never see a link to a page that 403s.
const ANALYTICS_LINK = { href: "/dashboard/analytics", label: "Analytics", icon: LineChart };

export default async function DashboardLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const {
    data: { session },
  } = await supabase.auth.getSession();
  let isDemo = false;
  let businessName = "";
  let businessType = "";
  let demoTagline: string | null = null;
  let demoDescription: string | null = null;
  if (session) {
    try {
      const meResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/settings/me`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (meResponse.ok) {
        const me = await meResponse.json();
        isDemo = Boolean(me.client?.is_demo);
        businessName = me.client?.business_name ?? "";
        businessType = me.client?.business_type ?? "";
        demoTagline = me.client?.demo_tagline ?? null;
        demoDescription = me.client?.demo_description ?? null;
      }
    } catch {
      // Non-fatal - header just won't show client data.
    }
  }

  const navLinks = NAV_LINKS.map((link) => ({
    href: link.href,
    label: link.label,
    icon: <link.icon className="size-4" />,
  }));

  // Only allowlisted operators (ADMIN_EMAILS) get the operator-only Analytics
  // link, appended after the standard nav items.
  if (isOperatorEmail(user.email)) {
    navLinks.push({
      href: ANALYTICS_LINK.href,
      label: ANALYTICS_LINK.label,
      icon: <ANALYTICS_LINK.icon className="size-4" />,
    });
  }

  return (
    <TooltipProvider>
      <div className="flex h-screen flex-col">
        <DashboardHeader
          businessName={businessName}
          businessType={businessType}
          isDemo={isDemo}
          demoTagline={demoTagline}
          demoDescription={demoDescription}
        />
        <div className="flex flex-1 overflow-hidden">
          <DashboardSidebar navLinks={navLinks} businessName={businessName} businessType={businessType} />
          <main className="min-w-0 flex-1 overflow-y-auto p-6">{children}</main>
        </div>
      </div>
      <Toaster position="bottom-right" />
    </TooltipProvider>
  );
}
