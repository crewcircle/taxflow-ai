type TrialStatus = "active" | "expiring_soon" | "card_required" | "expired";

interface TrialBannerProps {
  status: TrialStatus;
  daysRemaining: number;
}

const STYLES: Record<TrialStatus, string> = {
  active: "bg-green-50 text-green-800 border-green-200",
  expiring_soon: "bg-amber-50 text-amber-800 border-amber-200",
  card_required: "bg-red-50 text-red-800 border-red-200",
  expired: "bg-red-100 text-red-900 border-red-300",
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

  return (
    <div className={`flex items-center justify-between border-b px-4 py-2 text-sm ${STYLES[status]}`}>
      <span>{message(status, daysRemaining)}</span>
      {showCta && (
        <a href="/upgrade" className="rounded bg-black px-3 py-1 text-white text-xs">
          Upgrade now
        </a>
      )}
    </div>
  );
}
