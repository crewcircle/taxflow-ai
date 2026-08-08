"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { MessageSquare, Check, Reply, Pencil, Trash2, HelpCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Annotorious, useAnnotator, useSelection } from "@annotorious/react";
import { TextAnnotator, TextAnnotationPopup } from "@recogito/react-text-annotator";
import type { TextAnnotation, RecogitoTextAnnotator, HighlightStyle } from "@recogito/react-text-annotator";
import { MarkdownDocument } from "@/components/MarkdownDocument";
import { MentionField, renderMentionBody } from "@/components/MentionField";
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

// Walks the container's text nodes to find the element holding the character
// at `offset` (same coordinate space as container.textContent, which is what
// the verify-anchor offsets are computed against) - used to scroll a flagged
// claim into view without depending on Recogito's internal highlight DOM.
function findElementAtTextOffset(container: HTMLElement, offset: number): HTMLElement | null {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let acc = 0;
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const len = node.textContent?.length ?? 0;
    if (acc + len > offset) return node.parentElement;
    acc += len;
  }
  return null;
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
// Imperative handle so a sibling outside the Annotorious tree (the query
// page's TrustRibbon) can drive "jump to the next flagged claim" without
// owning any of Recogito's internal state itself.
export interface AnnotatableMarkdownHandle {
  focusNextFlag: (severity?: "critical" | "warning" | "note") => void;
}

