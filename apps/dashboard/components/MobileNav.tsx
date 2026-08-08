"use client";

import { useState } from "react";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { HeaderNavLink } from "@/components/HeaderNavLink";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

// Below `md` the header's horizontal nav has nowhere to go - this swaps it
// for a hamburger that opens the same links as a full-height drawer instead
// of silently overflowing the header. Closes itself on link click (Sheet
// doesn't do that automatically - a nav drawer that stays open after
// navigating reads as broken, not as "still open on purpose").
export function MobileNav({ navLinks }: { navLinks: NavItem[] }) {
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
            <HeaderNavLink key={link.href} href={link.href} icon={link.icon}>
              {link.label}
            </HeaderNavLink>
          ))}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
