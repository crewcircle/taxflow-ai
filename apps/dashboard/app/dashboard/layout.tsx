import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { TrialBanner } from "@/components/TrialBanner";

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
        <aside className="w-56 border-r p-4">
          <nav className="flex flex-col gap-2">
            {NAV_LINKS.map((link) => (
              <Link key={link.href} href={link.href} className="rounded px-2 py-1 text-sm hover:bg-neutral-100">
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
