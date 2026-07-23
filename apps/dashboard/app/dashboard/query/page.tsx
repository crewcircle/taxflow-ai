"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  CheckCircle2,
  Copy,
  FileDown,
  FileText,
  HelpCircle,
  MessageCircleQuestion,
  MessageSquare,
  MessagesSquare,
  Pencil,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { QueryHistorySidebar, type QueryListItem } from "@/components/QueryHistorySidebar";
import { ConfirmDialog } from "@/components/resource-actions/ConfirmDialog";
import { useResourceMutation } from "@/components/resource-actions/useResourceMutation";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { SourcesPanel, type SourceCitation } from "@/components/SourcesPanel";
import { AnswerTracePanel, type AnswerTrace } from "@/components/AnswerTracePanel";
import { CollapsedPanelRail } from "@/components/CollapsedPanelRail";
import type { EngagementSelection } from "@/components/EngagementPicker";
import { ConversationBar } from "@/components/ConversationBar";
import { ReResearchBadge } from "@/components/ReResearchBadge";
import { MarkdownDocument } from "@/components/MarkdownDocument";
import { AnnotatableMarkdown, type AnnotatableMarkdownHandle } from "@/components/AnnotatableMarkdown";
import { DocumentTemplatesPanel } from "@/components/DocumentTemplatesPanel";
import { NOTIFICATIONS_UPDATED_EVENT } from "@/lib/useNotifications";

interface DocumentTemplate {
  type: string;
  label: string;
}

interface VerificationIssue {
  claim: string;
  issue: string;
  severity: "critical" | "warning" | "note";
  // The backend's VerificationResult already computes these (see
  // verify.py's VerificationIssue model) - previously dropped before reaching
  // the frontend's trimmed type even though the SSE payload carries them.
  source_says?: string;
  suggested_correction?: string;
}

interface Verification {
  overall_status: "verified" | "needs_correction" | "unreliable" | "parse_error";
  issues: VerificationIssue[];
}

// Phase 4: clarifying questions. The backend returns 1-2 questions, each with
// always-populated selectable options and an optional free-text escape.
interface ClarifyOption {
  label: string;
  value: string;
}

interface ClarifyQuestionUI {
  prompt: string;
  options: ClarifyOption[];
  allow_free_text: boolean;
}

interface QueryResult {
  answer: string;
  citations: SourceCitation[];
  model_used: string | null;
  query_id: string | null;
  askedQuestion: string;
}

const MAX_CHARS = 2000;

function AnswerWithCitationLinks({ text, citations }: { text: string; citations: SourceCitation[] }) {
  return <MarkdownDocument text={text} citations={citations} />;
}

interface FirmKnowledgeSuggestionProps {
  repeatCount: number;
  defaultTitle: string;
  content: string;
}

