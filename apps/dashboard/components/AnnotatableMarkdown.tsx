"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { MessageSquare, Check, Reply, Pencil, Trash2, HelpCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Annotorious, useAnnotator, useSelection } from "@annotorious/react";
import { TextAnnotator } from "@recogito/react-text-annotator";
import type { TextAnnotation, RecogitoTextAnnotator, HighlightStyle } from "@recogito/react-text-annotator";
import { MarkdownDocument } from "@/components/MarkdownDocument";
import type { SourceCitation } from "@/components/SourcesPanel";
import { cn } from "@/lib/utils";
import { sourceHash, stripMarkdownEmphasis } from "@/lib/annotations/tokenizer";

export type TargetType = "query_answer" | "document";
export type AuthorKind = "reviewer" | "user";

// A verification-pass finding, anchored inline the same way a user comment is
// (both are placed by exact character offset into the rendered container,
// resolved once on mount/update - see `useFlaggedClaimOffsets` below).
// Structurally compatible with query/page.tsx's own `VerificationIssue` - kept
// as a local shape so this component doesn't import a page-level type.
export interface VerificationFlag {
  claim: string;
  issue: string;
  severity: "critical" | "warning" | "note";
  source_says?: string;
  suggested_correction?: string;
}

export interface Annotation {
  id: string;
  client_id: string;
  target_type: TargetType;
  target_id: string;
  target_version: string;
  block_index: number;
  start_offset: number;
  end_offset: number;
  quoted_text: string;
  author_kind: AuthorKind;
  author_name: string | null;
  body: string;
  parent_id: string | null;
  resolved_at: string | null;
  created_at: string;
}

// A resolved thread: a root annotation plus its replies.
interface Thread {
  root: Annotation;
  replies: Annotation[];
  stale: boolean; // source hash differs from what this annotation was anchored to
}

interface AnchorOffsets {
  startOffset: number;
  endOffset: number;
  quotedText: string;
}

interface PendingSelection {
  anchor: AnchorOffsets;
  version: string;
}

const RECOGITO_CONTAINER_CLASS = "annotatable-recogito-container";

function initials(name: string | null): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "");
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days > 0) return `${days}d`;
  const hours = Math.floor(diff / 3_600_000);
  if (hours > 0) return `${hours}h`;
  return "just now";
}

/**
 * Reusable annotation layer over rendered markdown, keyed by `targetType`.
 * Renders the source through the shared MarkdownDocument inside a Recogito
 * TextAnnotator, which owns selection-capture and highlight placement
 * directly against the rendered DOM (offsets are computed against the actual
 * container text, so there's no markdown-source-vs-rendered-text mismatch to
 * reconcile). This component keeps its own thread state (reply/edit/resolve
 * CRUD against /api/annotations) and only feeds Recogito the flat list of
 * spans to highlight + a style callback.
 */
