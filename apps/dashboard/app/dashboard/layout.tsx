import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { TrialBanner } from "@/components/TrialBanner";
import { Logo } from "@/components/Logo";

const NAV_LINKS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/query", label: "Ask a question" },
  { href: "/dashboard/ato-response", label: "ATO correspondence" },
  { href: "/dashboard/documents", label: "Documents" },
  { href: "/dashboard/knowledge", label: "Firm knowledge" },
  { href: "/dashboard/settings", label: "Settings" },
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
              <Link
                key={link.href}
                href={link.href}
                className="rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-all duration-200 hover:bg-muted hover:text-foreground"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </aside>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
