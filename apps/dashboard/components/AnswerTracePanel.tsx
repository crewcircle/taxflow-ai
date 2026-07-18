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
                  {trace.retrieval.chunks_considered === 1 ? "" : "s"} considered
                  {trace.retrieval.source_type_hint && trace.retrieval.source_type_hint.length > 0
                    ? ` - boosted toward ${trace.retrieval.source_type_hint.join(", ")}`
                    : ""}
                  .
                </p>
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
                        {c.source_type ? ` · ${c.source_type}` : ""}
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
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                Served from cache - no new retrieval ran for this exact question.
              </p>
            )}
          </div>

          <div>
            <p className="mb-1 font-medium text-foreground">2. Generation</p>
            <p className="text-xs text-muted-foreground">
              Answered by <span className="font-medium text-foreground">{trace.generation.model}</span>
              {typeof trace.generation.confidence === "number"
                ? ` at ${Math.round(trace.generation.confidence * 100)}% confidence`
                : ""}
              .
            </p>
          </div>

          <div>
            <p className="mb-1 font-medium text-foreground">3. Verification</p>
            {trace.verification?.ran ? (
              <p className="text-xs text-muted-foreground">
                {stageLabel(trace.verification.status)}
                {trace.verification.issue_count ? ` (${trace.verification.issue_count} flagged)` : ""}
                {trace.verification.corrective_pass && trace.corrective_generation
                  ? ` - regenerated by ${trace.corrective_generation.model}.`
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