// Shown after an answer completes when the client has asked essentially the
// same question before (backend-computed repeat_count) - a signal this
// answer is worth keeping as reusable firm guidance rather than re-deriving
// it from scratch next time.
function FirmKnowledgeSuggestion({ repeatCount, defaultTitle, content }: FirmKnowledgeSuggestionProps) {
  const [dismissed, setDismissed] = useState(false);
  const [title, setTitle] = useState(defaultTitle);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (dismissed || repeatCount < 1) return null;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const response = await fetch("/api/firm-knowledge/from-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim() || defaultTitle, content }),
      });
      if (!response.ok) throw new Error("Failed");
      setSaved(true);
    } catch {
      setError("Could not save to Firm Knowledge - please try again");
    } finally {
      setSaving(false);
    }
  }

  if (saved) {
    return (
      <Card className="border-accent/30 bg-accent/5">
        <CardContent className="flex items-center gap-2 py-3 text-sm text-foreground">
          <BookOpen className="size-4 text-accent" />
          Saved to Firm Knowledge.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-accent/30 bg-accent/5">
      <CardContent className="space-y-2 py-3">
        <p className="flex items-center gap-2 text-sm font-medium text-foreground">
          <BookOpen className="size-4 text-accent" />
          You&apos;ve asked something like this {repeatCount === 1 ? "once" : `${repeatCount} times`} before.
        </p>
        <p className="text-sm text-muted-foreground">Save this answer to Firm Knowledge for next time?</p>
        {editing && (
          <Input value={title} onChange={(e) => setTitle(e.target.value)} className="h-8 max-w-md text-sm" />
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="flex flex-wrap gap-2 pt-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="sm" disabled={saving} onClick={handleSave}>
                {saving ? "Saving..." : "Save to Firm Knowledge"}
              </Button>
            </TooltipTrigger>
            <TooltipContent>Saves this answer as reusable firm guidance, so future questions like it can draw on it directly</TooltipContent>
          </Tooltip>
          {!editing && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                  Edit title
                </Button>
              </TooltipTrigger>
              <TooltipContent>Rename this entry before saving - the default title is just the question text</TooltipContent>
            </Tooltip>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" onClick={() => setDismissed(true)}>
                Not now
              </Button>
            </TooltipTrigger>
            <TooltipContent>Dismiss this suggestion - nothing is saved</TooltipContent>
          </Tooltip>
        </div>
      </CardContent>
    </Card>
  );
}

// Phase 4: the clarify card. Shown when the backend decides a first-turn
// question is genuinely ambiguous. Each question shows always-populated,
// selectable option chips plus an optional free-text input; a prominent
// "Skip - just answer" button lets the user bypass clarifying entirely, so
// they are never forced to respond. Submitting re-asks on the SAME session.
function ClarifyCard({
  questions,
  onSubmit,
  onSkip,
  disabled,
}: {
  questions: ClarifyQuestionUI[];
  onSubmit: (answers: { prompt: string; value: string }[]) => void;
  onSkip: () => void;
  disabled: boolean;
}) {
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [freeText, setFreeText] = useState<Record<number, string>>({});

  function answerFor(idx: number): string {
    // A typed free-text answer takes precedence over a selected option.
    const typed = (freeText[idx] ?? "").trim();
    if (typed) return typed;
    return selected[idx] ?? "";
  }

  function handleContinue() {
    const answers = questions
      .map((q, idx) => ({ prompt: q.prompt, value: answerFor(idx) }))
      .filter((a) => a.value);
    onSubmit(answers);
  }

  const hasAnyAnswer = questions.some((_, idx) => answerFor(idx));

  return (
    <Card className="border-accent/30 bg-accent/5">
      <CardContent className="space-y-4 py-4">
        <div className="space-y-1">
          <p className="flex items-center gap-2 text-sm font-medium text-foreground">
            <MessageCircleQuestion className="size-4 text-accent" />
            A couple of quick details will sharpen this answer
          </p>
          <p className="text-sm text-muted-foreground">
            Answer what you can — or skip and I&apos;ll answer with reasonable
            assumptions.
          </p>
        </div>

        {questions.map((q, idx) => (
          <div key={idx} className="space-y-2">
            <p className="text-sm font-medium text-foreground">{q.prompt}</p>
            {q.options.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {q.options.map((opt) => {
                  const isSelected =
                    selected[idx] === opt.value && !(freeText[idx] ?? "").trim();
                  return (
                    <Button
                      key={opt.value}
                      type="button"
                      size="sm"
                      variant={isSelected ? "default" : "outline"}
                      disabled={disabled}
                      onClick={() => {
                        setSelected((prev) => ({ ...prev, [idx]: opt.value }));
                        setFreeText((prev) => ({ ...prev, [idx]: "" }));
                      }}
                    >
                      {opt.label}
                    </Button>
                  );
                })}
              </div>
            )}
            {q.allow_free_text && (
              <Input
                value={freeText[idx] ?? ""}
                onChange={(e) =>
                  setFreeText((prev) => ({ ...prev, [idx]: e.target.value }))
                }
                placeholder="Or type your own answer..."
                className="h-8 max-w-md text-sm"
                disabled={disabled}
              />
            )}
          </div>
        ))}

        <div className="flex flex-wrap gap-2 pt-1">
          <Button size="sm" disabled={disabled || !hasAnyAnswer} onClick={handleContinue}>
            Continue
          </Button>
          <Button variant="ghost" size="sm" disabled={disabled} onClick={onSkip}>
            Skip &amp; answer anyway
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// Phase 4: suggested follow-up chips rendered beneath a finished answer.
// Clicking a chip re-asks that question on the SAME session (conversation
// continuity), just like typing a follow-up.
function FollowUpChips({
  questions,
  onPick,
  disabled,
}: {
  questions: string[];
  onPick: (question: string) => void;
  disabled: boolean;
}) {
  if (questions.length === 0) return null;
  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <HelpCircle className="size-3.5" />
        Ask a follow-up
      </p>
      <div className="flex flex-wrap gap-2">
        {questions.map((q, idx) => (
          <Button
            key={idx}
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => onPick(q)}
          >
            {q}
          </Button>
        ))}
      </div>
    </div>
  );
}

interface AnswerActionsBarProps {
  queryId: string | null;
  onReResearchEnqueued: () => void;
  copied: boolean;
  onCopy: () => void;
  savedDocId: string | null;
  savingDoc: boolean;
  docType: string;
  onDocTypeChange: (v: string) => void;
  templates: DocumentTemplate[];
  onSave: () => void;
  clientRef: string;
  onEditAnswer: () => void;
}

// Everything you can do with a finished answer, in one row: rate it (Task
// C9 - thumbs-up sends it for Firm Knowledge approval, thumbs-down WITH a
// note enqueues an async re-research per C2), say who it's for, copy the
// text, or pick a format and save it as a document (which picks up the
// client tag automatically). Combined into a single block per feedback that
// two separate boxes made the relationship between them unclear - only the
// thumbs-down note editor drops to its own line below.
function AnswerActionsBar({
  queryId,
  onReResearchEnqueued,
  copied,
  onCopy,
  savedDocId,
  savingDoc,
  docType,
  onDocTypeChange,
  templates,
  onSave,
  clientRef,
  onEditAnswer,
}: AnswerActionsBarProps) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [editDocOpen, setEditDocOpen] = useState(false);
  const [editDocLoading, setEditDocLoading] = useState(false);
  const [editDocSaving, setEditDocSaving] = useState(false);
  const [editDocTitle, setEditDocTitle] = useState("");
  const [editDocContent, setEditDocContent] = useState("");
  const [editDocError, setEditDocError] = useState<string | null>(null);
  const selectedTemplateLabel = templates.find((t) => t.type === docType)?.label ?? "document";

  async function openEditDoc() {
    if (!savedDocId) return;
    setEditDocOpen(true);
    setEditDocLoading(true);
    setEditDocError(null);
    try {
      const res = await fetch(`/api/documents/${savedDocId}`);
      if (!res.ok) throw new Error("load failed");
      const doc: { title: string; content_md: string } = await res.json();
      setEditDocTitle(doc.title);
      setEditDocContent(doc.content_md);
    } catch {
      setEditDocError("Could not load this document - please try again");
    } finally {
      setEditDocLoading(false);
    }
  }

  async function saveEditDoc() {
    if (!savedDocId || !editDocContent.trim()) return;
    setEditDocSaving(true);
    setEditDocError(null);
    try {
      const res = await fetch(`/api/documents/${savedDocId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: editDocTitle.trim() || undefined, content_md: editDocContent }),
      });
      if (!res.ok) throw new Error("save failed");
      setEditDocOpen(false);
    } catch {
      setEditDocError("Could not save your changes - please try again");
    } finally {
      setEditDocSaving(false);
    }
  }
  // Terminal states after a successful feedback submit.
  const [outcome, setOutcome] = useState<"re_researching" | "sent_for_approval" | "recorded" | null>(null);

  async function submitFeedback(chosenRating: "up" | "down", chosenNote: string) {
    if (!queryId) return;
    setSubmitting(true);
    setFeedbackError(null);
    try {
      const response = await fetch(`/api/query/${queryId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: chosenRating, note: chosenNote.trim() || undefined }),
      });
      if (!response.ok) throw new Error("Failed");
      const data: { re_research_enqueued?: boolean } = await response.json();
      if (chosenRating === "up") {
        setOutcome("sent_for_approval");
      } else if (data.re_research_enqueued) {
        // Show "Re-researching..." immediately, then refresh history so the
        // row's re_research_status badge (C7) reflects the persisted state.
        setOutcome("re_researching");
        onReResearchEnqueued();
      } else {
        setOutcome("recorded");
      }
    } catch {
      setFeedbackError("Could not record your feedback - please try again");
    } finally {
      setSubmitting(false);
    }
  }

  const feedbackSegment =
    outcome === "sent_for_approval" ? (
      <span className="flex items-center gap-1.5 text-sm text-foreground">
        <BookOpen className="size-4 text-accent" />
        Sent for approval
      </span>
    ) : outcome === "re_researching" ? (
      <span className="flex items-center gap-1.5 text-sm text-foreground">
        <ReResearchBadge status="pending" />
        Re-researching...
      </span>
    ) : outcome === "recorded" ? (
      <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <CheckCircle2 className="size-4 text-green-600" />
        Thanks for the feedback
      </span>
    ) : (
      <div className="flex items-center gap-1">
        <span className="mr-0.5 text-xs text-muted-foreground">Helpful?</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={rating === "up" ? "secondary" : "ghost"}
              size="icon-sm"
              disabled={submitting}
              onClick={() => submitFeedback("up", "")}
              aria-label="Yes, this was helpful"
            >
              <ThumbsUp className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Suggests this answer for Firm Knowledge (a partner approves it before it&apos;s used)</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={rating === "down" ? "secondary" : "ghost"}
              size="icon-sm"
              disabled={submitting}
              onClick={() => setRating("down")}
              aria-label="No, this wasn't helpful"
            >
              <ThumbsDown className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Tell us what&apos;s wrong and we&apos;ll re-research it in the background</TooltipContent>
        </Tooltip>
      </div>
    );

  return (
    <div className="space-y-2 rounded-xl border border-border bg-muted/30 p-2.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {savedDocId ? (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button asChild variant="secondary" size="sm">
                    <Link href="/dashboard/workspace">View saved document →</Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Opens the Documents list where this was just saved</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="outline" size="sm" onClick={openEditDoc}>
                    <Pencil className="size-3.5" />
                    Edit document
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Edit the saved document&apos;s title and text directly</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="sm" onClick={() => setTemplateDialogOpen(true)}>
                    Customize template
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  Edit the {selectedTemplateLabel.toLowerCase()} drafting template used for future answers - this
                  doesn&apos;t change the document you just saved
                </TooltipContent>
              </Tooltip>
            </>
          ) : (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button size="sm" disabled={savingDoc} onClick={onSave}>
                    <FileDown className="size-3.5" />
                    {savingDoc ? "Saving..." : `Save as ${selectedTemplateLabel}`}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  Saves this answer as a new {selectedTemplateLabel.toLowerCase()}{" "}
                  under Documents{clientRef.trim() ? `, tagged to ${clientRef.trim()}` : " (no client tagged)"}
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Select value={docType} onValueChange={onDocTypeChange}>
                    <SelectTrigger size="sm" className="w-[180px] bg-background">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {templates.map((t) => (
                        <SelectItem key={t.type} value={t.type}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TooltipTrigger>
                <TooltipContent>Choose the document style to generate - e.g. an advice memo vs. a client letter</TooltipContent>
              </Tooltip>
            </>
          )}

          {queryId && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={onEditAnswer}>
                  <Pencil className="size-3.5" />
                  Edit
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Edit this answer&apos;s text - saving clears the automated verification status, since it no longer describes your edited wording
              </TooltipContent>
            </Tooltip>
          )}
        </div>

        {queryId && (
          <div className="flex shrink-0 items-center gap-2 border-l border-border pl-3">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={onCopy}>
                  <Copy className="size-3.5" />
                  {copied ? "Copied!" : "Copy"}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Copies the plain answer text to your clipboard - handy for pasting into an email or another
                document
              </TooltipContent>
            </Tooltip>
            {feedbackSegment}
          </div>
        )}
      </div>

      {rating === "down" && outcome === null && (
        <div className="space-y-2">
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="What was wrong or missing? A note is required to trigger a re-research."
          />
          <div className="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                {/* wrapper span so the tooltip still shows when the button is disabled */}
                <span>
                  <Button
                    size="sm"
                    disabled={submitting || !note.trim()}
                    onClick={() => submitFeedback("down", note)}
                  >
                    {submitting ? "Submitting..." : "Submit & re-research"}
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>Re-researches this answer in the background with your note as the correction</TooltipContent>
            </Tooltip>
            <Button
              variant="ghost"
              size="sm"
              disabled={submitting}
              onClick={() => {
                setRating(null);
                setNote("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {feedbackError && <p className="text-sm text-destructive">{feedbackError}</p>}

      <Sheet open={templateDialogOpen} onOpenChange={setTemplateDialogOpen}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Document templates</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <DocumentTemplatesPanel initialKey={docType} />
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={editDocOpen} onOpenChange={setEditDocOpen}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Edit saved document</SheetTitle>
          </SheetHeader>
          {editDocLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
              <div className="space-y-1.5">
                <Label htmlFor="edit_doc_title">Title</Label>
                <Input id="edit_doc_title" value={editDocTitle} onChange={(e) => setEditDocTitle(e.target.value)} />
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-1.5">
                <Label htmlFor="edit_doc_content">Content</Label>
                <Textarea
                  id="edit_doc_content"
                  value={editDocContent}
                  onChange={(e) => setEditDocContent(e.target.value)}
                  className="flex-1 resize-none font-mono text-xs"
                />
              </div>
              {editDocError && <p className="text-sm text-destructive">{editDocError}</p>}
            </div>
          )}
          <SheetFooter>
            <Button variant="outline" onClick={() => setEditDocOpen(false)} disabled={editDocSaving}>
              Cancel
            </Button>
            <Button onClick={saveEditDoc} disabled={editDocSaving || editDocLoading || !editDocContent.trim()}>
              {editDocSaving ? "Saving..." : "Save"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}

// The single info bar for a finished answer - trust status, how many
// sources it drew on (click opens the Sources panel), and the annotation
// hint. These used to be three separate things scattered around the answer
// (a verification ribbon above "You asked", a source count only visible by
// opening the panel, a hint reprinted per-answer) - consolidated into one
// row directly under the question so there's exactly one place to look for
// "what do I need to know about this response" instead of hunting around it.
// Hex values in the flagged-claim buttons must match the underline color
// AnnotatableMarkdown's RecogitoLayer gives each severity (see the `style`
// callback there) - critical #dc2626 is Tailwind red-600, warning #d97706 is
// Tailwind amber-600 - so the label IS that highlight, not just a near match.
function AnswerInfoBar({
  verifying,
  verification,
  sourceCount,
  onOpenSources,
  onFocusFlag,
}: {
  verifying: boolean;
  verification: Verification | null;
  sourceCount: number;
  onOpenSources: () => void;
  onFocusFlag: (severity: "critical" | "warning") => void;
}) {
  const critical = verification?.issues.filter((i) => i.severity === "critical") ?? [];
  const warning = verification?.issues.filter((i) => i.severity === "warning") ?? [];
  const clean =
    verification != null &&
    verification.overall_status !== "parse_error" &&
    (verification.overall_status === "verified" || verification.issues.length === 0);
  const showFlags = verification != null && verification.overall_status !== "parse_error" && !clean;

  return (
    <div className="flex flex-wrap items-center gap-4 rounded-lg bg-muted px-3 py-2 text-sm">
      {verifying && (
        <Badge variant="outline" className="text-muted-foreground">
          Verifying...
        </Badge>
      )}
      {!verifying && clean && (
        <span className="flex items-center gap-1.5 text-green-700">
          <CheckCircle2 className="size-4" />
          Verified against sources
        </span>
      )}
      {!verifying && showFlags && (
        <>
          {critical.length > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => onFocusFlag("critical")}
                  className="flex items-center gap-1.5 text-red-600 hover:underline"
                >
                  <span className="size-2 rounded-full bg-red-600" />
                  {critical.length} claim{critical.length === 1 ? "" : "s"} need review
                </button>
              </TooltipTrigger>
              <TooltipContent>Click to jump to each flagged claim in the answer, one at a time</TooltipContent>
            </Tooltip>
          )}
          {warning.length > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => onFocusFlag("warning")}
                  className="flex items-center gap-1.5 text-amber-600 hover:underline"
                >
                  <span className="size-2 rounded-full bg-amber-600" />
                  {warning.length} worth a second look
                </button>
              </TooltipTrigger>
              <TooltipContent>Click to jump to each flagged claim in the answer, one at a time</TooltipContent>
            </Tooltip>
          )}
        </>
      )}

      {sourceCount > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onOpenSources}
              className="flex items-center gap-1.5 text-accent hover:underline"
            >
              <FileText className="size-3.5" />
              Used {sourceCount} source{sourceCount === 1 ? "" : "s"}
            </button>
          </TooltipTrigger>
          <TooltipContent>Opens the Sources panel with every passage this answer drew on</TooltipContent>
        </Tooltip>
      )}

      <span className="ml-auto flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground">
        <MessageSquare className="size-3.5" />
        Select any text to ask a question or leave a note
      </span>
    </div>
  );
}