export const AnnotatableMarkdown = forwardRef<AnnotatableMarkdownHandle, {
  targetType: TargetType;
  targetId: string;
  sourceMarkdown: string;
  citations?: SourceCitation[];
  authorName?: string | null;
  verificationIssues?: VerificationFlag[];
  showHint?: boolean;
}>(function AnnotatableMarkdown({
  targetType,
  targetId,
  sourceMarkdown,
  citations,
  authorName,
  verificationIssues,
  // The "select text to comment" hint. Defaults on (the document viewer shows
  // one document at a time, so it's fine there) - the query page passes
  // false and renders its own persistent, non-repeating hint instead, since
  // a fresh AnnotatableMarkdown mounts per answer there and the hint would
  // otherwise reappear after every question.
  showHint = true,
}, ref) {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [serverHash, setServerHash] = useState<string | null>(null);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);

  // reply / edit inline state
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const [replyBody, setReplyBody] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");

  const isEmpty = sourceMarkdown.trim().length === 0;

  // Lifted out of RecogitoLayer (rather than computed there) so this
  // component - outside the Annotorious tree - can also drive "jump to the
  // next flagged claim" from the ribbon via the imperative handle below.
  // Each flagged claim needs a concrete (start, end) into the RENDERED
  // container text - VerifyAgent quotes come from the raw markdown source
  // (may still carry "**"/"`" syntax), so they're stripped and located by a
  // plain indexOf against the container's textContent, the same coordinate
  // space Recogito's own Range-based offsets use. A claim that isn't found
  // (paraphrased beyond an exact substring) simply isn't inline-marked; it's
  // never dropped from the underlying verification data, only from this
  // presentation.
  const [verifyAnchors, setVerifyAnchors] = useState<
    { issue: VerificationFlag; id: string; anchor: AnchorOffsets }[]
  >([]);
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
    // Reading order, so "next" cycles top-to-bottom through the answer.
    found.sort((a, b) => a.anchor.startOffset - b.anchor.startOffset);
    setVerifyAnchors(found);
  }, [verificationIssues, sourceMarkdown]);

  const flagCursorRef = useRef(0);
  // RecogitoLayer registers its `anno` instance here once mounted (it's the
  // only place `useAnnotator()` can be called, inside the Annotorious tree) -
  // lets focusNextFlag select the flagged annotation programmatically so the
  // SAME inline TextAnnotationPopup used for comments also shows the verify
  // detail, anchored right at the flagged text, instead of a separate dialog.
  const annoRef = useRef<RecogitoTextAnnotator | null>(null);

  useImperativeHandle(
    ref,
    () => ({
      focusNextFlag(severity) {
        const container = document.querySelector<HTMLElement>(`.${RECOGITO_CONTAINER_CLASS}`);
        if (!container) return;
        const candidates = severity ? verifyAnchors.filter((v) => v.issue.severity === severity) : verifyAnchors;
        if (candidates.length === 0) return;
        const target = candidates[flagCursorRef.current % candidates.length];
        flagCursorRef.current += 1;
        const el = findElementAtTextOffset(container, target.anchor.startOffset);
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        // Brief flash so "here it is" reads even after the smooth-scroll
        // already lands it in the middle of the viewport, underlined the
        // same as every other flagged claim.
        if (el) {
          el.classList.add("flag-flash");
          setTimeout(() => el.classList.remove("flag-flash"), 1200);
        }
        annoRef.current?.setSelected(target.id);
      },
    }),
    [verifyAnchors]
  );

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
  // Takes explicit args rather than reading composer state, since the compose
  // UI now lives in RecogitoLayer's inline selection popup (TextAnnotationPopup),
  // outside this component - only the actual persistence + refresh needs to
  // stay here alongside loadAnnotations.
  async function createAnnotation(anchor: AnchorOffsets, kind: AuthorKind, body: string): Promise<boolean> {
    try {
      const version = await sourceHash(sourceMarkdown);
      const res = await fetch("/api/annotations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_type: targetType,
          target_id: targetId,
          target_version: version,
          block_index: 0,
          start_offset: anchor.startOffset,
          end_offset: anchor.endOffset,
          quoted_text: anchor.quotedText,
          author_kind: kind,
          author_name: authorName ?? null,
          body: body.trim(),
        }),
      });
      if (!res.ok) throw new Error("save failed");
      toast.success(kind === "user" ? "Question added" : "Comment added");
      await loadAnnotations();
      return true;
    } catch {
      toast.error("Could not save your comment");
      return false;
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
          author_kind: thread.root.author_kind,
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

  return (
    <div className="flex gap-4">
      <div className="min-w-0 flex-1" data-testid="annotatable-article">
        {showHint && !isEmpty && threads.length === 0 && (
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
              verifyAnchors={verifyAnchors}
              activeThreadId={activeThreadId}
              onCreateAnnotation={createAnnotation}
              onClickThread={setActiveThreadId}
              onAnnotatorReady={(a) => {
                annoRef.current = a;
              }}
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
                <div className="mb-2 flex items-center gap-1 text-[11px] text-warning">
                  <AlertTriangle className="size-3" />
                  Source changed — may no longer be highlighted inline
                </div>
              )}

              <div className="mb-2 border-l-2 border-border pl-2 text-[11px] text-muted-foreground">
                &ldquo;{thread.root.quoted_text}&rdquo;
              </div>

              {editingId === thread.root.id ? (
                <div className="mb-2 space-y-1.5">
                  <MentionField
                    value={editBody}
                    onChange={setEditBody}
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
                <p className="mb-2 text-sm leading-relaxed">{renderMentionBody(thread.root.body)}</p>
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
                  <p className="text-sm leading-relaxed">{renderMentionBody(reply.body)}</p>
                </div>
              ))}

              {replyingTo === thread.root.id ? (
                <div className="mt-2 flex gap-1.5">
                  <MentionField
                    as="input"
                    value={replyBody}
                    onChange={setReplyBody}
                    placeholder="Reply to this thread… (type @ to tag someone)"
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
                    className="inline-flex items-center gap-1 text-success hover:opacity-80"
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

    </div>
  );
});

/**
 * Everything that needs the Annotorious context (useAnnotator/useSelection)
 * lives here, as a child of <Annotorious>. Renders the markdown inside a
 * Recogito TextAnnotator, feeds it the current thread + verification-flag
 * spans to highlight, turns highlight clicks into callbacks the parent drives
 * its own gutter/verify-detail state from, and shows the new-comment composer
 * as an inline popup anchored to the selection itself (TextAnnotationPopup,
 * shipped by @recogito/react-text-annotator - no dialog/modal involved, and
 * no extra dependency since it's already part of the installed package).
 */
