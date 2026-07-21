"use client";

import { useState } from "react";
import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  MessageSquare,
  RotateCcw,
  Search,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface TraceCandidate {
  n: number;
  citation: string;
  source_type: string | null;
  is_firm_knowledge: boolean;
  score: number;
  cited_in_answer: boolean;
  // B1/B2: knowledge-lifecycle lineage. All optional so old traces and the
  // cache-hit path still typecheck/render.
  is_superseded?: boolean;
  superseded_by?: string | null;
  is_historical?: boolean;
}

export interface AnswerTrace {
  retrieval: {
    chunks_considered: number;
    source_type_hint: string[] | null;
    candidates: TraceCandidate[];
    // B/C: freshness + firm-knowledge provenance (all optional/additive).
    knowledge_as_of?: string | null;
    historical_pool_size?: number | null;
    firm_knowledge_used?: string[] | null;
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
  // C: firm voice + firm-knowledge usage. Filled by B (firm_items/
  // firm_items_used) and C (profile/voice/usage_trend); emitted when either
  // fragment is non-empty.
  firm?: {
    profile_applied?: boolean;
    voice_applied?: boolean;
    profile_summary?: string | null;
    firm_items_used?: number;
    firm_items?: { citation: string; cited_in_answer: boolean }[];
    usage_trend?: { quarter_count: number; prior_count: number } | null;
  } | null;
  // C: engagement / session context threaded from prior turns + memos.
  session?: {
    prior_turns_used?: number;
    engagement_memos_used?: number;
    client_ref?: string | null;
  } | null;
  // A/B/C: emitted only when a widened re-run fired.
  re_retrieval?: {
    fired: boolean;
    reason?: "weak_signal" | "reviewer_flag" | "feedback_triggered" | null;
    detail?: string | null;
  } | null;
  // A: emitted only when a corrective pass ran.
  passes?: {
    first_pass?: { model: string; confidence: number } | null;
    corrected?: { model: string; confidence: number } | null;
    changed: boolean;
  } | null;
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

// Renders an ISO date (YYYY-MM-DD) as a compact "12 Jun 2025" stamp. Falls
// back to the raw string if it isn't a parseable date.
function formatFreshness(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function reRetrievalReason(reason?: string | null): string {
  switch (reason) {
    case "reviewer_flag":
      return "A reviewer flagged a possible gap";
    case "feedback_triggered":
      return "Your feedback triggered a re-run";
    case "weak_signal":
    default:
      return "The first pass returned weak signals";
  }
}

// Collapsible "why this answer?" panel, redesigned as the Direction A
// narrative timeline: a plain-language story a firm principal can read top to
// bottom - firm voice, engagement context, retrieval (with re-run + superseded
// lineage), generation, verification (with first-pass-vs-corrected diff) - with
// the technical per-candidate detail progressively disclosed behind <details>,
// and a learning-loop footer to suggest the answer for firm knowledge.
export function AnswerTracePanel({
  trace,
  onPromote,
  promoteState,
}: {
  trace: AnswerTrace;
  onPromote?: () => void;
  promoteState?: "idle" | "saving" | "saved" | "error";
}) {
  // Open by default: the Sources rail beside it is already always-visible
  // (no toggle), so a closed trace panel was the one remaining "click to find
  // out whether you can trust this" step - full transparency means not
  // hiding it behind that click.
  const [open, setOpen] = useState(true);

  const { retrieval, firm, session, re_retrieval, passes, verification } = trace;

  const knowledgeAsOf = retrieval?.knowledge_as_of;
  const firmItemsUsed = firm?.firm_items_used ?? 0;
  const priorTurns = session?.prior_turns_used ?? 0;
  const reRan = Boolean(re_retrieval?.fired);
  const verified = verification?.status === "verified";
  const flagged =
    verification?.status === "needs_correction" ||
    verification?.status === "unreliable";

  const showChips = firmItemsUsed > 0 || priorTurns > 0 || reRan || Boolean(verification?.ran);

  const citedCount = retrieval?.candidates.filter((c) => c.cited_in_answer).length ?? 0;
  const supersededCandidates =
    retrieval?.candidates.filter((c) => c.is_superseded || c.is_historical) ?? [];

  const state = promoteState ?? "idle";

  return (
    <Card className="border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium text-foreground"
      >
        <span className="flex items-center gap-1.5">
          <Search className="size-3.5 text-muted-foreground" />
          Why this answer?
        </span>
        <span className="ml-auto flex items-center gap-3">
          {/* 1. Header freshness stamp */}
          {knowledgeAsOf && (
            <span className="hidden items-center gap-1 text-[11px] font-medium text-muted-foreground sm:inline-flex">
              <Clock className="size-3" />
              Knowledge as of {formatFreshness(knowledgeAsOf)}
            </span>
          )}
          {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
        </span>
      </button>

      {open && (
        <CardContent className="border-t border-border pt-3.5 text-sm">
          {/* 2. Provenance summary chips */}
          {showChips && (
            <div className="mb-3.5 flex flex-wrap gap-1.5">
              {firmItemsUsed > 0 && (
                <Badge variant="outline" className="border-accent/30 bg-accent/5 text-accent">
                  <BookOpen className="size-3" />
                  {firmItemsUsed} firm knowledge item{firmItemsUsed === 1 ? "" : "s"}
                </Badge>
              )}
              {priorTurns > 0 && (
                <Badge variant="outline">
                  <MessageSquare className="size-3" />
                  {priorTurns} prior turn{priorTurns === 1 ? "" : "s"}
                </Badge>
              )}
              {reRan && (
                <Badge variant="outline" className="border-amber-600/30 bg-amber-50 text-amber-800">
                  <RotateCcw className="size-3" />
                  Search re-run once
                </Badge>
              )}
              {verified && (
                <Badge variant="outline" className="border-green-600/30 bg-green-50 text-green-700">
                  <Check className="size-3" />
                  Verified against sources
                </Badge>
              )}
              {flagged && (
                <Badge variant="outline" className="border-amber-600/30 bg-amber-50 text-amber-800">
                  Flagged for review
                </Badge>
              )}
            </div>
          )}

          {/* Timeline */}
          <ol className="relative m-0 list-none p-0">
            {/* 3. Firm voice step */}
            {firm && (
              <TimelineStep tone="firm" icon={<BookOpen className="size-2.5" />}>
                <h4 className="text-[13px] font-semibold leading-tight text-foreground">
                  Grounded in your firm&apos;s practice
                </h4>
                <p className="mt-0.5 text-xs leading-normal text-muted-foreground">
                  {firm.profile_summary ? (
                    <>
                      Steered by{" "}
                      <span className="font-medium text-foreground">{firm.profile_summary}</span>.{" "}
                    </>
                  ) : firm.profile_applied || firm.voice_applied ? (
                    <>Steered by your firm&apos;s profile and client voice. </>
                  ) : null}
                  {firmItemsUsed > 0 && (
                    <>
                      <span className="font-medium text-foreground">{firmItemsUsed}</span> of your
                      firm&apos;s own knowledge item{firmItemsUsed === 1 ? "" : "s"} shaped this answer.
                    </>
                  )}
                </p>
                {firm.usage_trend && (
                  <span className="mt-1.5 inline-flex items-center gap-1.5 text-[11px] font-medium text-accent">
                    <TrendingUp className="size-3" />
                    Firm knowledge has informed {firm.usage_trend.quarter_count} answer
                    {firm.usage_trend.quarter_count === 1 ? "" : "s"} this quarter — up from{" "}
                    {firm.usage_trend.prior_count}
                  </span>
                )}
                {firm.firm_items && firm.firm_items.length > 0 && (
                  <details className="mt-2">
                    <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[11px] font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">
                      <ChevronDown className="size-3" />
                      Show the firm items used
                    </summary>
                    <ul className="mt-2 flex list-none flex-col gap-1.5 p-0">
                      {firm.firm_items.map((item, i) => (
                        <li
                          key={i}
                          className={cn(
                            "flex items-center justify-between gap-2 rounded-md border px-2 py-1 text-[11.5px]",
                            item.cited_in_answer
                              ? "border-accent/30 bg-accent/5 text-foreground"
                              : "border-border text-muted-foreground"
                          )}
                        >
                          <span className="flex min-w-0 items-center gap-1.5">
                            <Badge
                              variant="outline"
                              className="h-[18px] border-accent/30 bg-accent/5 px-1.5 text-[10px] text-accent"
                            >
                              firm
                            </Badge>
                            <span className="truncate">{item.citation}</span>
                          </span>
                          <Badge
                            variant="outline"
                            className={cn(
                              "h-[18px] px-1.5 text-[10px]",
                              item.cited_in_answer
                                ? "border-accent/30 text-accent"
                                : "text-muted-foreground"
                            )}
                          >
                            {item.cited_in_answer ? "cited" : "context only"}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </TimelineStep>
            )}

            {/* 4. Engagement step */}
            {session && (priorTurns > 0 || (session.engagement_memos_used ?? 0) > 0) && (
              <TimelineStep tone="default" icon={<MessageSquare className="size-2.5" />}>
                <h4 className="text-[13px] font-semibold leading-tight text-foreground">
                  Continuing this client&apos;s engagement
                </h4>
                <p className="mt-0.5 text-xs leading-normal text-muted-foreground">
                  {priorTurns > 0 && (
                    <>
                      Informed by{" "}
                      <span className="font-medium text-foreground">
                        {priorTurns} earlier turn{priorTurns === 1 ? "" : "s"}
                      </span>{" "}
                      in this conversation
                      {session.client_ref ? (
                        <>
                          {" "}
                          for{" "}
                          <span className="font-medium text-foreground">{session.client_ref}</span>
                        </>
                      ) : null}
                      .{" "}
                    </>
                  )}
                  {(session.engagement_memos_used ?? 0) > 0 && (
                    <>
                      Reused context from{" "}
                      <span className="font-medium text-foreground">
                        {session.engagement_memos_used} engagement memo
                        {session.engagement_memos_used === 1 ? "" : "s"}
                      </span>
                      , so the position stays consistent with earlier advice.
                    </>
                  )}
                </p>
              </TimelineStep>
            )}

            {/* 5. Retrieval step */}
            <TimelineStep tone="default" icon={<Search className="size-2.5" />}>
              <h4 className="text-[13px] font-semibold leading-tight text-foreground">
                Searched the tax knowledge base
              </h4>
              {retrieval ? (
                <>
                  <p className="mt-0.5 text-xs leading-normal text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {retrieval.chunks_considered} source
                      {retrieval.chunks_considered === 1 ? "" : "s"} considered, {citedCount} cited
                    </span>
                    {retrieval.source_type_hint && retrieval.source_type_hint.length > 0
                      ? ` — boosted toward ${retrieval.source_type_hint.join(", ")}`
                      : ""}
                    .
                  </p>
                  {re_retrieval?.fired && (
                    <div className="mt-2 rounded-md border border-amber-600/30 bg-amber-50 px-2.5 py-2 text-[11.5px] leading-normal text-amber-800">
                      <span className="font-semibold">Search was widened and re-run.</span>{" "}
                      {reRetrievalReason(re_retrieval.reason)}, so we broadened the search and ran it
                      again.
                      {re_retrieval.detail ? ` ${re_retrieval.detail}` : ""}
                    </div>
                  )}
                  {retrieval.candidates.length > 0 && (
                    <details className="mt-2">
                      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[11px] font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">
                        <ChevronDown className="size-3" />
                        Show all {retrieval.chunks_considered} source
                        {retrieval.chunks_considered === 1 ? "" : "s"} considered
                      </summary>
                      <ul className="mt-2 flex list-none flex-col gap-1.5 p-0">
                        {retrieval.candidates.map((c) => (
                          <li
                            key={c.n}
                            className={cn(
                              "flex items-center justify-between gap-2 rounded-md border px-2 py-1 text-[11.5px]",
                              c.cited_in_answer
                                ? "border-accent/30 bg-accent/5 text-foreground"
                                : "border-border text-muted-foreground"
                            )}
                          >
                            <span className="flex min-w-0 items-center gap-1.5">
                              <span className="truncate">
                                [{c.n}] {c.citation}
                                {c.source_type
                                  ? ` · ${SOURCE_TYPE_LABELS[c.source_type] ?? c.source_type}`
                                  : ""}
                              </span>
                            </span>
                            <span className="flex shrink-0 items-center gap-1.5">
                              {(c.is_superseded || c.is_historical) && (
                                <Badge
                                  variant="outline"
                                  className="h-[18px] border-amber-600/30 bg-amber-50 px-1.5 text-[10px] text-amber-800"
                                >
                                  <RotateCcw className="size-2.5" />
                                  superseded
                                </Badge>
                              )}
                              <span className="tabular-nums text-[11px] text-muted-foreground">
                                {c.score.toFixed(3)}
                              </span>
                              {c.cited_in_answer ? (
                                <Badge
                                  variant="outline"
                                  className="h-[18px] border-accent/30 px-1.5 text-[10px] text-accent"
                                >
                                  cited
                                </Badge>
                              ) : (
                                <Badge
                                  variant="outline"
                                  className="h-[18px] px-1.5 text-[10px] text-muted-foreground"
                                >
                                  not used
                                </Badge>
                              )}
                            </span>
                          </li>
                        ))}
                      </ul>
                      {supersededCandidates.length > 0 && (
                        <div className="mt-2 rounded-md border border-border bg-muted px-2.5 py-2 text-[11.5px] leading-normal text-muted-foreground">
                          <span className="font-semibold text-amber-800">
                            Superseded source shown, not hidden:
                          </span>{" "}
                          {supersededCandidates.map((c, i) => (
                            <span key={c.n}>
                              {i > 0 ? "; " : ""}
                              <span className="text-foreground">{c.citation}</span>
                              {c.superseded_by ? (
                                <>
                                  {" "}
                                  was{" "}
                                  <span className="text-foreground">
                                    replaced by {c.superseded_by}
                                  </span>
                                </>
                              ) : (
                                " has been superseded"
                              )}
                            </span>
                          ))}
                          . The current version was used for this answer.
                        </div>
                      )}
                    </details>
                  )}
                </>
              ) : (
                <p className="mt-0.5 text-xs leading-normal text-muted-foreground">
                  Served from cache - no new retrieval ran for this exact question.
                </p>
              )}
            </TimelineStep>

            {/* 6. Generation step */}
            <TimelineStep tone="default" icon={<Sparkles className="size-2.5" />}>
              <h4 className="text-[13px] font-semibold leading-tight text-foreground">
                Drafted the answer
              </h4>
              <p className="mt-0.5 text-xs leading-normal text-muted-foreground">
                Answered using{" "}
                <span className="font-medium text-foreground">
                  {MODEL_DESCRIPTIONS[trace.generation.model] ?? trace.generation.model}
                </span>
                {firm?.voice_applied ? ", in your firm's client voice" : ""}.
              </p>
              {typeof trace.generation.confidence === "number" && (
                <p
                  className={cn(
                    "mt-1 text-xs font-medium",
                    relianceBand(trace.generation.confidence).className
                  )}
                >
                  {relianceBand(trace.generation.confidence).label}{" "}
                  <span className="font-normal text-muted-foreground">
                    ({Math.round(trace.generation.confidence * 100)}%)
                  </span>
                </p>
              )}
            </TimelineStep>

            {/* 7. Verification step */}
            <TimelineStep
              tone={verified ? "ok" : flagged ? "warn" : "default"}
              icon={<Check className="size-2.5" />}
              last
            >
              <h4 className="text-[13px] font-semibold leading-tight text-foreground">
                Checked against the cited sources
              </h4>
              {verification?.ran ? (
                <p className="mt-0.5 text-xs leading-normal text-muted-foreground">
                  {stageLabel(verification.status)}
                  {verification.issue_count ? ` (${verification.issue_count} flagged)` : ""}
                  {verification.corrective_pass && trace.corrective_generation
                    ? ` - regenerated by ${trace.corrective_generation.model}.`
                    : "."}
                </p>
              ) : (
                <p className="mt-0.5 text-xs leading-normal text-muted-foreground">
                  Skipped - retrieval/citation signals were strong enough that a verify pass
                  wasn&apos;t triggered.
                </p>
              )}
              {passes?.changed && (
                <div className="mt-2 flex gap-2">
                  <div className="flex-1 rounded-md border border-border px-2.5 py-1.5 text-[11px] text-muted-foreground">
                    <span className="mb-0.5 block text-[10px] uppercase tracking-wide text-muted-foreground">
                      First pass
                    </span>
                    <strong className="font-medium text-foreground line-through decoration-muted-foreground">
                      {passes.first_pass?.model ?? "draft"}
                    </strong>
                    {typeof passes.first_pass?.confidence === "number"
                      ? ` · ${Math.round(passes.first_pass.confidence * 100)}%`
                      : ""}
                  </div>
                  <div className="flex-1 rounded-md border border-green-600/30 bg-green-50 px-2.5 py-1.5 text-[11px] text-muted-foreground">
                    <span className="mb-0.5 block text-[10px] uppercase tracking-wide text-green-700">
                      Corrected answer
                    </span>
                    <strong className="font-semibold text-green-700">
                      {passes.corrected?.model ?? "corrected"}
                    </strong>
                    {typeof passes.corrected?.confidence === "number"
                      ? ` · ${Math.round(passes.corrected.confidence * 100)}%`
                      : ""}
                  </div>
                </div>
              )}
            </TimelineStep>
          </ol>

          {/* 8. Learning-loop footer */}
          {onPromote && (
            <div className="mt-2 flex items-center gap-3 border-t border-border pt-3">
              <span className="text-xs text-muted-foreground">
                <span className="block font-medium text-foreground">
                  Keep this answer in your firm&apos;s knowledge base
                </span>
                Reused as firm guidance for similar questions later.
              </span>
              {state === "saved" ? (
                <Badge
                  variant="outline"
                  className="ml-auto border-green-600/30 bg-green-50 text-green-700"
                >
                  <Check className="size-3" />
                  Sent for approval
                </Badge>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={state === "saving"}
                  onClick={onPromote}
                  className="ml-auto border-accent/30 bg-accent/5 text-accent hover:bg-accent/10 hover:text-accent"
                >
                  <BookOpen className="size-3.5" />
                  {state === "saving" ? "Sending..." : "Suggest for Firm Knowledge"}
                </Button>
              )}
            </div>
          )}
          {state === "error" && (
            <p className="mt-1.5 text-xs text-destructive">
              Could not send for approval - please try again.
            </p>
          )}
        </CardContent>
      )}
    </Card>
  );
}

// One node of the vertical timeline: coloured dot + connector line, matching
// the mockup's firm/ok/warn/default tones.
function TimelineStep({
  tone,
  icon,
  children,
  last,
}: {
  tone: "firm" | "ok" | "warn" | "default";
  icon: React.ReactNode;
  children: React.ReactNode;
  last?: boolean;
}) {
  return (
    <li className={cn("relative pl-[30px]", last ? "pb-1.5" : "pb-[18px]")}>
      {!last && (
        <span
          className="absolute left-[9px] top-5 bottom-0 w-0.5 bg-border"
          aria-hidden
        />
      )}
      <span
        className={cn(
          "absolute left-0 top-0.5 flex size-5 items-center justify-center rounded-full border-[1.5px] bg-card",
          tone === "firm" && "border-accent/30 bg-accent/5 text-accent",
          tone === "ok" && "border-green-600/30 bg-green-50 text-green-700",
          tone === "warn" && "border-amber-600/30 bg-amber-50 text-amber-800",
          tone === "default" && "border-border text-muted-foreground"
        )}
      >
        {icon}
      </span>
      {children}
    </li>
  );
}