// Isolated and memoized so unrelated state churn elsewhere in QueryPage
// (history/notifications polling, sidebar UI state, etc - anything that
// doesn't touch queryId/answer/citations/verificationIssues/streamComplete)
// can never re-render, let alone remount, this specific subtree. Investigated
// a live, reproducible bug where this exact block rendered 2-10+ times,
// stacked vertically, growing over time with zero user interaction and no
// additional route navigation - correlated with (but not proven caused by)
// an accelerating notifications-poll -> loadHistory -> setHistory chain
// elsewhere in this component. Extracting + memoizing the answer body is a
// defensive, verifiable mitigation regardless of the exact framework-level
// mechanism: this component's own props are referentially stable across a
// setHistory-driven re-render (result/verification objects aren't touched by
// it), so React.memo bails out here even if something upstream misbehaves.
const AnswerBody = memo(function AnswerBody({
  annotatableRef,
  queryId,
  answer,
  citations,
  verificationIssues,
  streamComplete,
}: {
  annotatableRef: React.RefObject<AnnotatableMarkdownHandle | null>;
  queryId: string | null;
  answer: string;
  citations: SourceCitation[];
  verificationIssues?: VerificationIssue[];
  streamComplete: boolean;
}) {
  return streamComplete && queryId ? (
    // Annotation layer is enabled ONLY after the stream is [DONE]
    // (streamComplete) and a persisted query_id exists — offsets/hash are
    // computed against the final persisted answer, never the mid-stream
    // buffer (a correction event can replace the whole answer). A restored
    // history conversation sets streamComplete immediately since it is
    // already persisted.
    <AnnotatableMarkdown
      ref={annotatableRef}
      key={queryId}
      targetType="query_answer"
      targetId={queryId}
      sourceMarkdown={answer}
      citations={citations}
      verificationIssues={verificationIssues}
      showHint={false}
    />
  ) : (
    <AnswerWithCitationLinks text={answer} citations={citations} />
  );
});

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [clientRef, setClientRef] = useState("");
  // Phase 2: the chosen first-class engagement. Selecting one also mirrors the
  // end-client name into clientRef so the legacy client_ref plumbing (history
  // highlighting, document tagging) keeps working alongside engagement_id.
  const [engagement, setEngagement] = useState<EngagementSelection | null>(null);
  // Session memory (Task D3): a UUID minted per conversation and reused across
  // every follow-up so the backend can load prior turns for this session. Reset
  // to a fresh id on "new question" / when loading a different past query, so
  // context never leaks across unrelated conversations.
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  // True only once the answer is authoritative: a live stream has emitted
  // [DONE] (after any correction/regeneration), or a persisted conversation was
  // loaded from history. The annotation layer mounts ONLY when this is true, so
  // offsets/hashes are never computed against a mid-stream buffer.
  const [streamComplete, setStreamComplete] = useState(false);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [trace, setTrace] = useState<AnswerTrace | null>(null);
  // Phase 4: the clarify card (shown instead of an answer when the backend asks
  // for clarification) and the follow-up chips (shown beneath a finished answer).
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestionUI[] | null>(null);
  const [clarifyAskedQuestion, setClarifyAskedQuestion] = useState("");
  const [followUps, setFollowUps] = useState<string[]>([]);
  const [promoteState, setPromoteState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [repeatCount, setRepeatCount] = useState(0);
  const [copied, setCopied] = useState(false);
  // Closed by default - the conversation-level picker in the top bar now
  // handles "which conversation am I in," so this panel is an opt-in
  // chronological search/browse view, not the primary navigation surface.
  const [historyOpen, setHistoryOpen] = useState(false);
  // Collapsed by default - a citation superscript click (href="#source-N")
  // reveals it and jumps straight to the matching excerpt (see the
  // hashchange effect below), rather than it permanently occupying the
  // right column for every answer.
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [historyHighlighted, setHistoryHighlighted] = useState(false);

  const [history, setHistory] = useState<QueryListItem[]>([]);
  // session_id -> label, for engagements the user has renamed (Task #15).
  const [sessionLabels, setSessionLabels] = useState<Record<string, string>>({});
  const [editingLabel, setEditingLabel] = useState(false);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [docType, setDocType] = useState("advice_memo");
  const [savingDoc, setSavingDoc] = useState(false);
  const [savedDocId, setSavedDocId] = useState<string | null>(null);
  const [highlightedHistoryId, setHighlightedHistoryId] = useState<string | null>(null);
  const [deleteQueryTarget, setDeleteQueryTarget] = useState<QueryListItem | null>(null);
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<string | null>(null);
  const [editingAnswer, setEditingAnswer] = useState(false);
  const [answerDraft, setAnswerDraft] = useState("");
  const [savingAnswer, setSavingAnswer] = useState(false);

  const hasAutoLoaded = useRef(false);
  // Lets TrustRibbon (a sibling of AnnotatableMarkdown here, not a parent)
  // drive "jump to next flagged claim" without owning any Recogito state.
  const annotatableRef = useRef<AnnotatableMarkdownHandle>(null);

  const loadHistory = useCallback(() => {
    fetch("/api/query")
      .then((r) => (r.ok ? r.json() : []))
      .then(setHistory)
      .catch(() => {});
  }, []);

  useEffect(loadHistory, [loadHistory]);

  const mutation = useResourceMutation({ onSuccess: loadHistory });

  const loadSessionLabels = useCallback(() => {
    fetch("/api/query/sessions")
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: { session_id: string; label: string | null }[]) => {
        const labels: Record<string, string> = {};
        for (const row of rows) if (row.label) labels[row.session_id] = row.label;
        setSessionLabels(labels);
      })
      .catch(() => {});
  }, []);

  useEffect(loadSessionLabels, [loadSessionLabels]);

  async function saveSessionLabel(label: string) {
    const trimmed = label.trim();
    if (!trimmed) {
      setEditingLabel(false);
      return;
    }
    setSessionLabels((prev) => ({ ...prev, [sessionId]: trimmed }));
    setEditingLabel(false);
    await fetch(`/api/query/sessions/${sessionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: trimmed }),
    }).catch(() => {});
  }

  // The notification poll (dashboard chrome) fires this event whenever a fresh
  // batch arrives - an `answer_improved` notification means a query's
  // re_research_status just flipped to "done", so reload the history to update
  // its inline badge.
  useEffect(() => {
    window.addEventListener(NOTIFICATIONS_UPDATED_EVENT, loadHistory);
    return () => window.removeEventListener(NOTIFICATIONS_UPDATED_EVENT, loadHistory);
  }, [loadHistory]);

  // A citation superscript in the answer is a real <a href="#source-N"> (see
  // MarkdownDocument's linkifyCitations). The browser's native anchor-jump
  // fires on click, before React has committed the panel into the DOM if it
  // was collapsed - so that first jump finds nothing. Reveal the panel here,
  // then re-run the scroll (and :target-style highlight via a manual class,
  // since a hash that hasn't changed won't retrigger :target) once the
  // element actually exists.
  useEffect(() => {
    function openOnSourceHash() {
      const hash = window.location.hash;
      if (!/^#source-\d+$/.test(hash)) return;
      setSourcesOpen(true);
      requestAnimationFrame(() => {
        document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
    openOnSourceHash();
    window.addEventListener("hashchange", openOnSourceHash);
    return () => window.removeEventListener("hashchange", openOnSourceHash);
  }, []);

  // Header "Questions asked" link deep-links here with ?focus=history so it can
  // open the history sidebar (or just flash it if already open) from any page.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("focus") !== "history") return;
    window.history.replaceState(null, "", window.location.pathname);
    const openTimer = setTimeout(() => {
      setHistoryOpen(true);
      setHistoryHighlighted(true);
    }, 0);
    const clearTimer = setTimeout(() => setHistoryHighlighted(false), 1500);
    return () => {
      clearTimeout(openTimer);
      clearTimeout(clearTimer);
    };
  }, []);

  useEffect(() => {
    fetch("/api/documents/templates")
      .then((r) => (r.ok ? r.json() : []))
      .then(setTemplates)
      .catch(() => {});
  }, []);


  function resetPane() {
    setResult(null);
    setStreamComplete(false);
    setStreamedAnswer("");
    setVerification(null);
    setVerifying(false);
    setTrace(null);
    setPromoteState("idle");
    setRepeatCount(0);
    setSavedDocId(null);
    setDocType("advice_memo");
    setError(null);
    // Phase 4: clear any prior clarify card / follow-up chips.
    setClarifyQuestions(null);
    setClarifyAskedQuestion("");
    setFollowUps([]);
  }

  // Fetches a past query's full detail (answer + citations + verification)
  // and shows it exactly as it was, so browsing history reads like a real
  // conversation log rather than just a list of question text to re-ask.
  async function loadConversation(item: QueryListItem) {
    resetPane();
    setQuestion("");
    setClientRef(item.client_ref ?? "");
    // The top bar's Client/Engagement/Conversation picker must reflect what's
    // actually loaded, not sit empty - `item` already carries the engagement
    // fields the history list joins in, so no extra fetch is needed. Bypasses
    // handleEngagementChange (its null branch resets the pane we're mid-way
    // through populating).
    if (
      item.engagement_id &&
      item.engagement_number != null &&
      item.engagement_description &&
      item.firm_client_id &&
      item.firm_client_name
    ) {
      setEngagement({
        engagement: {
          id: item.engagement_id,
          firm_client_id: item.firm_client_id,
          engagement_number: item.engagement_number,
          description: item.engagement_description,
          status: "active",
        },
        clientName: item.firm_client_name,
      });
    } else {
      setEngagement(null);
    }
    try {
      const response = await fetch(`/api/query/${item.id}`);
      if (!response.ok) return;
      const data = await response.json();
      setResult({
        answer: data.final_answer ?? "",
        citations: data.citations ?? [],
        model_used: data.model_used,
        query_id: data.id ?? item.id,
        askedQuestion: data.question ?? item.question,
      });
      // A restored conversation is already persisted and authoritative, so the
      // annotation layer may mount immediately.
      setStreamComplete(true);
      // Continue the restored conversation: reuse its session_id so a typed
      // follow-up folds into that session's context rather than starting a new
      // one. Fall back to a freshly-minted id if the row predates session_id.
      setSessionId(data.session_id ?? crypto.randomUUID());
      if (data.verification_result?.overall_status) {
        setVerification(data.verification_result);
      }
      if (data.trace) {
        setTrace(data.trace);
      }
    } catch {
      setError("Could not load this question");
    }
  }

  // Session continuity: the first time history loads with content, resume
  // straight into the most recent conversation as if the user never left -
  // unless the header's tag dropdown deep-linked here with ?tag=X, in which
  // case jump to and highlight the newest question carrying that tag instead.
  useEffect(() => {
    if (hasAutoLoaded.current || history.length === 0) return;
    hasAutoLoaded.current = true;

    const tag = new URLSearchParams(window.location.search).get("tag");
    const queryParam = new URLSearchParams(window.location.search).get("query");
    // A notification (e.g. "answer improved") deep-links here with ?query=<id>
    // so clicking it opens the exact re-researched conversation.
    const queryMatch = queryParam ? history.find((h) => h.id === queryParam) : null;
    if (queryMatch) {
      window.history.replaceState(null, "", window.location.pathname);
      const openTimer = setTimeout(() => {
        setHistoryOpen(true);
        setHighlightedHistoryId(queryMatch.id);
        loadConversation(queryMatch);
      }, 0);
      const clearTimer = setTimeout(() => setHighlightedHistoryId(null), 2000);
      return () => {
        clearTimeout(openTimer);
        clearTimeout(clearTimer);
      };
    }

    const tagMatch = tag ? history.find((h) => h.topic_tag === tag) : null;
    if (tagMatch) {
      window.history.replaceState(null, "", window.location.pathname);
      const openTimer = setTimeout(() => {
        setHistoryOpen(true);
        setHighlightedHistoryId(tagMatch.id);
        loadConversation(tagMatch);
      }, 0);
      const clearTimer = setTimeout(() => setHighlightedHistoryId(null), 2000);
      return () => {
        clearTimeout(openTimer);
        clearTimeout(clearTimer);
      };
    }

    const t = setTimeout(() => loadConversation(history[0]), 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history]);

  // A new conversation is a new thread WITHIN the current engagement, not a
  // reset of which client/engagement the work is billed to.
  function handleNewConversation() {
    setQuestion("");
    setSessionId(crypto.randomUUID());
    resetPane();
  }

  // Selecting an engagement mirrors its end-client into clientRef so the legacy
  // client_ref plumbing (document tagging, history highlighting) keeps working.
  // Clearing it (switching to a different client in the top bar, before an
  // engagement under them is chosen) resets the whole pane the same way a
  // fresh question does - the old engagement's answer shouldn't linger under
  // a client it no longer belongs to.
  function handleEngagementChange(selection: EngagementSelection | null) {
    setEngagement(selection);
    if (selection) {
      setClientRef(selection.clientName);
    } else {
      setClientRef("");
      setQuestion("");
      setSessionId(crypto.randomUUID());
      resetPane();
    }
  }

  // Selecting a past question - from the sidebar or a scenario tag - shows
  // that conversation (answer + sources), same as the auto-loaded most
  // recent one. The ask box is left as-is so the user can type a follow-up.
  function handleSelectHistory(id: string) {
    const item = history.find((h) => h.id === id);
    if (!item) return;
    // loadConversation restores the item's answer/sources AND its session_id, so
    // a follow-up continues that conversation's context (D3 session memory).
    loadConversation(item);
  }

  function openEditAnswer() {
    if (!result) return;
    setAnswerDraft(result.answer);
    setEditingAnswer(true);
  }

  async function saveAnswerEdit() {
    if (!result?.query_id) return;
    const edited = answerDraft.trim();
    if (!edited) return;
    setSavingAnswer(true);
    try {
      const response = await fetch(`/api/query/${result.query_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ final_answer: edited }),
      });
      if (!response.ok) throw new Error("Failed");
      // Reflect the edit locally and clear the now-stale verification UI: the
      // backend has cleared verification_result + citation validity + the
      // trace's verification block, so drop them from the pane too.
      setResult((prev) => (prev ? { ...prev, answer: edited } : prev));
      setVerification(null);
      setTrace((prev) => (prev ? { ...prev, verification: { ran: false } } : prev));
      setEditingAnswer(false);
      loadHistory();
    } catch {
      setError("Could not save your edit - please try again");
    } finally {
      setSavingAnswer(false);
    }
  }

  async function handleSubmit(options?: {
    questionOverride?: string;
    clarifications?: { prompt: string; value: string }[];
  }) {
    setLoading(true);
    resetPane();
    // Snapshot the question text now - the textarea stays editable for a
    // follow-up while this streams, and the result must stay tied to what
    // was actually asked, not whatever the box holds when the stream ends.
    // Phase 4: a clarify round-trip / follow-up chip re-asks a specific
    // question (questionOverride) that may differ from the textarea contents.
    const askedQuestion = options?.questionOverride ?? question;
    const clarifications = options?.clarifications;

    try {
      const gate = await fetch("/api/query/stream?question=", { method: "HEAD" }).catch(() => null);
      if (gate && gate.status === 402) {
        window.location.assign("/upgrade");
        return;
      }

      const streamUrl = `/api/query/stream?question=${encodeURIComponent(askedQuestion)}${
        clientRef.trim() ? `&client_ref=${encodeURIComponent(clientRef.trim())}` : ""
      }${
        engagement ? `&engagement_id=${encodeURIComponent(engagement.engagement.id)}` : ""
      }&session_id=${encodeURIComponent(sessionId)}${
        clarifications
          ? `&clarifications=${encodeURIComponent(JSON.stringify(clarifications))}`
          : ""
      }`;
      const source = new EventSource(streamUrl);
      let answer = "";
      let citations: SourceCitation[] = [];

      await new Promise<void>((resolve, reject) => {
        source.onmessage = (event) => {
          if (event.data === "[DONE]") {
            source.close();
            // Stream is finished and every correction has been applied, so the
            // displayed answer now matches the persisted queries.final_answer.
            // Only now is it safe to anchor annotations against it.
            setStreamComplete(true);
            resolve();
            return;
          }
          const parsed: {
            type: string;
            text?: string;
            citations?: SourceCitation[];
            query_id?: string;
            answer?: string;
            caveat?: string | null;
            model_used?: string | null;
            overall_status?: Verification["overall_status"];
            issues?: VerificationIssue[];
            count?: number;
            questions?: ClarifyQuestionUI[] | string[];
            retrieval?: AnswerTrace["retrieval"];
            generation?: AnswerTrace["generation"];
            verification?: AnswerTrace["verification"];
            corrective_generation?: AnswerTrace["corrective_generation"];
            firm?: AnswerTrace["firm"];
            session?: AnswerTrace["session"];
            re_retrieval?: AnswerTrace["re_retrieval"];
            passes?: AnswerTrace["passes"];
          } = JSON.parse(event.data);

          if (parsed.type === "token" && parsed.text) {
            answer += parsed.text;
            setStreamedAnswer(answer);
          } else if (parsed.type === "clarify") {
            // Phase 4: the backend asked a clarifying question instead of
            // answering. Stop the spinner and render the clarify card; the
            // round-trip re-asks THIS same question on the same session.
            setClarifyQuestions((parsed.questions as ClarifyQuestionUI[]) ?? []);
            setClarifyAskedQuestion(askedQuestion);
            setVerifying(false);
          } else if (parsed.type === "follow_ups") {
            // Phase 4: suggested next questions, rendered as chips beneath the
            // finished answer once it arrives.
            setFollowUps((parsed.questions as string[]) ?? []);
          } else if (parsed.type === "final") {
            citations = parsed.citations ?? [];
            // A cache hit streams the whole answer as one token event, so pick it
            // up here if we didn't accumulate it token-by-token.
            if (!answer && parsed.answer) answer = parsed.answer;
            setResult({
              answer,
              citations,
              model_used: parsed.model_used ?? null,
              query_id: parsed.query_id ?? null,
              askedQuestion,
            });
            setVerifying(true);
          } else if (parsed.type === "correction") {
            // The verify pass produced a caveat or a corrective regeneration
            // replaced the streamed answer. Replace what we displayed so the UI
            // matches the authoritative stored answer (queries.final_answer).
            answer = parsed.answer ?? answer;
            citations = parsed.citations ?? citations;
            setStreamedAnswer(answer);
            setResult((prev) =>
              prev
                ? { ...prev, answer, citations, model_used: parsed.model_used ?? prev.model_used }
                : { answer, citations, model_used: parsed.model_used ?? null, query_id: null, askedQuestion },
            );
          } else if (parsed.type === "verification") {
            setVerifying(false);
            setVerification({
              overall_status: parsed.overall_status ?? "parse_error",
              issues: parsed.issues ?? [],
            });
            loadHistory();
          } else if (parsed.type === "repeat_count") {
            setRepeatCount(parsed.count ?? 0);
          } else if (parsed.type === "trace" && parsed.generation) {
            setTrace({
              retrieval: parsed.retrieval ?? null,
              generation: parsed.generation,
              verification: parsed.verification ?? null,
              corrective_generation: parsed.corrective_generation,
              firm: parsed.firm ?? null,
              session: parsed.session ?? null,
              re_retrieval: parsed.re_retrieval ?? null,
              passes: parsed.passes ?? null,
            });
          }
        };
        source.onerror = () => {
          source.close();
          reject(new Error("stream failed"));
        };
      });
    } catch {
      setError("Query failed - please try again");
    } finally {
      setLoading(false);
    }
  }

  // Learning loop (approval-gated): suggest the finished answer for firm
  // knowledge. Posts to the approval-gated /suggestions endpoint (a partner
  // approves it before it becomes authoritative firm knowledge) - NOT the
  // direct from-text save.
  async function handlePromote() {
    if (!result) return;
    setPromoteState("saving");
    try {
      const response = await fetch("/api/firm-knowledge/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: result.askedQuestion.slice(0, 80),
          content: result.answer,
          source_query_id: result.query_id,
        }),
      });
      if (!response.ok) throw new Error("Failed");
      setPromoteState("saved");
    } catch {
      setPromoteState("error");
    }
  }

  async function handleCopy() {
    if (!result) return;
    await navigator.clipboard.writeText(result.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleSaveAsDocument() {
    if (!result) return;
    setSavingDoc(true);
    try {
      const response = await fetch("/api/documents/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query_id: result.query_id,
          document_type: docType,
          title: result.askedQuestion.slice(0, 80),
          content_md: result.answer,
          client_ref: clientRef.trim() || null,
          engagement_id: engagement?.engagement.id ?? null,
        }),
      });
      if (!response.ok) throw new Error("Failed");
      const doc = await response.json();
      setSavedDocId(doc.id);
    } catch {
      setError("Could not save as a document - please try again");
    } finally {
      setSavingDoc(false);
    }
  }

  const displayedCitations = result?.citations ?? [];

  return (
    <div className="flex h-[calc(100vh-8rem)] min-h-[420px] w-full min-w-0 overflow-hidden rounded-xl border border-border">
      {historyOpen ? (
        <div
          className={
            historyHighlighted ? "ring-2 ring-accent ring-inset transition-shadow duration-300" : "transition-shadow duration-300"
          }
        >
          <QueryHistorySidebar
            history={history}
            onSelect={handleSelectHistory}
            onHide={() => setHistoryOpen(false)}
            onDeleteQuery={(id) => {
              const item = history.find((h) => h.id === id) ?? null;
              setDeleteQueryTarget(item);
            }}
            onDeleteSession={(sid) => setDeleteSessionTarget(sid)}
            highlightedId={highlightedHistoryId}
            sessionLabels={sessionLabels}
          />
        </div>
      ) : (
        <CollapsedPanelRail
          side="left"
          label="Show questions"
          icon={MessagesSquare}
          onShow={() => setHistoryOpen(true)}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* The single, always-visible answer to "which engagement is this?" -
            billing is per-engagement, so client + engagement live here, at
            the top, instead of being split across a session-label header, a
            client field lower down, and a picker buried in the ask box. */}
        <div className="shrink-0 border-b border-border p-4 pb-3">
          <ConversationBar
            value={engagement}
            onChangeEngagement={handleEngagementChange}
            history={history}
            currentSessionId={sessionId}
            onSelectConversation={handleSelectHistory}
            onNewConversation={handleNewConversation}
            disabled={loading}
          />
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-6">
          {result && (
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Conversation title
                </p>
                {(() => {
                  const turnCount = history.filter((h) => h.session_id === sessionId).length;
                  if (turnCount < 2) return null;
                  return (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="flex items-center gap-1 rounded-full bg-accent/15 px-1.5 py-0.5 text-[9px] font-semibold text-accent">
                          <MessageCircleQuestion className="size-2.5" />
                          {turnCount}-turn thread
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        This answer continues an existing conversation - your follow-up below stays in the
                        same thread. Start &ldquo;New question&rdquo; in the sidebar to begin a separate one.
                      </TooltipContent>
                    </Tooltip>
                  );
                })()}
              </div>
              {editingLabel ? (
                <Input
                  autoFocus
                  defaultValue={sessionLabels[sessionId] ?? result.askedQuestion.slice(0, 80)}
                  onBlur={(e) => saveSessionLabel(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.currentTarget.blur();
                    if (e.key === "Escape") setEditingLabel(false);
                  }}
                  className="h-7 max-w-sm text-sm font-semibold"
                />
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      onClick={() => setEditingLabel(true)}
                      className="flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-sm font-semibold text-foreground hover:bg-muted"
                    >
                      {sessionLabels[sessionId] ?? result.askedQuestion.slice(0, 80)}
                      <Pencil className="size-3 opacity-60" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>
                    Click to rename this conversation thread - defaults to your first question. This is just a
                    label for finding it again in the history panel; it&apos;s separate from the engagement
                    selected above, which is what billing is attributed to.
                  </TooltipContent>
                </Tooltip>
              )}
            </div>
          )}

          {trace?.firm && (trace.firm.profile_summary || trace.firm.profile_applied || trace.firm.voice_applied) && (
            <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-accent/10 px-2.5 py-1 text-xs text-accent">
              <CheckCircle2 className="size-3" />
              {trace.firm.profile_summary
                ? `Written in your firm's voice · ${trace.firm.profile_summary}`
                : "Written in your firm's voice"}
            </span>
          )}

          {!result && !loading && history.length === 0 && (
            <p className="text-sm text-muted-foreground">Ask a question below to get started.</p>
          )}

          {loading && streamedAnswer && !result && (
            <p className="whitespace-pre-wrap text-sm">{streamedAnswer}</p>
          )}

          {clarifyQuestions && !result && (
            <ClarifyCard
              questions={clarifyQuestions}
              disabled={loading}
              onSubmit={(answers) =>
                handleSubmit({
                  questionOverride: clarifyAskedQuestion,
                  clarifications: answers,
                })
              }
              onSkip={() =>
                handleSubmit({
                  questionOverride: clarifyAskedQuestion,
                  // An empty clarifications array marks a deliberate skip so the
                  // backend answers directly (skips the clarify gate).
                  clarifications: [],
                })
              }
            />
          )}

          {result && (
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-3">
                {result.askedQuestion && (
                  <p className="text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">You asked: </span>
                    {result.askedQuestion}
                  </p>
                )}
              </div>

              {result.query_id &&
                (() => {
                  const status = history.find((h) => h.id === result.query_id)?.re_research_status;
                  return status ? <ReResearchBadge status={status} /> : null;
                })()}

              {streamComplete && result.query_id && (
                // The one place all response metadata lives - trust status,
                // source count (opens the Sources panel), and the annotation
                // hint - instead of scattered around the answer. Lives here,
                // not inside AnnotatableMarkdown, since a fresh instance
                // mounts per answer (key={result.query_id}) and would
                // otherwise repeat every piece of this after every question.
                <AnswerInfoBar
                  verifying={verifying}
                  verification={verification}
                  sourceCount={new Set(displayedCitations.map((c) => c.citation)).size}
                  onOpenSources={() => setSourcesOpen(true)}
                  onFocusFlag={(severity) => annotatableRef.current?.focusNextFlag(severity)}
                />
              )}

              <AnswerBody
                annotatableRef={annotatableRef}
                queryId={result.query_id}
                answer={result.answer}
                citations={result.citations}
                verificationIssues={verification?.issues}
                streamComplete={streamComplete}
              />

              {trace && (
                <AnswerTracePanel
                  trace={trace}
                  onPromote={handlePromote}
                  promoteState={promoteState}
                />
              )}

              <FirmKnowledgeSuggestion
                repeatCount={repeatCount}
                defaultTitle={result.askedQuestion.slice(0, 80) || "Saved answer"}
                content={result.answer}
              />

              <FollowUpChips
                questions={followUps}
                disabled={loading}
                onPick={(q) => {
                  setQuestion(q);
                  handleSubmit({ questionOverride: q });
                }}
              />

              <AnswerActionsBar
                key={result.query_id}
                queryId={result.query_id}
                onReResearchEnqueued={loadHistory}
                copied={copied}
                onCopy={handleCopy}
                savedDocId={savedDocId}
                savingDoc={savingDoc}
                docType={docType}
                onDocTypeChange={setDocType}
                templates={templates}
                onSave={handleSaveAsDocument}
                clientRef={clientRef}
                onEditAnswer={openEditAnswer}
              />
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        {/* Ask TaxFlow input - part of the middle column, below the answer,
            so a follow-up is always right where the conversation is. Client
            & engagement are chosen once, at the top of the column - not
            repeated here. */}
        <div className="shrink-0 border-t border-border p-4">
          <Textarea
            data-tour="question-textarea"
            value={question}
            onChange={(e) => setQuestion(e.target.value.slice(0, MAX_CHARS))}
            rows={3}
            placeholder={result ? "Ask a follow-up question..." : "Ask an Australian tax question..."}
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {question.length}/{MAX_CHARS} characters
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={() => handleSubmit()}
                  disabled={loading || !question.trim() || (!engagement && !result)}
                >
                  {loading ? "Thinking..." : "Ask TaxFlow"}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {!engagement && !result
                  ? "Select a client & engagement above to start"
                  : result
                    ? "Continues this engagement with your follow-up"
                    : "Runs your question against the AU tax knowledge base"}
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>

      {sourcesOpen ? (
        <SourcesPanel citations={displayedCitations} onHide={() => setSourcesOpen(false)} />
      ) : (
        <CollapsedPanelRail
          side="right"
          label="Show sources"
          icon={FileText}
          onShow={() => setSourcesOpen(true)}
        />
      )}

      <ConfirmDialog
        open={!!deleteQueryTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteQueryTarget(null);
        }}
        title="Delete question?"
        description={
          deleteQueryTarget
            ? `"${deleteQueryTarget.question.slice(0, 100)}" will be removed from your history. This cannot be undone.`
            : undefined
        }
        confirmLabel="Delete"
        destructive
        pending={mutation.pending}
        onConfirm={async () => {
          if (!deleteQueryTarget) return;
          const deletedId = deleteQueryTarget.id;
          const ok = await mutation.remove(`/api/query/${deletedId}`, "Question deleted");
          if (ok) {
            setDeleteQueryTarget(null);
            if (result?.query_id === deletedId) resetPane();
          }
        }}
      />

      <ConfirmDialog
        open={!!deleteSessionTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteSessionTarget(null);
        }}
        title="Delete conversation?"
        description="Every question in this conversation thread will be removed from your history. This cannot be undone."
        confirmLabel="Delete conversation"
        destructive
        pending={mutation.pending}
        onConfirm={async () => {
          if (!deleteSessionTarget) return;
          const deletedSession = deleteSessionTarget;
          const ok = await mutation.remove(
            `/api/query/sessions/${deletedSession}`,
            "Conversation deleted"
          );
          if (ok) {
            setDeleteSessionTarget(null);
            if (sessionId === deletedSession) resetPane();
          }
        }}
      />

      <Sheet
        open={editingAnswer}
        onOpenChange={(open) => {
          if (!open) setEditingAnswer(false);
        }}
      >
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Edit answer</SheetTitle>
          </SheetHeader>
          <p className="shrink-0 text-xs text-muted-foreground">
            Saving replaces the stored answer with your edited text and clears the automated
            verification status, since it no longer describes your wording. This does not re-run
            research.
          </p>
          <Textarea
            value={answerDraft}
            onChange={(e) => setAnswerDraft(e.target.value)}
            className="min-h-0 flex-1 resize-none font-mono text-xs"
          />
          <SheetFooter>
            <Button
              variant="outline"
              onClick={() => setEditingAnswer(false)}
              disabled={savingAnswer}
            >
              Cancel
            </Button>
            <Button onClick={saveAnswerEdit} disabled={savingAnswer || !answerDraft.trim()}>
              {savingAnswer ? "Saving..." : "Save"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}
