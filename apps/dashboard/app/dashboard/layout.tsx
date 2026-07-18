import { redirect } from "next/navigation";
import {
  BookOpen,
  FileText,
  MessageSquareText,
  ScrollText,
} from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { DashboardHeader } from "@/components/DashboardHeader";
import { DashboardSidebar } from "@/components/DashboardSidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

const NAV_LINKS = [
  { href: "/dashboard/query", label: "Ask TaxFlow", icon: MessageSquareText },
  { href: "/dashboard/documents", label: "Documents", icon: FileText },
  { href: "/dashboard/ato-response", label: "ATO correspondence", icon: ScrollText },
  { href: "/dashboard/knowledge", label: "Firm knowledge", icon: BookOpen },
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
      // Non-fatal - header just won't show client data.
    }
  }

  const navLinks = NAV_LINKS.map((link) => ({
    href: link.href,
    label: link.label,
    icon: <link.icon className="size-4" />,
  }));

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
    </TooltipProvider>
  );
}
