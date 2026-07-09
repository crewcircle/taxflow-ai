"use client";

import { useState } from "react";
import { Logo } from "@/components/Logo";

const TIERS = [
  {
    id: "starter",
    name: "Starter",
    price: "$2,400",
    period: "/year + GST",
    features: [
      "300 research queries / month",
      "50 documents / month",
      "ATO correspondence module",
      "Email support",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    price: "$6,000",
    period: "/year + GST",
    highlighted: true,
    features: [
      "Unlimited research queries",
      "Unlimited documents",
      "ATO correspondence module",
      "Firm knowledge base",
      "Regulatory alerts",
      "Priority support",
    ],
  },
];

export default function UpgradePage() {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleUpgrade(tier: string) {
    setLoading(tier);
    setError(null);
    try {
      const response = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
      });
      if (!response.ok) throw new Error("Checkout failed");
      const data: { checkout_url: string } = await response.json();
      window.location.assign(data.checkout_url);
    } catch {
      setError("Could not start checkout - please try again or contact support");
      setLoading(null);
    }
  }

  return (
    <main className="flex flex-1 flex-col items-center bg-muted px-4 py-12">
      <div className="mb-8">
        <Logo />
      </div>
      <h1 className="mb-2 text-2xl font-bold">Choose your plan</h1>
      <p className="mb-8 text-sm text-muted-foreground">
        Annual billing. Cancel anytime. Card or BECS direct debit.
      </p>

      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      <div className="grid w-full max-w-2xl gap-6 md:grid-cols-2">
        {TIERS.map((tier) => (
          <div
            key={tier.id}
            className={`rounded-xl border bg-card p-6 shadow-sm ${
              tier.highlighted ? "border-accent ring-1 ring-accent" : "border-border"
            }`}
          >
            {tier.highlighted && (
              <span className="mb-2 inline-block rounded bg-accent px-2 py-0.5 text-xs font-semibold text-accent-foreground">
                Most popular
              </span>
            )}
            <h2 className="text-lg font-bold">{tier.name}</h2>
            <p className="mt-1">
              <span className="text-3xl font-bold">{tier.price}</span>
              <span className="text-sm text-muted-foreground">{tier.period}</span>
            </p>
            <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
              {tier.features.map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <span className="text-accent">✓</span> {f}
                </li>
              ))}
            </ul>
            <button
              onClick={() => handleUpgrade(tier.id)}
              disabled={loading !== null}
              className={`mt-6 w-full rounded-lg py-2 text-sm font-semibold transition-all duration-200 disabled:opacity-50 ${
                tier.highlighted
                  ? "bg-accent text-accent-foreground hover:opacity-90"
                  : "bg-primary text-primary-foreground hover:bg-accent"
              }`}
            >
              {loading === tier.id ? "Redirecting to checkout..." : `Choose ${tier.name}`}
            </button>
          </div>
        ))}
      </div>
    </main>
  );
}