function RecogitoLayer({
  sourceMarkdown,
  citations,
  threads,
  verifyAnchors,
  activeThreadId,
  onCreateAnnotation,
  onClickThread,
  onAnnotatorReady,
}: {
  sourceMarkdown: string;
  citations?: SourceCitation[];
  threads: Thread[];
  verifyAnchors: { issue: VerificationFlag; id: string; anchor: AnchorOffsets }[];
  activeThreadId: string | null;
  onCreateAnnotation: (anchor: AnchorOffsets, kind: AuthorKind, body: string) => Promise<boolean>;
  onClickThread: (id: string) => void;
  onAnnotatorReady: (anno: RecogitoTextAnnotator) => void;
}) {
  const anno = useAnnotator<RecogitoTextAnnotator>();
  const { selected } = useSelection<TextAnnotation>();

  useEffect(() => {
    if (anno) onAnnotatorReady(anno);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anno]);

  const threadByRootId = useMemo(() => {
    const map = new Map<string, Thread>();
    for (const thread of threads) map.set(thread.root.id, thread);
    return map;
  }, [threads]);

  const verifyIssueById = useMemo(() => {
    const map = new Map<string, VerificationFlag>();
    for (const v of verifyAnchors) map.set(v.id, v.issue);
    return map;
  }, [verifyAnchors]);

  // Recogito recalculates each highlight's on-screen position on window
  // resize (it listens for the event itself) and via its own ResizeObserver
  // on this container - but a layout shift caused by something OUTSIDE this
  // component (the Sources/History rail toggling open, a citation's source
  // Dialog opening and releasing the page's scrollbar on close) doesn't
  // always reach either of those, and once a highlight's cached position
  // goes stale it stays stale - clicking the underlined text again does
  // nothing, because Recogito already believes it knows where the highlight
  // is and there's no user-facing "refresh" action. A ResizeObserver on the
  // container's own parent (catches real width/height changes) plus a
  // MutationObserver on <body> (catches DOM changes that don't necessarily
  // resize this container, e.g. a Dialog's portal mounting) both nudge
  // Recogito down its own already-correct, already-tested recovery path by
  // dispatching a real `resize` event - the same thing an actual window
  // resize would do - rather than reaching into its internal recalculation
  // function directly.
  useEffect(() => {
    const container = document.querySelector<HTMLElement>(`.${RECOGITO_CONTAINER_CLASS}`);
    if (!container) return;
    let pending: ReturnType<typeof setTimeout> | null = null;
    const nudge = () => {
      if (pending) clearTimeout(pending);
      pending = setTimeout(() => window.dispatchEvent(new Event("resize")), 50);
    };
    const resizeObserver = new ResizeObserver(nudge);
    resizeObserver.observe(container.parentElement ?? container);
    const mutationObserver = new MutationObserver(nudge);
    mutationObserver.observe(document.body, { attributes: true, childList: true, subtree: true });
    return () => {
      if (pending) clearTimeout(pending);
      resizeObserver.disconnect();
      mutationObserver.disconnect();
    };
  }, []);

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

  // A click on an already-known THREAD highlight opens its gutter card and is
  // resolved instantly, so that one still auto-cancels the selection (the
  // gutter, not a popup, is the source of truth for thread detail/reply).
  // Verify-flag clicks and brand-new drag-selections are deliberately left
  // selected - both get an inline TextAnnotationPopup below (verify detail /
  // compose form respectively), which cancels the selection itself once the
  // user closes it.
  useEffect(() => {
    if (!anno || selected.length === 0) return;
    for (const { annotation } of selected) {
      if (threadByRootId.has(annotation.id)) {
        onClickThread(annotation.id);
        anno.cancelSelected();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  // Tracked in a ref (not read straight off `selected`) because onClose fires
  // from an effect inside the library itself, whose timing relative to our
  // own `selected` state updating isn't something to rely on - the ref always
  // holds whatever was selected most recently, synchronously.
  const lastSelectedIdRef = useRef<string | null>(null);
  useEffect(() => {
    lastSelectedIdRef.current = selected[0]?.annotation.id ?? null;
  }, [selected]);

  // Drag-selecting text to open the compose form creates a REAL annotation in
  // Recogito's local store immediately (that's what the popup is anchored
  // to) - it isn't a UI-only "pending" state. `anno.cancelSelected()` only
  // clears which annotation is selected (so the popup closes); it does NOT
  // remove that annotation from the store, so the highlight it drew was
  // staying behind forever - still visibly "selected" even after Cancel,
  // exactly as if nothing had been dismissed at all. The fix is to actually
  // delete it, but ONLY when it's a throwaway draft: a real comment/question
  // thread or a verify-flag annotation must never be deleted just because its
  // detail popup was closed, so both maps are checked before removing
  // anything. One shared function backs every dismissal path (the composer's
  // own Cancel button, the verify popup's Close button, and clicking/tabbing
  // away without pressing either) so they can't drift out of sync with each
  // other.
  const cancelCurrentSelection = useCallback(() => {
    const id = lastSelectedIdRef.current;
    if (id && !threadByRootId.has(id) && !verifyIssueById.has(id)) {
      anno?.removeAnnotation(id);
    }
    anno?.cancelSelected();
    // Recogito clears its own selection state above, but the native browser
    // text selection (blue highlight) that triggered this popup in the first
    // place can survive that - clear it too so cancelling actually reverts to
    // plain, unhighlighted text instead of leaving it looking selected.
    window.getSelection()?.removeAllRanges();
  }, [anno, threadByRootId, verifyIssueById]);

  // TextAnnotationPopup positions itself via a virtual floating-ui reference
  // element whose getBoundingClientRect() reads a value that
  // @recogito/react-text-annotator computes asynchronously (debounced ~250ms
  // inside a requestAnimationFrame) - floating-ui calls it SYNCHRONOUSLY on
  // the popup's first render, so the very first position it gets is whatever
  // that value held from BEFORE this selection (or an empty, zeroed rect the
  // first time any popup opens this session), landing the popup in the wrong
  // place - typically vertically centered in the container, overlapping the
  // underlined text it's meant to explain. Nothing in floating-ui's own
  // auto-update machinery re-checks a virtual reference on a timer, only on
  // an actual window scroll/resize, so once the library's internal value
  // finally settles to the correct rect, a synthetic resize event - the same
  // thing a real window resize would fire - is what makes floating-ui ask for
  // the position again and reposition correctly. Confirmed against 4.2.5 (the
  // current latest release) by reading its bundled source; not something
  // fixable from the props this component exposes.
  useEffect(() => {
    if (selected.length === 0) return;
    const t = setTimeout(() => window.dispatchEvent(new Event("resize")), 320);
    return () => clearTimeout(t);
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
      <TextAnnotationPopup
        // Dismissing any other way (click outside, escape, tab away) goes
        // through the same cleanup as the explicit Cancel/Close buttons -
        // see cancelCurrentSelection above for why a plain cancelSelected()
        // isn't enough on its own.
        onClose={cancelCurrentSelection}
        popup={({ annotation }) => {
          // A click on an existing thread highlight is already routed to the
          // gutter and cancelled by the effect above before this would ever
          // render for it.
          if (threadByRootId.has(annotation.id)) return null;
          const verifyIssue = verifyIssueById.get(annotation.id);
          if (verifyIssue) {
            return <VerifyDetailPopup issue={verifyIssue} onDone={cancelCurrentSelection} />;
          }
          const sel = annotation.target?.selector?.[0];
          const quote = sel?.quote?.trim();
          if (!sel || !quote) return null;
          return (
            <ComposerPopup
              anchor={{ startOffset: sel.start, endOffset: sel.end, quotedText: quote }}
              onCreateAnnotation={onCreateAnnotation}
              onDone={cancelCurrentSelection}
            />
          );
        }}
      />
    </TextAnnotator>
  );
}

// Inline detail for a flagged claim, positioned right at the underlined text
// by TextAnnotationPopup - replaces what used to be a centered Dialog.
// "What's wrong" merges the issue description and what the source actually
// says into one crisp line (they were two separate, often-overlapping
// paragraphs before) - the point a reader needs is "this claim doesn't match
// the source, here's why," not two takes on the same fact.
function VerifyDetailPopup({ issue, onDone }: { issue: VerificationFlag; onDone: () => void }) {
  const whatsWrong = issue.source_says ? `${issue.issue} Source says: ${issue.source_says}` : issue.issue;
  return (
    <div className="w-80 space-y-2.5 rounded-lg border border-border bg-popover p-3 text-sm text-popover-foreground shadow-xl">
      <div className="flex items-center gap-2">
        <AlertTriangle
          className={cn("size-4 shrink-0", issue.severity === "critical" ? "text-destructive" : "text-warning")}
        />
        <span className="text-xs font-semibold">
          {issue.severity === "critical"
            ? "Needs review before relying on this"
            : issue.severity === "warning"
              ? "Worth a second look"
              : "Note"}
        </span>
      </div>
      <p className="text-foreground">{whatsWrong}</p>
      {issue.suggested_correction && (
        <div>
          <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Suggested correction
          </span>
          <p className="text-muted-foreground">{issue.suggested_correction}</p>
        </div>
      )}
      <div className="flex justify-end">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Close
        </Button>
      </div>
    </div>
  );
}

// The inline "ask a question / leave a comment" form, positioned by
// TextAnnotationPopup right at the current selection - replaces what used to
// be a centered Dialog that hid the rest of the answer while composing.
function ComposerPopup({
  anchor,
  onCreateAnnotation,
  onDone,
}: {
  anchor: AnchorOffsets;
  onCreateAnnotation: (anchor: AnchorOffsets, kind: AuthorKind, body: string) => Promise<boolean>;
  onDone: () => void;
}) {
  const [kind, setKind] = useState<AuthorKind>("user");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!body.trim() || saving) return;
    setSaving(true);
    const ok = await onCreateAnnotation(anchor, kind, body);
    setSaving(false);
    if (ok) onDone();
  }

  return (
    // No repeat of the selected text here - it's already highlighted inline
    // (the blue/orange marker on the text itself), so quoting it back again
    // was redundant, not clarifying. Question/comment toggle, one field,
    // Cancel/Add - that's the whole form.
    <div className="w-80 space-y-2 rounded-lg border border-border bg-popover p-3 text-sm text-popover-foreground shadow-xl">
      <div className="inline-flex overflow-hidden rounded-lg border border-border">
        <button
          type="button"
          onClick={() => setKind("user")}
          className={cn(
            "inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium",
            kind === "user" ? "bg-accent/10 text-accent" : "text-muted-foreground"
          )}
        >
          <HelpCircle className="size-3.5" /> Question
        </button>
        <button
          type="button"
          onClick={() => setKind("reviewer")}
          className={cn(
            "inline-flex items-center gap-1.5 border-l border-border px-2.5 py-1 text-xs font-medium",
            kind === "reviewer" ? "bg-accent/10 text-accent" : "text-muted-foreground"
          )}
        >
          <MessageSquare className="size-3.5" /> Comment
        </button>
      </div>
      <MentionField
        value={body}
        onChange={setBody}
        rows={3}
        autoFocus
        className="text-sm"
        placeholder={
          kind === "user"
            ? "Ask a question about this passage… (type @ to tag someone)"
            : "Add a reviewer comment… (type @ to tag someone)"
        }
        onKeyDown={(e) => {
          if (e.key === "Escape") onDone();
        }}
      />
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone} disabled={saving}>
          Cancel
        </Button>
        <Button size="sm" onClick={() => void submit()} disabled={saving || !body.trim()}>
          {saving ? "Saving…" : kind === "user" ? "Add question" : "Add comment"}
        </Button>
      </div>
    </div>
  );
}
