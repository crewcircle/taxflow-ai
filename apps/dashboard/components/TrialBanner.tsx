import { AlertTriangle, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type TrialStatus = "active" | "expiring_soon" | "card_required" | "expired";

interface TrialBannerProps {
  status: TrialStatus;
  daysRemaining: number;
}

const STYLES: Record<TrialStatus, string> = {
  active: "border-border bg-background text-muted-foreground",
  expiring_soon: "border-accent/30 bg-accent/5 text-foreground",
  card_required: "border-destructive/30 bg-destructive/5 text-foreground",
  expired: "border-destructive/30 bg-destructive/5 text-foreground",
};

function message(status: TrialStatus, daysRemaining: number): string {
  switch (status) {
    case "active":
      return `Trial: ${daysRemaining} days remaining`;
    case "expiring_soon":
      return `Trial ends in ${daysRemaining} days - add payment to keep access`;
    case "card_required":
      return "Trial ends tomorrow - add card now";
    case "expired":
      return "Your trial has ended - upgrade to continue";
  }
}

// Stub props (trial_status='active', days_remaining=28) until wired to the
// real trial API in Week 4.
export function TrialBanner({ status = "active", daysRemaining = 28 }: Partial<TrialBannerProps>) {
  const showCta = status === "card_required" || status === "expired";
  const Icon = status === "active" ? CheckCircle2 : AlertTriangle;

  return (
    <div className={cn("flex items-center justify-between border-b px-4 py-2 text-sm", STYLES[status])}>
      <span className="flex items-center gap-2">
        <Icon className="size-4" />
        {message(status, daysRemaining)}
      </span>
      {showCta && (
        <Button asChild size="sm" variant="outline">
          <Link href="/upgrade">Upgrade now</Link>
        </Button>
      )}
    </div>
  );
}
