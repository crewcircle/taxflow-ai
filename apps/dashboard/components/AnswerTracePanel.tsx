"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface TraceCandidate {
  n: number;
  citation: string;
  source_type: string | null;
  is_firm_knowledge: boolean;
  score: number;
  cited_in_answer: boolean;
}

export interface AnswerTrace {
  retrieval: {
    chunks_considered: number;
    source_type_hint: string[] | null;
    candidates: TraceCandidate[];
  } | null;
  generation: {
    model: string;
    confidence?: number;
    input_tokens?: number | null;
    output_tokens?: number | null;
  };
  verification: {
    ran: boolean;
    status?: string;
    issue_count?: number;
    corrective_pass?: boolean;
  } | null;
  corrective_generation?: {
    model: string;
    confidence?: number;
  };
}

// Plain-English "can I use this as-is" signal, replacing a bare confidence
// percentage - per the practice-principal audit, the percentage on its own
// has no professional meaning. The number isn't deleted, just demoted to a
// secondary parenthetical next to this sentence.
function relianceBand(confidence: number): { label: string; className: string } {
  if (confidence >= 0.75) {
    return { label: "Safe to rely on as drafted", className: "text-green-700" };
  }
  if (confidence >= 0.5) {
    return { label: "Spot-check before relying on it", className: "text-amber-700" };
  }
  return { label: "Needs review before relying on it", className: "text-destructive" };
}

// Which model answered doesn't mean anything to a practitioner on its own -
// described here in terms of what it implies about the answer instead of a
// raw model id (replaces the standalone "Enhanced model" badge that used to
// sit above the answer).
const MODEL_DESCRIPTIONS: Record<string, string> = {
  haiku: "our standard research pass",
  sonnet: "a deeper research pass, used because this question needed extra care",
};

// Plain-English labels for the source_type enum, so the default retrieval
// summary reads like a sentence a practitioner would say out loud instead of
// a raw database value.
const SOURCE_TYPE_LABELS: Record<string, string> = {
  ato_ruling: "ATO ruling",
  state_ruling: "State revenue ruling",
  legislation: "Legislation",
  court_decision: "Court decision",
  ato_determination: "ATO determination",
  ato_guide: "ATO guide",
  ato_pbr: "Private ruling",
  ato_news: "ATO news",
};

function stageLabel(status?: string): string {
  switch (status) {
    case "verified":
      return "Passed - claims matched the cited sources";
    case "needs_correction":
      return "Flagged issues - answer was regenerated to address them";
    case "unreliable":
      return "Flagged as unreliable";
    case "parse_error":
      return "Verification pass errored (answer still shown, unverified)";
    default:
      return status ?? "Unknown";
  }
}

// Collapsible "why this answer?" panel: shows exactly which retrieved
// candidates were actually cited, which model answered, and whether/how the
// verify pass checked the draft - the transparency layer meant to make the
// answer debuggable instead of a black box.
export function AnswerTracePanel({ trace }: { trace: AnswerTrace }) {
  const [open, setOpen] = useState(false);
  const [showRetrievalDetail, setShowRetrievalDetail] = useState(false);

  return (
    <Card className="border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium text-foreground"
      >
        <span className="flex items-center gap-1.5">
          <Search className="size-3.5 text-muted-foreground" />
          Why this answer?
        </span>
        {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
      </button>

      {open && (
        <CardContent className="space-y-4 border-t border-border pt-3 text-sm">
          <div>
            <p className="mb-1 font-medium text-foreground">1. Retrieval</p>
            {trace.retrieval ? (
              <>
                <p className="mb-1.5 text-xs text-muted-foreground">
                  {trace.retrieval.chunks_considered} source
                  {trace.retrieval.chunks_considered === 1 ? "" : "s"} checked.{" "}
                  {trace.retrieval.candidates.filter((c) => c.cited_in_answer).length} relied on
                  {trace.retrieval.candidates.some((c) => c.cited_in_answer) ? ": " : "."}
                  {trace.retrieval.candidates
                    .filter((c) => c.cited_in_answer)
                    .map((c) => c.source_type ? `${c.citation} (${SOURCE_TYPE_LABELS[c.source_type] ?? c.source_type})` : c.citation)
                    .join(", ")}
                </p>
                <button
                  type="button"
                  onClick={() => setShowRetrievalDetail((v) => !v)}
                  className="mb-1.5 text-xs font-medium text-accent hover:underline"
                >
                  {showRetrievalDetail ? "Hide retrieval detail" : "Show retrieval detail"}
                </button>
                {showRetrievalDetail && (
                  <ul className="space-y-1">
                    {trace.retrieval.candidates.map((c) => (
                      <li
                        key={c.n}
                        className={cn(
                          "flex items-center justify-between gap-2 rounded-md border px-2 py-1 text-xs",
                          c.cited_in_answer
                            ? "border-accent/30 bg-accent/5"
                            : "border-border text-muted-foreground"
                        )}
                      >
                        <span className="truncate">
                          [{c.n}] {c.citation}
                          {c.source_type ? ` · ${SOURCE_TYPE_LABELS[c.source_type] ?? c.source_type}` : ""}
                        </span>
                        <span className="flex shrink-0 items-center gap-1.5">
                          <span className="tabular-nums">{c.score.toFixed(3)}</span>
                          {c.cited_in_answer ? (
                            <Badge variant="outline" className="border-accent/30 text-accent">
                              cited
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-muted-foreground">
                              not used
                            </Badge>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                Served from cache - no new retrieval ran for this exact question.
              </p>
            )}
          </div>

          <div>
            <p className="mb-1 font-medium text-foreground">2. How much can you rely on this?</p>
            {typeof trace.generation.confidence === "number" ? (
              <p className={cn("text-xs font-medium", relianceBand(trace.generation.confidence).className)}>
                {relianceBand(trace.generation.confidence).label}{" "}
                <span className="font-normal text-muted-foreground">
                  ({Math.round(trace.generation.confidence * 100)}%)
                </span>
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Answered using {MODEL_DESCRIPTIONS[trace.generation.model] ?? trace.generation.model}.
            </p>
          </div>

          <div>
            <p className="mb-1 font-medium text-foreground">3. Verification</p>
            {trace.verification?.ran ? (
              <p className="text-xs text-muted-foreground">
                {stageLabel(trace.verification.status)}
                {trace.verification.issue_count ? ` (${trace.verification.issue_count} flagged)` : ""}
                {trace.verification.corrective_pass && trace.corrective_generation
                  ? " - the answer above was already rewritten to fix them."
                  : "."}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Skipped - retrieval/citation signals were strong enough that a verify pass wasn&apos;t triggered.
              </p>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}
