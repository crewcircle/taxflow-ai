"use client";

import { Bell } from "lucide-react";
import { DashboardNavLink } from "@/components/DashboardNavLink";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Plain nav link now - new-alert signaling lives in the single header
// NotificationBell instead of a second, independent unread dot here. Two
// separate "something's new" indicators in two corners of the screen was
// the actual confusion being reported, not this link itself.
export function RegulatoryBellLink({ collapsed }: { collapsed?: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <DashboardNavLink
          href="/dashboard/library?tab=reference"
          icon={<Bell className="size-4" />}
          collapsed={collapsed}
        >
          Regulatory updates
        </DashboardNavLink>
      </TooltipTrigger>
      <TooltipContent side="right">Recent ATO and tax law changes relevant to your clients</TooltipContent>
    </Tooltip>
  );
}
