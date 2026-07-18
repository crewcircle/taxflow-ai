"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Slim strip shown in place of the question-history or sources column when
// the user has hidden it, so there's always a visible way to bring it back
// (rather than the whole column silently disappearing with no affordance).
export function CollapsedPanelRail({
  side,
  label,
  onShow,
}: {
  side: "left" | "right";
  label: string;
  onShow: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onShow}
          className={`flex h-full w-8 shrink-0 flex-col items-center justify-center gap-2 text-muted-foreground hover:bg-muted hover:text-foreground ${
            side === "left" ? "border-r border-border" : "border-l border-border"
          }`}
        >
          {side === "left" ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
        </button>
      </TooltipTrigger>
      <TooltipContent side={side === "left" ? "right" : "left"}>{label}</TooltipContent>
    </Tooltip>
  );
}
