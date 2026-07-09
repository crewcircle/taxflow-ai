import { redirect } from "next/navigation";
import {
  BookOpen,
  FileText,
  LayoutDashboard,
  MessageSquare,
  ScrollText,
  Settings,
} from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { TrialBanner } from "@/components/TrialBanner";
import { Logo } from "@/components/Logo";
import { DashboardNavLink } from "@/components/DashboardNavLink";

const NAV_LINKS = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard/query", label: "Ask a question", icon: MessageSquare },
  { href: "/dashboard/ato-response", label: "ATO correspondence", icon: ScrollText },
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

  return (
    <div className="flex flex-1 flex-col">
      <TrialBanner status="active" daysRemaining={28} />
      <div className="flex flex-1">
        <aside className="w-60 border-r border-border p-4">
          <div className="mb-6 px-2">
            <Logo href="/dashboard" />
          </div>
          <nav className="flex flex-col gap-1">
            {NAV_LINKS.map((link) => (
              <DashboardNavLink key={link.href} href={link.href} icon={link.icon}>
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
