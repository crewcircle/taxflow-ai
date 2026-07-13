import { redirect } from "next/navigation";
import {
  Bell,
  BookOpen,
  FileText,
  MessageSquare,
  ScrollText,
  Settings,
} from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { DashboardIdentityStrip } from "@/components/DashboardIdentityStrip";
import { Logo } from "@/components/Logo";
import { DashboardNavLink } from "@/components/DashboardNavLink";

const NAV_LINKS = [
  { href: "/dashboard/query", label: "Ask a question", icon: MessageSquare },
  { href: "/dashboard/ato-response", label: "ATO correspondence", icon: ScrollText },
  { href: "/dashboard/regulatory", label: "Regulatory updates", icon: Bell },
  { href: "/dashboard/documents", label: "Documents", icon: FileText },
  { href: "/dashboard/knowledge", label: "Firm knowledge", icon: BookOpen },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

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
      // Non-fatal - identity strip just won't render without client data.
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      {businessName && (
        <DashboardIdentityStrip
          businessName={businessName}
          businessType={businessType}
          isDemo={isDemo}
          demoTagline={demoTagline}
          demoDescription={demoDescription}
        />
      )}
      <div className="flex flex-1">
        <aside className="w-60 border-r border-border p-4">
          <div className="mb-6 px-2">
            <Logo href="/dashboard" />
          </div>
          <nav className="flex flex-col gap-1" data-tour="nav-sidebar">
            {NAV_LINKS.map((link) => (
              <DashboardNavLink
                key={link.href}
                href={link.href}
                icon={<link.icon className="size-4" />}
              >
                {link.label}
              </DashboardNavLink>
            ))}
          </nav>
        </aside>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
