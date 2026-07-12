"use client";

import { useState } from "react";
import { Info, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { startDemoLogin } from "@/lib/demo-login";

interface DashboardIdentityStripProps {
  businessName: string;
  businessType: string;
  isDemo: boolean;
  demoTagline: string | null;
  demoDescription: string | null;
}

interface QueryListItem {
  id: string;
  created_at: string;
}

interface VerificationIssue {
  claim: string;
  suggested_correction: string;
}

interface QueryDetail {
  question: string;
  citations: { citation: string; url: string; excerpt: string }[];
  verification_result: { overall_status: string; issues: VerificationIssue[] } | null;
  created_at: string;
}

const MODULES = [
  { label: "Ask a question", detail: "Cited answers to tax questions, pulled from the ATO knowledge base." },
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

function relativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const dayDiff = Math.round(
    (new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() -
      new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) /
      86400000
  );
  if (dayDiff <= 0) return "today";
  if (dayDiff === 1) return "yesterday";
  if (dayDiff < 7) return `${dayDiff} days ago`;
  return date.toLocaleDateString("en-AU");
}

export function DashboardIdentityStrip({
  businessName,
  businessType,
  isDemo,
  demoTagline,
  demoDescription,
}: DashboardIdentityStripProps) {
  const [switching, setSwitching] = useState(false);
  const [open, setOpen] = useState(false);
  const [lastQuery, setLastQuery] = useState<QueryDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [noQueries, setNoQueries] = useState(false);

  async function handleSwitch() {
    setSwitching(true);
    const result = await startDemoLogin();
    if (result.ok) {
      window.location.reload();
    } else {
      setSwitching(false);
    }
  }

  async function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen);
    if (nextOpen && !lastQuery && !noQueries) {
      setLoadingDetail(true);
      try {
        const listRes = await fetch("/api/query");
        const list: QueryListItem[] = listRes.ok ? await listRes.json() : [];
        if (list.length > 0) {
          const detailRes = await fetch(`/api/query/${list[0].id}`);
          if (detailRes.ok) setLastQuery(await detailRes.json());
        } else {
          setNoQueries(true);
        }
      } catch {
        // Non-fatal - dialog just shows without the walkthrough section.
      } finally {
        setLoadingDetail(false);
      }
    }
  }

  const firstIssue = lastQuery?.verification_result?.issues?.[0];
  const distinctCitations = lastQuery
    ? Array.from(new Set(lastQuery.citations.map((c) => c.citation)))
    : [];

  if (!isDemo) {
    return (
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-sm">
        <span className="font-medium text-foreground">{businessName}</span>
        <Badge variant="outline" className="text-[10px]">
          {humanizeType(businessType)}
        </Badge>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2 text-sm">
      <span className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 text-accent" />
        <span>
          Viewing a live demo as <strong>{businessName}</strong>
        </span>
        <Badge variant="outline" className="text-[10px]">
          {humanizeType(businessType)}
        </Badge>
        <Dialog open={open} onOpenChange={handleOpenChange}>
          <DialogTrigger asChild>
            <button
              type="button"
              className="flex items-center text-muted-foreground hover:text-foreground"
              aria-label="About this demo"
            >
              <Info className="size-4" />
            </button>
          </DialogTrigger>
          <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{businessName}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 text-sm">
              {demoDescription && <p className="text-muted-foreground">{demoDescription}</p>}
              {demoTagline && <p className="font-medium text-foreground">{demoTagline}</p>}

              <div>
                <p className="mb-2 text-xs font-semibold text-muted-foreground">
                  WHAT TAXFLOW DOES FOR {businessName.toUpperCase()}
                </p>
                <ul className="space-y-1.5">
                  {MODULES.map((m) => (
                    <li key={m.label} className="text-xs">
                      <span className="font-medium text-foreground">{m.label}</span>
                      <span className="text-muted-foreground"> - {m.detail}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <p className="mb-2 text-xs font-semibold text-muted-foreground">LAST QUESTION ASKED</p>
                {loadingDetail && <p className="text-xs text-muted-foreground">Loading...</p>}
                {!loadingDetail && noQueries && (
                  <p className="text-xs text-muted-foreground">No questions asked yet.</p>
                )}
                {!loadingDetail && lastQuery && (
                  <div className="space-y-2 rounded-lg border border-border p-3">
                    <p className="text-xs font-medium text-foreground">{lastQuery.question}</p>
                    <p className="text-[11px] text-muted-foreground">
                      Asked {relativeTime(lastQuery.created_at)}
                    </p>

                    {distinctCitations.length > 0 ? (
                      <p className="text-xs text-muted-foreground">
                        Sources found: {distinctCitations.join(", ")}
                      </p>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        TaxFlow found no matching sources in the knowledge base for this question -
                        the drafted answer relied on general knowledge instead.
                      </p>
                    )}

                    {lastQuery.verification_result?.overall_status === "verified" && (
                      <p className="text-xs text-green-700">Verified against sources.</p>
                    )}
                    {firstIssue && (
                      <div className="space-y-1 rounded bg-amber-50 p-2 text-[11px]">
                        <p>
                          <span className="font-semibold">What the draft said: </span>
                          {firstIssue.claim}
                        </p>
                        <p>
                          <span className="font-semibold">Verify Agent&apos;s correction note: </span>
                          {firstIssue.suggested_correction}
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </span>
      <Button variant="outline" size="sm" disabled={switching} onClick={handleSwitch}>
        {switching ? "Switching..." : "Try a different scenario"}
      </Button>
    </div>
  );
}
