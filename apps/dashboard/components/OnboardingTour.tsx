"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { relativeTime, useLastQueryWalkthrough } from "@/lib/useLastQueryWalkthrough";

interface OnboardingTourProps {
  businessName: string;
  businessType: string;
  demoTagline: string | null;
  demoDescription: string | null;
  isDemo: boolean;
}

const MODULES = [
  { label: "ATO correspondence", detail: "Upload an ATO letter, get a classification and a drafted response." },
  {
    label: "Documents",
    detail: "Save any answer as a client-ready document - advice memo, engagement letter, and more.",
  },
  {
    label: "Firm knowledge",
    detail: "Upload the firm's own precedents so answers reflect internal guidance too.",
  },
  { label: "Regulatory updates", detail: "New rulings and decisions detected from public regulator feeds." },
];

function humanizeType(type: string): string {
  return type.replace(/_/g, " ");
}

export function OnboardingTour({
  businessName,
  businessType,
  demoTagline,
  demoDescription,
  isDemo,
}: OnboardingTourProps) {
  const storageKey = `taxflow_tour_seen:${businessName}`;
  const stepCount = 6;

  // A full page reload happens on persona switch ("Try a different scenario"),
  // so this component always remounts fresh for a new persona - a lazy
  // initializer is enough to decide the first render's open state. It only
  // reads sessionStorage (stays pure/safe under Strict Mode's dev-mode
  // double-invocation) - marking the key "seen" is a side effect, done
  // separately in the mount effect below.
  const [open, setOpen] = useState(
    () => typeof window !== "undefined" && isDemo && !!businessName && !window.sessionStorage.getItem(storageKey)
  );
  const [step, setStep] = useState(0);
  const { load, loading, lastQuery, noQueries, firstIssue, distinctCitations } = useLastQueryWalkthrough();

  useEffect(() => {
    if (open) {
      window.sessionStorage.setItem(storageKey, "1");
      load();
    }
    // Only on mount - load() is idempotent (guards on its own "fetched" flag).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function openManually() {
    setStep(0);
    setOpen(true);
    load();
  }

  function handleFinish() {
    setOpen(false);
    document.querySelector<HTMLTextAreaElement>("textarea")?.focus();
  }

  if (!isDemo) return null;

  return (
    <>
      <Button variant="outline" size="sm" onClick={openManually}>
        Take the tour
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="size-4 text-accent" />
              {businessName}
            </DialogTitle>
          </DialogHeader>

          <div className="min-h-[220px] space-y-3 text-sm">
            {step === 0 && (
              <>
                <p className="text-xs font-semibold text-muted-foreground">WELCOME</p>
                <p className="flex items-center gap-2">
                  You&apos;re viewing a live demo as <strong>{businessName}</strong>
                  <Badge variant="outline" className="text-[10px]">
                    {humanizeType(businessType)}
                  </Badge>
                </p>
                {demoDescription && <p className="text-muted-foreground">{demoDescription}</p>}
                {demoTagline && <p className="font-medium text-foreground">{demoTagline}</p>}
              </>
            )}

            {step === 1 && (
              <>
                <p className="text-xs font-semibold text-muted-foreground">A REAL QUESTION THEY ASKED</p>
                {loading && <p className="text-xs text-muted-foreground">Loading...</p>}
                {!loading && noQueries && (
                  <p className="text-xs text-muted-foreground">
                    This firm hasn&apos;t asked a question yet.
                  </p>
                )}
                {!loading && lastQuery && (
                  <div className="space-y-1.5 rounded-lg border border-border p-3">
                    <p className="text-sm font-medium text-foreground">{lastQuery.question}</p>
                    <p className="text-xs text-muted-foreground">Asked {relativeTime(lastQuery.created_at)}</p>
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  Real questions, asked in plain English - not a scripted demo script.
                </p>
              </>
            )}

            {step === 2 && (
              <>
                <p className="text-xs font-semibold text-muted-foreground">WHAT TAXFLOW FOUND</p>
                {distinctCitations.length > 0 ? (
                  <>
                    <p className="text-muted-foreground">
                      TaxFlow searched its knowledge base of real ATO rulings and legislation and found:
                    </p>
                    <ul className="list-disc space-y-1 pl-5">
                      {distinctCitations.map((c) => (
                        <li key={c} className="text-foreground">
                          {c}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="text-muted-foreground">
                    For this particular question, TaxFlow found no matching sources in the knowledge
                    base - the drafted answer relied on general knowledge instead of a grounded
                    source. That gap is exactly what the next step catches.
                  </p>
                )}
              </>
            )}

            {step === 3 && (
              <>
                <p className="text-xs font-semibold text-muted-foreground">THE SAFETY NET</p>
                {firstIssue ? (
                  <>
                    <p className="text-muted-foreground">
                      Before the answer was marked ready, a second AI pass (Verify Agent) checked
                      every claim against the sources actually retrieved - and caught something:
                    </p>
                    <div className="space-y-1.5 rounded bg-amber-50 p-3 text-xs">
                      <p>
                        <span className="font-semibold">What the draft said: </span>
                        {firstIssue.claim}
                      </p>
                      <p>
                        <span className="font-semibold">Verify Agent&apos;s correction note: </span>
                        {firstIssue.suggested_correction}
                      </p>
                    </div>
                    <p className="text-muted-foreground">
                      A generic AI chatbot would have no way to catch this - there&apos;s no source
                      corpus to check the claim against in the first place.
                    </p>
                  </>
                ) : (
                  <p className="text-muted-foreground">
                    For this question, Verify Agent checked every claim against the retrieved
                    sources and found nothing to flag - the answer came back fully verified.
                  </p>
                )}
              </>
            )}

            {step === 4 && (
              <>
                <p className="text-xs font-semibold text-muted-foreground">EVERYTHING ELSE TAXFLOW DOES</p>
                <ul className="space-y-2">
                  {MODULES.map((m) => (
                    <li key={m.label} className="text-xs">
                      <span className="font-medium text-foreground">{m.label}</span>
                      <span className="text-muted-foreground"> - {m.detail}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {step === 5 && (
              <>
                <p className="text-xs font-semibold text-muted-foreground">TRY IT YOURSELF</p>
                <p className="text-muted-foreground">
                  Ask your own Australian tax question below and watch the same research, draft,
                  and verification steps happen live.
                </p>
              </>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-border pt-4">
            <div className="flex gap-1">
              {Array.from({ length: stepCount }).map((_, i) => (
                <span
                  key={i}
                  className={`size-1.5 rounded-full ${i === step ? "bg-accent" : "bg-muted"}`}
                />
              ))}
            </div>
            <div className="flex gap-2">
              {step > 0 && (
                <Button variant="ghost" size="sm" onClick={() => setStep((s) => s - 1)}>
                  <ArrowLeft className="size-3.5" />
                  Back
                </Button>
              )}
              {step < stepCount - 1 ? (
                <Button size="sm" onClick={() => setStep((s) => s + 1)}>
                  Next
                  <ArrowRight className="size-3.5" />
                </Button>
              ) : (
                <Button size="sm" onClick={handleFinish}>
                  Try it yourself
                </Button>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
