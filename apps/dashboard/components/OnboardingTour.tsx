"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { relativeTime, useLastQueryWalkthrough } from "@/lib/useLastQueryWalkthrough";

interface OnboardingTourProps {
  businessName: string;
  businessType: string;
  demoTagline: string | null;
  demoDescription: string | null;
  isDemo: boolean;
}

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const QUERY_PATH = "/dashboard/query";
const PAD = 8;

function humanizeType(type: string): string {
  return type.replace(/_/g, " ");
}

function useTargetRect(selector: string | null, active: boolean): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null);

  useEffect(() => {
    if (!active || !selector) {
      const clearId = setTimeout(() => setRect(null), 0);
      return () => clearTimeout(clearId);
    }
    const el = document.querySelector<HTMLElement>(selector);
    if (!el) {
      const clearId = setTimeout(() => setRect(null), 0);
      return () => clearTimeout(clearId);
    }
    el.scrollIntoView({ block: "center", behavior: "smooth" });

    function measure() {
      const r = el!.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    }
    const t = setTimeout(measure, 350);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [selector, active]);

  return rect;
}

export function OnboardingTour({
  businessName,
  businessType,
  demoTagline,
  demoDescription,
  isDemo,
}: OnboardingTourProps) {
  const router = useRouter();
  const pathname = usePathname();
  const storageKey = `taxflow_tour_seen:${businessName}`;

  const [open, setOpen] = useState(false);
  const [forceOpenRequested, setForceOpenRequested] = useState(false);
  const [step, setStep] = useState(0);
  const { load, loading, lastQuery, issueExample, noQueries, firstIssue, distinctCitations } =
    useLastQueryWalkthrough();

  // Auto-open once per persona per session. This reacts to `pathname` rather
  // than only checking it at mount, because the demo-login flow does a
  // client-side router.push("/dashboard") that then server-redirects to
  // /dashboard/query - pathname isn't settled to its final value until after
  // this component has already mounted, so a mount-only check (e.g. a
  // useState lazy initializer) misses the redirect and never opens.
  useEffect(() => {
    if (!(isDemo && businessName && pathname === QUERY_PATH && !window.sessionStorage.getItem(storageKey))) return;
    const t = setTimeout(() => {
      window.sessionStorage.setItem(storageKey, "1");
      setStep(0);
      setOpen(true);
      load();
    }, 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDemo, businessName, pathname, storageKey]);

  // "Take the tour" clicked from a page other than the query page: navigate
  // there first, then open once we've actually landed (same reasoning as above).
  useEffect(() => {
    if (!(forceOpenRequested && pathname === QUERY_PATH)) return;
    const t = setTimeout(() => {
      setForceOpenRequested(false);
      setStep(0);
      setOpen(true);
      load();
    }, 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forceOpenRequested, pathname]);

  const steps = [
    {
      selector: '[data-tour="identity-strip"]',
      title: "Who you're looking at",
      body: (
        <>
          <p>
            You&apos;re viewing a live demo as <strong>{businessName}</strong> ({humanizeType(businessType)}).
          </p>
          {demoDescription && <p className="text-muted-foreground">{demoDescription}</p>}
          {demoTagline && <p className="font-medium text-foreground">{demoTagline}</p>}
        </>
      ),
    },
    {
      selector: '[data-tour="suggested-question"]',
      title: "A real question they asked",
      body: (
        <>
          {loading && <p className="text-muted-foreground">Loading...</p>}
          {!loading && noQueries && <p className="text-muted-foreground">This firm hasn&apos;t asked a question yet.</p>}
          {!loading && lastQuery && (
            <p className="text-muted-foreground">
              These are real questions {businessName} has already asked TaxFlow - like this one, asked{" "}
              {relativeTime(lastQuery.created_at)}. Click any of them to try it yourself.
            </p>
          )}
        </>
      ),
    },
    {
      selector: '[data-tour="sources-panel"]',
      title: "Where sources appear",
      body:
        distinctCitations.length > 0 ? (
          <p className="text-muted-foreground">
            When TaxFlow answers, every source it actually used shows up here. For{" "}
            {businessName}&apos;s last question, that was: {distinctCitations.join(", ")}.
          </p>
        ) : (
          <p className="text-muted-foreground">
            This panel is empty right now because no question has been asked yet this session - but for{" "}
            {businessName}&apos;s last question, TaxFlow actually found no matching sources at all. That
            honesty is exactly what the next step is about.
          </p>
        ),
    },
    {
      selector: null,
      title: "The safety net",
      body: firstIssue && issueExample ? (
        <>
          <p className="text-xs text-muted-foreground">
            On: &ldquo;{issueExample.question}&rdquo;
          </p>
          <div className="space-y-1.5 rounded bg-amber-50 p-3 text-xs">
            <p>
              <span className="font-semibold">Draft said: </span>
              {firstIssue.claim}
            </p>
            <p>
              <span className="font-semibold">Verify Agent caught: </span>
              {firstIssue.suggested_correction}
            </p>
          </div>
          <p className="text-muted-foreground">
            Every claim is checked against the actual sources before an answer ships. A generic
            chatbot can&apos;t do this - it has no source corpus to check against.
          </p>
        </>
      ) : (
        <p className="text-muted-foreground">
          Every claim in a drafted answer is checked against the actual sources retrieved before it
          ships - {businessName}&apos;s questions have all come back fully verified so far.
        </p>
      ),
    },
    {
      selector: '[data-tour="nav-sidebar"]',
      title: "Everything else TaxFlow does",
      body: (
        <ul className="space-y-1.5">
          <li>
            <span className="font-medium text-foreground">ATO correspondence</span>
            <span className="text-muted-foreground"> - upload a letter, get a classification and a drafted reply.</span>
          </li>
          <li>
            <span className="font-medium text-foreground">Documents</span>
            <span className="text-muted-foreground"> - save any answer as a client-ready document.</span>
          </li>
          <li>
            <span className="font-medium text-foreground">Firm knowledge</span>
            <span className="text-muted-foreground"> - upload the firm&apos;s own precedents.</span>
          </li>
          <li>
            <span className="font-medium text-foreground">Regulatory updates</span>
            <span className="text-muted-foreground"> - new rulings detected from public feeds.</span>
          </li>
        </ul>
      ),
    },
    {
      selector: '[data-tour="question-textarea"]',
      title: "Try it yourself",
      body: (
        <p className="text-muted-foreground">
          Ask your own Australian tax question here and watch the same research, draft, and verification
          steps happen live.
        </p>
      ),
    },
  ];

  const stepCount = steps.length;
  const current = steps[step];
  const rect = useTargetRect(current.selector, open);

  function openManually() {
    if (pathname !== QUERY_PATH) {
      setForceOpenRequested(true);
      router.push(QUERY_PATH);
      return;
    }
    setStep(0);
    setOpen(true);
    load();
  }

  function handleFinish() {
    setOpen(false);
    document.querySelector<HTMLTextAreaElement>('[data-tour="question-textarea"]')?.focus();
  }

  if (!isDemo) return null;

  // Card position: below the target if it fits, else above; clamped horizontally.
  const CARD_WIDTH = 340;
  let cardStyle: React.CSSProperties = {
    top: "50%",
    left: "50%",
    transform: "translate(-50%, -50%)",
  };
  if (rect) {
    const estHeight = 220;
    const spaceBelow = window.innerHeight - (rect.top + rect.height);
    const top = spaceBelow > estHeight + 24 ? rect.top + rect.height + PAD + 8 : Math.max(16, rect.top - estHeight - PAD - 8);
    const left = Math.min(Math.max(16, rect.left), window.innerWidth - CARD_WIDTH - 16);
    cardStyle = { top, left };
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={openManually}>
        Take the tour
      </Button>

      {open && (
        <div className="fixed inset-0 z-[100]">
          {rect ? (
            <>
              <div
                className="absolute inset-x-0 top-0 bg-black/60"
                style={{ height: Math.max(0, rect.top - PAD) }}
              />
              <div
                className="absolute inset-x-0 bottom-0 bg-black/60"
                style={{ top: rect.top + rect.height + PAD }}
              />
              <div
                className="absolute bg-black/60"
                style={{ top: rect.top - PAD, height: rect.height + PAD * 2, left: 0, width: Math.max(0, rect.left - PAD) }}
              />
              <div
                className="absolute bg-black/60"
                style={{
                  top: rect.top - PAD,
                  height: rect.height + PAD * 2,
                  left: rect.left + rect.width + PAD,
                  right: 0,
                }}
              />
              <div
                className="pointer-events-none absolute rounded-lg ring-2 ring-accent"
                style={{
                  top: rect.top - PAD,
                  left: rect.left - PAD,
                  width: rect.width + PAD * 2,
                  height: rect.height + PAD * 2,
                }}
              />
            </>
          ) : (
            <div className="absolute inset-0 bg-black/60" />
          )}

          <div
            className="absolute w-[340px] space-y-3 rounded-xl border border-border bg-background p-4 text-sm shadow-xl"
            style={cardStyle}
          >
            <p className="text-xs font-semibold text-muted-foreground">{current.title.toUpperCase()}</p>
            <div className="min-h-[80px] space-y-2">{current.body}</div>

            <div className="flex items-center justify-between border-t border-border pt-3">
              <div className="flex gap-1">
                {Array.from({ length: stepCount }).map((_, i) => (
                  <span key={i} className={`size-1.5 rounded-full ${i === step ? "bg-accent" : "bg-muted"}`} />
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
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="absolute -right-2 -top-2 flex size-6 items-center justify-center rounded-full border border-border bg-background text-xs text-muted-foreground hover:text-foreground"
              aria-label="Close tour"
            >
              ×
            </button>
          </div>
        </div>
      )}
    </>
  );
}