export function AnnotatableMarkdown({
  targetType,
  targetId,
  sourceMarkdown,
  citations,
  authorName,
  verificationIssues,
}: {
  targetType: TargetType;
  targetId: string;
  sourceMarkdown: string;
  citations?: SourceCitation[];
  authorName?: string | null;
  verificationIssues?: VerificationFlag[];
}) {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [serverHash, setServerHash] = useState<string | null>(null);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);

  // composer (create) state
  const [pending, setPending] = useState<PendingSelection | null>(null);
  const [composerKind, setComposerKind] = useState<AuthorKind>("user");
  const [composerBody, setComposerBody] = useState("");
  const [saving, setSaving] = useState(false);

  // reply / edit inline state
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const [replyBody, setReplyBody] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");

  // Which flagged claim's detail is open (click on an inline verify-mark).
  const [activeVerifyIssue, setActiveVerifyIssue] = useState<VerificationFlag | null>(null);

  const isEmpty = sourceMarkdown.trim().length === 0;

  const loadAnnotations = useCallback(async () => {
    try {
      const params = new URLSearchParams({ target_type: targetType, target_id: targetId });
      const res = await fetch(`/api/annotations?${params.toString()}`);
      if (!res.ok) throw new Error("load failed");
      const data: { annotations: Annotation[]; source_hash: string } = await res.json();
      setAnnotations(data.annotations);
      setServerHash(data.source_hash);
    } catch {
      toast.error("Could not load comments");
    }
  }, [targetType, targetId]);

  useEffect(() => {
    // loadAnnotations is async — setState runs only after the fetch resolves,
    // not synchronously in the effect body.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadAnnotations();
  }, [loadAnnotations]);

  // Group annotations into threads. A root whose stored version doesn't match
  // the current source hash is flagged stale — its offsets may no longer line
  // up with the (changed) rendered text, so Recogito simply won't find a DOM
  // range for it and the highlight silently doesn't render; the thread still
  // shows in the gutter with a "source changed" note rather than being lost.
  const threads = useMemo<Thread[]>(() => {
    const roots = annotations.filter((a) => !a.parent_id);
    const repliesByParent = new Map<string, Annotation[]>();
    for (const a of annotations) {
      if (a.parent_id) {
        const list = repliesByParent.get(a.parent_id) ?? [];
        list.push(a);
        repliesByParent.set(a.parent_id, list);
      }
    }
    return roots.map((root) => ({
      root,
      replies: (repliesByParent.get(root.id) ?? []).sort(
        (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      ),
      stale: serverHash != null && root.target_version !== serverHash,
    }));
  }, [annotations, serverHash]);

  const visibleThreads = threads.filter((t) =>
    showResolved ? t.root.resolved_at != null : t.root.resolved_at == null
  );
  const openCount = threads.filter((t) => t.root.resolved_at == null).length;
  const resolvedCount = threads.length - openCount;

  // --- CRUD ------------------------------------------------------------------
  async function createAnnotation() {
    if (!pending || !composerBody.trim() || saving) return;
    setSaving(true);
    try {
      const res = await fetch("/api/annotations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_type: targetType,
          target_id: targetId,
          target_version: pending.version,
          block_index: 0,
          start_offset: pending.anchor.startOffset,
          end_offset: pending.anchor.endOffset,
          quoted_text: pending.anchor.quotedText,
          author_kind: composerKind,
          author_name: authorName ?? null,
          body: composerBody.trim(),
        }),
      });
      if (!res.ok) throw new Error("save failed");
      setPending(null);
      setComposerBody("");
      toast.success(composerKind === "user" ? "Question added" : "Comment added");
      await loadAnnotations();
    } catch {
      toast.error("Could not save your comment");
    } finally {
      setSaving(false);
    }
  }

  async function submitReply(thread: Thread) {
    if (!replyBody.trim()) return;
    try {
      const res = await fetch("/api/annotations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_type: targetType,
          target_id: targetId,
          target_version: thread.root.target_version,
          block_index: 0,
          start_offset: thread.root.start_offset,
          end_offset: thread.root.end_offset,
          quoted_text: thread.root.quoted_text,
          author_kind: composerKind,
          author_name: authorName ?? null,
          body: replyBody.trim(),
          parent_id: thread.root.id,
        }),
      });
      if (!res.ok) throw new Error("reply failed");
      setReplyingTo(null);
      setReplyBody("");
      await loadAnnotations();
    } catch {
      toast.error("Could not post your reply");
    }
  }

  async function patchAnnotation(id: string, fields: { body?: string; resolved?: boolean }) {
    try {
      const res = await fetch(`/api/annotations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (!res.ok) throw new Error("update failed");
      await loadAnnotations();
    } catch {
      toast.error("Could not update this comment");
    }
  }

  async function deleteAnnotation(id: string) {
    try {
      const res = await fetch(`/api/annotations/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("delete failed");
      toast.success("Comment deleted");
      await loadAnnotations();
    } catch {
      toast.error("Could not delete this comment");
    }
  }

  function handleNewSelection(anchor: AnchorOffsets) {
    void sourceHash(sourceMarkdown).then((version) => {
      setPending({ anchor, version });
      setComposerKind("user");
      setComposerBody("");
    });
  }

  return (
    <div className="flex gap-4">
      <div className="min-w-0 flex-1" data-testid="annotatable-article">
        {!isEmpty && threads.length === 0 && (
          <p className="mb-3 flex items-center gap-1.5 text-xs text-muted-foreground">
            <MessageSquare className="size-3.5" />
            Select any text below to ask a question or leave a note on it
          </p>
        )}
        {isEmpty ? (
          <p className="text-sm text-muted-foreground">This document has no content to display.</p>
        ) : (
          <Annotorious>
            <RecogitoLayer
              sourceMarkdown={sourceMarkdown}
              citations={citations}
              threads={visibleThreads}
              verificationIssues={verificationIssues}
              activeThreadId={activeThreadId}
              onNewSelection={handleNewSelection}
              onClickThread={setActiveThreadId}
              onClickVerify={setActiveVerifyIssue}
            />
          </Annotorious>
        )}
      </div>

      {/* gutter thread panel - only takes up space once there's something to
          show; an always-visible "Comments 0, Open (0), Resolved (0)" column
          competed with the answer for no reason on every fresh question. */}
      {threads.length > 0 && (
      <aside className="hidden w-80 shrink-0 border-l border-border pl-4 lg:block" data-testid="annotation-gutter">
        <div className="mb-3 flex items-center gap-2">
          <MessageSquare className="size-4" />
          <span className="text-sm font-semibold">Comments</span>
          <span className="rounded-full bg-muted px-2 text-xs text-muted-foreground">{threads.length}</span>
          {resolvedCount > 0 && (
            <div className="ml-auto flex gap-1">
              <button
                type="button"
                onClick={() => setShowResolved(false)}
                className={cn(
                  "rounded-full border border-border px-2.5 py-0.5 text-xs",
                  !showResolved ? "bg-foreground text-background" : "text-muted-foreground"
                )}
              >
                Open ({openCount})
              </button>
              <button
                type="button"
                onClick={() => setShowResolved(true)}
                className={cn(
                  "rounded-full border border-border px-2.5 py-0.5 text-xs",
                  showResolved ? "bg-foreground text-background" : "text-muted-foreground"
                )}
              >
                Resolved ({resolvedCount})
              </button>
            </div>
          )}
        </div>

        {visibleThreads.length === 0 && (
          <p className="text-xs text-muted-foreground">
            {showResolved
              ? "No resolved comments."
              : "All comments resolved."}
          </p>
        )}

        <div className="flex flex-col gap-3">
          {visibleThreads.map((thread) => (
            <div
              key={thread.root.id}
              onClick={() => setActiveThreadId(thread.root.id)}
              className={cn(
                "rounded-xl p-3 shadow-[0_0_0_1px] shadow-border",
                activeThreadId === thread.root.id && "shadow-accent",
                thread.root.resolved_at != null && "opacity-75"
              )}
              data-testid="annotation-thread"
            >
              <div className="mb-2 flex items-center gap-2">
                <span
                  className={cn(
                    "flex size-5 items-center justify-center rounded-full text-[10px] font-semibold uppercase",
                    thread.root.author_kind === "user"
                      ? "bg-accent/15 text-accent"
                      : "bg-slate-400/20 text-slate-600"
                  )}
                >
                  {initials(thread.root.author_name)}
                </span>
                <span className="text-xs font-semibold">{thread.root.author_name ?? "Anonymous"}</span>
                <Badge variant="outline" className="text-[10px]">
                  {thread.root.author_kind === "user" ? "Question" : "Comment"}
                </Badge>
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {relativeTime(thread.root.created_at)}
                </span>
              </div>

              {thread.stale && (
                <div className="mb-2 flex items-center gap-1 text-[11px] text-amber-700">
                  <AlertTriangle className="size-3" />
                  Source changed — may no longer be highlighted inline
                </div>
              )}

              <div className="mb-2 border-l-2 border-border pl-2 text-[11px] text-muted-foreground">
                &ldquo;{thread.root.quoted_text}&rdquo;
              </div>

              {editingId === thread.root.id ? (
                <div className="mb-2 space-y-1.5">
                  <Textarea
                    value={editBody}
                    onChange={(e) => setEditBody(e.target.value)}
                    rows={3}
                    className="text-sm"
                  />
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      onClick={async () => {
                        await patchAnnotation(thread.root.id, { body: editBody.trim() });
                        setEditingId(null);
                      }}
                    >
                      Save
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="mb-2 text-sm leading-relaxed">{thread.root.body}</p>
              )}

              {thread.replies.map((reply) => (
                <div key={reply.id} className="mt-2 border-t border-border pt-2">
                  <div className="mb-1 flex items-center gap-2">
                    <span
                      className={cn(
                        "flex size-5 items-center justify-center rounded-full text-[10px] font-semibold uppercase",
                        reply.author_kind === "user" ? "bg-accent/15 text-accent" : "bg-slate-400/20 text-slate-600"
                      )}
                    >
                      {initials(reply.author_name)}
                    </span>
                    <span className="text-xs font-semibold">{reply.author_name ?? "Anonymous"}</span>
                    <span className="ml-auto text-[11px] text-muted-foreground">{relativeTime(reply.created_at)}</span>
                  </div>
                  <p className="text-sm leading-relaxed">{reply.body}</p>
                </div>
              ))}

              {replyingTo === thread.root.id ? (
                <div className="mt-2 flex gap-1.5">
                  <Input
                    value={replyBody}
                    onChange={(e) => setReplyBody(e.target.value)}
                    placeholder="Reply to this thread…"
                    className="h-8 text-xs"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void submitReply(thread);
                    }}
                  />
                  <Button size="sm" className="h-8" onClick={() => void submitReply(thread)}>
                    Send
                  </Button>
                </div>
              ) : (
                <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:text-foreground"
                    onClick={() => {
                      setReplyingTo(thread.root.id);
                      setReplyBody("");
                    }}
                  >
                    <Reply className="size-3" /> Reply
                  </button>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:text-foreground"
                    onClick={() => {
                      setEditingId(thread.root.id);
                      setEditBody(thread.root.body);
                    }}
                  >
                    <Pencil className="size-3" /> Edit
                  </button>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 text-green-700 hover:text-green-800"
                    onClick={() =>
                      void patchAnnotation(thread.root.id, {
                        resolved: thread.root.resolved_at == null,
                      })
                    }
                  >
                    <Check className="size-3" /> {thread.root.resolved_at == null ? "Resolve" : "Reopen"}
                  </button>
                  <button
                    type="button"
                    className="ml-auto inline-flex items-center gap-1 text-destructive hover:opacity-80"
                    onClick={() => void deleteAnnotation(thread.root.id)}
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </aside>
      )}

      {/* compose dialog — activated by a text selection */}
      <Dialog open={pending != null} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add {composerKind === "user" ? "question" : "comment"}</DialogTitle>
          </DialogHeader>
          {pending && (
            <div className="rounded-lg bg-accent/10 px-3 py-2 text-xs text-foreground">
              <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-accent">
                Selected text
              </span>
              &ldquo;{pending.anchor.quotedText}&rdquo;
            </div>
          )}
          <div className="inline-flex overflow-hidden rounded-lg border border-border">
            <button
              type="button"
              onClick={() => setComposerKind("user")}
              className={cn(
                "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium",
                composerKind === "user" ? "bg-accent/10 text-accent" : "text-muted-foreground"
              )}
            >
              <HelpCircle className="size-3.5" /> Question
            </button>
            <button
              type="button"
              onClick={() => setComposerKind("reviewer")}
              className={cn(
                "inline-flex items-center gap-1.5 border-l border-border px-3 py-1.5 text-xs font-medium",
                composerKind === "reviewer" ? "bg-accent/10 text-accent" : "text-muted-foreground"
              )}
            >
              <MessageSquare className="size-3.5" /> Comment
            </button>
          </div>
          <Textarea
            value={composerBody}
            onChange={(e) => setComposerBody(e.target.value)}
            rows={4}
            autoFocus
            placeholder={
              composerKind === "user"
                ? "Ask a question about this passage…"
                : "Add a reviewer comment…"
            }
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button onClick={() => void createAnnotation()} disabled={saving || !composerBody.trim()}>
              {saving ? "Saving…" : composerKind === "user" ? "Add question" : "Add comment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* verification-flag detail — opened by clicking an inline flagged claim */}
      <Dialog open={activeVerifyIssue != null} onOpenChange={(open) => !open && setActiveVerifyIssue(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle
                className={cn(
                  "size-4",
                  activeVerifyIssue?.severity === "critical" ? "text-destructive" : "text-amber-600"
                )}
              />
              {activeVerifyIssue?.severity === "critical"
                ? "Needs review before relying on this"
                : activeVerifyIssue?.severity === "warning"
                  ? "Worth a second look"
                  : "Note"}
            </DialogTitle>
          </DialogHeader>
          {activeVerifyIssue && (
            <div className="space-y-3 text-sm">
              <div className="rounded-lg bg-muted px-3 py-2">
                <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Flagged text
                </span>
                &ldquo;{activeVerifyIssue.claim}&rdquo;
              </div>
              <p className="text-foreground">{activeVerifyIssue.issue}</p>
              {activeVerifyIssue.source_says && (
                <div>
                  <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    What the source actually says
                  </span>
                  <p className="text-muted-foreground">{activeVerifyIssue.source_says}</p>
                </div>
              )}
              {activeVerifyIssue.suggested_correction && (
                <div>
                  <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Suggested correction
                  </span>
                  <p className="text-muted-foreground">{activeVerifyIssue.suggested_correction}</p>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setActiveVerifyIssue(null)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/**
 * Everything that needs the Annotorious context (useAnnotator/useSelection)
 * lives here, as a child of <Annotorious>. Renders the markdown inside a
 * Recogito TextAnnotator, feeds it the current thread + verification-flag
 * spans to highlight, and turns new drag-selections / highlight clicks into
 * callbacks the parent drives its own Dialog/gutter state from.
 */
function RecogitoLayer({
  sourceMarkdown,
  citations,
  threads,
  verificationIssues,
  activeThreadId,
  onNewSelection,
  onClickThread,
  onClickVerify,
}: {
  sourceMarkdown: string;
  citations?: SourceCitation[];
  threads: Thread[];
  verificationIssues?: VerificationFlag[];
  activeThreadId: string | null;
  onNewSelection: (anchor: AnchorOffsets) => void;
  onClickThread: (id: string) => void;
  onClickVerify: (issue: VerificationFlag) => void;
}) {
  const anno = useAnnotator<RecogitoTextAnnotator>();
  const { selected } = useSelection<TextAnnotation>();

  const threadByRootId = useMemo(() => {
    const map = new Map<string, Thread>();
    for (const thread of threads) map.set(thread.root.id, thread);
    return map;
  }, [threads]);

  // Each flagged claim needs a concrete (start, end) into the RENDERED
  // container text before Recogito can place it - VerifyAgent quotes come
  // from the raw markdown source (may still carry "**"/"`" syntax), so they're
  // stripped and located by a plain indexOf against the container's
  // textContent, which is exactly the same coordinate space Recogito's own
  // Range-based offsets use. A claim that isn't found (paraphrased beyond an
  // exact substring) simply isn't inline-marked; it's never dropped from the
  // underlying verification data, only from this presentation.
  const [verifyAnchors, setVerifyAnchors] = useState<{ issue: VerificationFlag; id: string; anchor: AnchorOffsets }[]>(
    []
  );
  useEffect(() => {
    if (!verificationIssues?.length) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setVerifyAnchors([]);
      return;
    }
    const container = document.querySelector<HTMLElement>(`.${RECOGITO_CONTAINER_CLASS}`);
    if (!container) return;
    const text = container.textContent ?? "";
    const found: { issue: VerificationFlag; id: string; anchor: AnchorOffsets }[] = [];
    verificationIssues.forEach((issue, i) => {
      const claim = stripMarkdownEmphasis(issue.claim).trim();
      if (!claim) return;
      const start = text.indexOf(claim);
      if (start === -1) return;
      found.push({
        issue,
        id: `verify:${i}`,
        anchor: { startOffset: start, endOffset: start + claim.length, quotedText: claim },
      });
    });
    setVerifyAnchors(found);
  }, [verificationIssues, sourceMarkdown]);

  const verifyIssueById = useMemo(() => {
    const map = new Map<string, VerificationFlag>();
    for (const v of verifyAnchors) map.set(v.id, v.issue);
    return map;
  }, [verifyAnchors]);

  // Push the current set of spans to highlight into Recogito. `replace: true`
  // so toggling Open/Resolved (which changes `threads`) actually removes
  // highlights that should no longer show, not just adds new ones.
  useEffect(() => {
    if (!anno) return;
    const threadAnnotations: TextAnnotation[] = threads.map((thread) => ({
      id: thread.root.id,
      bodies: [],
      target: {
        annotation: thread.root.id,
        selector: [
          {
            quote: thread.root.quoted_text,
            start: thread.root.start_offset,
            end: thread.root.end_offset,
          },
        ],
      },
    }));
    const verifyAnnotations: TextAnnotation[] = verifyAnchors.map(({ id, anchor }) => ({
      id,
      bodies: [],
      target: {
        annotation: id,
        selector: [{ quote: anchor.quotedText, start: anchor.startOffset, end: anchor.endOffset }],
      },
    }));
    anno.setAnnotations([...threadAnnotations, ...verifyAnnotations], true);
  }, [anno, threads, verifyAnchors]);

  // A selection resolves to one of three things: a click on an already-known
  // thread highlight (open its gutter card), a click on a verify-flag
  // highlight (open its detail dialog), or a brand-new drag-selection with no
  // matching id yet (hand its offsets to the parent to drive the compose
  // dialog). Either way we immediately cancel Recogito's own "selected" state
  // since the backend list (via the effect above) is the single source of
  // truth for what's actually persisted and highlighted.
  useEffect(() => {
    if (!anno || selected.length === 0) return;
    for (const { annotation } of selected) {
      if (threadByRootId.has(annotation.id)) {
        onClickThread(annotation.id);
      } else if (verifyIssueById.has(annotation.id)) {
        const issue = verifyIssueById.get(annotation.id);
        if (issue) onClickVerify(issue);
      } else {
        const sel = annotation.target?.selector?.[0];
        const quote = sel?.quote?.trim();
        if (sel && quote) {
          onNewSelection({ startOffset: sel.start, endOffset: sel.end, quotedText: quote });
        }
      }
    }
    anno.cancelSelected();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const style = useCallback(
    (annotation: TextAnnotation): HighlightStyle | undefined => {
      const id = annotation.id;
      if (verifyIssueById.has(id)) {
        const issue = verifyIssueById.get(id)!;
        const color =
          issue.severity === "critical" ? "#dc2626" : issue.severity === "warning" ? "#d97706" : "#94a3b8";
        return { fillOpacity: 0, underlineColor: color, underlineThickness: 2, underlineOffset: 2 };
      }
      const thread = threadByRootId.get(id);
      if (thread) {
        const resolved = thread.root.resolved_at != null;
        const active = id === activeThreadId;
        const color = resolved ? "#94a3b8" : thread.root.author_kind === "user" ? "#ea580c" : "#64748b";
        return {
          fill: color,
          fillOpacity: resolved ? 0.12 : active ? 0.22 : 0.14,
          underlineColor: color,
          underlineThickness: active ? 3 : 2,
          underlineOffset: 2,
        };
      }
      return undefined;
    },
    [threadByRootId, verifyIssueById, activeThreadId]
  );

  return (
    <TextAnnotator className={RECOGITO_CONTAINER_CLASS} style={style}>
      <MarkdownDocument text={sourceMarkdown} citations={citations} />
    </TextAnnotator>
  );
}
