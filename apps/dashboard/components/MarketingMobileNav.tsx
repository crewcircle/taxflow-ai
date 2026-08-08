"use client";

import { useState } from "react";
import Link from "next/link";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

interface NavLink {
  href: string;
  label: string;
}

// Below `md` the marketing header's nav links were simply hidden with no
// replacement at all (`hidden md:flex`, no hamburger) - every page except
// Home was unreachable from the header on a phone. This is the mobile
// equivalent MobileNav already gives the dashboard header.
export function MarketingMobileNav({ navLinks }: { navLinks: NavLink[] }) {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Open menu"
        className="md:hidden"
        onClick={() => setOpen(true)}
      >
        <Menu className="size-5" />
      </Button>
      <SheetContent className="max-w-72" onClick={() => setOpen(false)}>
        <SheetHeader>
          <SheetTitle>Menu</SheetTitle>
        </SheetHeader>
        <nav className="flex flex-col gap-1">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-lg px-3 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="mt-2 flex flex-col gap-2 border-t border-border pt-4">
          <Button asChild variant="outline">
            <Link href="/login">Login</Link>
          </Button>
          <Button asChild className="bg-accent text-accent-foreground hover:opacity-90">
            <Link href="/signup">Start free trial</Link>
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
