"use client";

import { useState } from "react";
import { Check } from "lucide-react";
import { SiteHeader } from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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
    <>
      <SiteHeader cta="login" />
      <main className="flex flex-1 flex-col items-center bg-background px-4 py-16">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold">Choose your plan</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Annual billing. Cancel anytime. Card or BECS direct debit.
          </p>
        </div>

        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

        <div className="grid w-full max-w-2xl gap-6 md:grid-cols-2">
          {TIERS.map((tier) => (
            <Card
              key={tier.id}
              className={cn(tier.highlighted && "border-accent ring-1 ring-accent")}
            >
              <CardHeader>
                {tier.highlighted && (
                  <Badge className="mb-1 w-fit bg-accent text-accent-foreground">
                    Most popular
                  </Badge>
                )}
                <h2 className="text-lg font-semibold">{tier.name}</h2>
                <p>
                  <span className="text-3xl font-bold">{tier.price}</span>
                  <span className="text-sm text-muted-foreground">{tier.period}</span>
                </p>
              </CardHeader>
              <CardContent className="space-y-6">
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-start gap-2">
                      <Check className="mt-0.5 size-4 shrink-0 text-accent" /> {f}
                    </li>
                  ))}
                </ul>
                <Button
                  onClick={() => handleUpgrade(tier.id)}
                  disabled={loading !== null}
                  className={cn(
                    "w-full",
                    tier.highlighted && "bg-accent text-accent-foreground hover:opacity-90"
                  )}
                >
                  {loading === tier.id ? "Redirecting to checkout..." : `Choose ${tier.name}`}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </main>
    </>
  );
}
