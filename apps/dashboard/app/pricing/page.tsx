import Link from "next/link";
import { Check } from "lucide-react";
import { MarketingHeader } from "@/components/MarketingHeader";
import { MarketingFooter } from "@/components/MarketingFooter";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { TIERS } from "@/lib/pricing";

const FAQS = [
  {
    q: "Do I need a credit card to try it?",
    a: "No. The 30-day free trial starts with just a work email - 100 research queries and 10 documents, no card required.",
  },
  {
    q: "What happens after the trial?",
    a: "You choose a plan and add a card or set up BECS direct debit. If you don't, your account simply reverts to view-only until you do.",
  },
  {
    q: "Can I switch plans later?",
    a: "Yes, any time. Contact us and we'll adjust your plan for the next billing cycle.",
  },
  {
    q: "Is my clients' data kept private?",
    a: "Yes. Each firm's data is isolated at the database level, and firm-uploaded knowledge is never used to answer another firm's questions.",
  },
];

export default function PricingPage() {
  return (
    <>
      <MarketingHeader />
      <main className="flex-1 bg-background px-6 py-20">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="mb-3 text-3xl font-bold text-foreground md:text-4xl">
            Simple pricing, no surprises
          </h1>
          <p className="text-lg text-muted-foreground">
            Annual billing. Cancel anytime. Card or BECS direct debit.
          </p>
        </div>

        <div className="mx-auto mt-14 grid max-w-2xl gap-6 md:grid-cols-2">
          {TIERS.map((tier) => (
            <Card key={tier.id} className={cn(tier.highlighted && "border-accent ring-1 ring-accent")}>
              <CardHeader>
                {tier.highlighted && (
                  <Badge className="mb-1 w-fit bg-accent text-accent-foreground">Most popular</Badge>
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
                  asChild
                  className={cn("w-full", tier.highlighted && "bg-accent text-accent-foreground hover:opacity-90")}
                >
                  <Link href="/signup">Start free trial</Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="mx-auto mt-24 max-w-2xl">
          <h2 className="mb-8 text-center text-2xl font-bold text-foreground">Questions</h2>
          <div className="space-y-6">
            {FAQS.map((faq) => (
              <div key={faq.q} className="border-b border-border pb-6 last:border-b-0">
                <h3 className="mb-2 font-semibold text-foreground">{faq.q}</h3>
                <p className="text-sm text-muted-foreground">{faq.a}</p>
              </div>
            ))}
          </div>
        </div>
      </main>
      <MarketingFooter />
    </>
  );
}
