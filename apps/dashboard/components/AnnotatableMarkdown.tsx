"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { MarkdownDocument } from "@/components/MarkdownDocument";
import type { SourceCitation } from "@/components/SourcesPanel";
import { cn } from "@/lib/utils";
import {
  splitBlocks,
  resolveOffsetsInBlock,
  reanchor,
  sourceHash,
  occurrenceBeforeOffset,
  type AnchorOffsets,
} from "@/lib/annotations/tokenizer";

export type TargetType = "query_answer" | "document";
export type AuthorKind = "reviewer" | "user";

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

// A resolved thread: a root annotation, its replies, and the re-anchor status.
interface Thread {
  root: Annotation;
  replies: Annotation[];
  anchor: AnchorOffsets | null; // null => detached (fuzzy match failed)
  stale: boolean; // source hash differs from what this annotation was anchored to
}

interface PendingSelection {
  anchor: AnchorOffsets;
  version: string;
}

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
 * Renders the source through the shared MarkdownDocument, decorates anchored
 * spans with inline <mark> highlights, and shows a gutter thread panel with
 * reply/edit/resolve/delete. Anchoring is computed ONLY against the finalized
 * `sourceMarkdown` passed in (never mid-stream) via the pure tokenizer module.
 */
export function AnnotatableMarkdown({
  targetType,
  targetId,
  sourceMarkdown,
  citations,
  authorName,
}: {
  targetType: TargetType;
  targetId: string;
  sourceMarkdown: string;
  citations?: SourceCitation[];
  authorName?: string | null;
}) {
  const articleRef = useRef<HTMLDivElement>(null);
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

  const blocks = useMemo(() => splitBlocks(sourceMarkdown), [sourceMarkdown]);
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

  // Group annotations into threads and resolve each root's anchor. If a root's
  // stored version matches the current source hash, use its offsets directly;
  // otherwise mark it stale and fuzzy re-anchor via quoted_text. On a miss the
  // thread is kept but detached (anchor: null) so a comment is never dropped.
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
    return roots.map((root) => {
      const stale = serverHash != null && root.target_version !== serverHash;
      let anchor: AnchorOffsets | null;
      const block = blocks[root.block_index];
      if (!stale && block) {
        // trust stored offsets, but keep the quoted_text for the highlighter
        anchor = {
          blockIndex: root.block_index,
          startOffset: root.start_offset,
          endOffset: root.end_offset,
          quotedText: root.quoted_text,
        };
      } else {
        anchor = reanchor(blocks, root.quoted_text, root.block_index);
      }
      return {
        root,
        replies: (repliesByParent.get(root.id) ?? []).sort(
          (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        ),
        anchor,
        stale,
      };
    });
  }, [annotations, blocks, serverHash]);

  const visibleThreads = threads.filter((t) =>
    showResolved ? t.root.resolved_at != null : t.root.resolved_at == null
  );
  const openCount = threads.filter((t) => t.root.resolved_at == null).length;
  const resolvedCount = threads.length - openCount;

  // --- selection -> offsets --------------------------------------------------
  // On mouseup inside the article, map the actual DOM selection back to
  // (block_index, start/end offset) in the SOURCE markdown. We locate the
  // rendered [data-block-index] wrapper the selection STARTS in (not a top-down
  // scan for the selected string), so selecting the 2nd of two identical spans
  // anchors the 2nd. When the selection crosses block wrappers we clamp to the
  // first block per the plan: offsets cover the first block's selected
  // substring, quoted_text keeps the full selection for fuzzy fallback. Offsets
  // are computed against the source, before citation linkification, so
  // highlighting and citation links compose.
  const handleMouseUp = useCallback(() => {
    if (isEmpty) return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) return;
    const fullSelected = selection.toString();
    if (!fullSelected.trim()) return;
    const range = selection.getRangeAt(0);
    const article = articleRef.current;
    if (!article || !article.contains(range.startContainer)) return;

    const startBlockEl = closestBlockEl(range.startContainer);
    const endBlockEl = closestBlockEl(range.endContainer);
    if (!startBlockEl) return;
    const firstBlockIndex = Number(startBlockEl.getAttribute("data-block-index"));
    const block = blocks[firstBlockIndex];
    if (!block) return;

    const crossesBlocks = endBlockEl !== startBlockEl;
    // Text actually selected within the first block: the whole selection for a
    // single-block drag, or (selection start → end of first block) when it
    // crosses into later blocks.
    let selectedInBlock = fullSelected;
    if (crossesBlocks) {
      const r = document.createRange();
      r.setStart(range.startContainer, range.startOffset);
      r.setEnd(startBlockEl, startBlockEl.childNodes.length);
      selectedInBlock = r.toString();
    }
    if (!selectedInBlock.trim()) return;

    // Which occurrence of the selected text within this block did the user pick?
    // Count non-overlapping matches in the rendered text before the selection
    // start so repeated spans disambiguate by position.
    const prefixRange = document.createRange();
    prefixRange.setStart(startBlockEl, 0);
    prefixRange.setEnd(range.startContainer, range.startOffset);
    const occurrence = countOccurrences(prefixRange.toString(), selectedInBlock.trim());

    const anchor = resolveOffsetsInBlock(block, selectedInBlock, occurrence);
    if (!anchor) {
      toast.error("Couldn't anchor that selection — try selecting within a single paragraph");
      return;
    }
    // Preserve the full multi-block selection as the quoted text for fuzzy
    // fallback + gutter display, while offsets stay clamped to the first block.
    if (crossesBlocks) {
      const full = fullSelected.trim();
      if (full) anchor.quotedText = full;
    }
    void sourceHash(sourceMarkdown).then((version) => {
      setPending({ anchor, version });
      setComposerKind("user");
      setComposerBody("");
    });
  }, [blocks, isEmpty, sourceMarkdown]);

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
          block_index: pending.anchor.blockIndex,
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
          block_index: thread.root.block_index,
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

  // --- inline highlight decoration -------------------------------------------
  // After render, wrap each anchored thread's quoted_text in <mark>s inside the
  // article DOM. The search is scoped to the thread's resolved SOURCE block
  // (rendered in its own [data-block-index] wrapper) and to the specific
  // occurrence of the quoted text within that block, so repeated text (e.g.
  // "$120,000" appearing twice) highlights the span the comment actually
  // anchored to rather than the first match in the whole article. Clicking a
  // mark activates its gutter thread.
  useEffect(() => {
    const root = articleRef.current;
    if (!root) return;
    // Clear previous highlights (unwrap our marks).
    root.querySelectorAll("mark[data-annotation]").forEach((el) => {
      const parent = el.parentNode;
      if (!parent) return;
      while (el.firstChild) parent.insertBefore(el.firstChild, el);
      parent.removeChild(el);
      parent.normalize();
    });

    for (const thread of visibleThreads) {
      if (!thread.anchor) continue;
      const quoted = thread.anchor.quotedText.trim();
      if (!quoted) continue;
      const blockEl = root.querySelector<HTMLElement>(
        `[data-block-index="${thread.anchor.blockIndex}"]`
      );
      if (!blockEl) continue;
      // Which occurrence of the quoted text within this block did the anchor
      // point at? Derive it from the stored source offset so the same span is
      // re-highlighted after reload.
      const srcBlock = blocks[thread.anchor.blockIndex];
      const occurrence = srcBlock
        ? occurrenceBeforeOffset(srcBlock.text, thread.anchor.startOffset, quoted)
        : 0;
      const kindClass =
        thread.root.resolved_at != null
          ? "bg-slate-200/60 text-muted-foreground"
          : thread.root.author_kind === "user"
            ? "bg-accent/15 shadow-[inset_0_-2px_0_theme(colors.accent.DEFAULT)]"
            : "bg-slate-400/20 shadow-[inset_0_-2px_0_theme(colors.slate.500)]";
      markOccurrenceInBlock(blockEl, quoted, occurrence, () => {
        const mark = document.createElement("mark");
        mark.dataset.annotation = thread.root.id;
        mark.className = cn(
          "cursor-pointer rounded-sm",
          kindClass,
          activeThreadId === thread.root.id && "ring-2 ring-accent"
        );
        mark.addEventListener("click", () => setActiveThreadId(thread.root.id));
        return mark;
      });
    }
  }, [visibleThreads, blocks, sourceMarkdown, activeThreadId]);

  return (
    <div className="flex gap-4">
      <div
        ref={articleRef}
        onMouseUp={handleMouseUp}
        className="min-w-0 flex-1"
        data-testid="annotatable-article"
      >
        {isEmpty ? (
          <p className="text-sm text-muted-foreground">This document has no content to display.</p>
        ) : (
          // Render each source block in its own wrapper tagged with the block's
          // index. This makes the DOM source-block-aware: selection→offset
          // mapping and highlight rendering resolve WITHIN the intended block
          // (and occurrence) instead of scanning the whole article for a quoted
          // string, so repeated text (e.g. "$120,000" twice) anchors correctly.
          blocks.map((block) => (
            <div key={block.index} data-block-index={block.index}>
              <MarkdownDocument text={block.text} citations={citations} />
            </div>
          ))
        )}
      </div>

      {/* gutter thread panel */}
      <aside className="hidden w-80 shrink-0 border-l border-border pl-4 lg:block" data-testid="annotation-gutter">
        <div className="mb-3 flex items-center gap-2">
          <MessageSquare className="size-4" />
          <span className="text-sm font-semibold">Comments</span>
          <span className="rounded-full bg-muted px-2 text-xs text-muted-foreground">{threads.length}</span>
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
        </div>

        {visibleThreads.length === 0 && (
          <p className="text-xs text-muted-foreground">
            {showResolved
              ? "No resolved comments."
              : "No comments yet. Select text in the document to add one."}
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
                  {thread.anchor ? "Source changed — re-anchored" : "Source changed — detached"}
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
    </div>
  );
}

/**
 * Walk up from a DOM node to the nearest ancestor tagged with a source
 * `data-block-index` (the per-block wrapper we render). Returns null if the
 * node is outside any block wrapper.
 */
function closestBlockEl(node: Node): HTMLElement | null {
  let el: Node | null = node.nodeType === Node.TEXT_NODE ? node.parentNode : node;
  while (el && el instanceof HTMLElement) {
    if (el.hasAttribute("data-block-index")) return el;
    el = el.parentNode;
  }
  return null;
}

/**
 * Count non-overlapping occurrences of `needle` in `haystack`. Used to derive
 * which occurrence of a repeated span the user selected, from the rendered text
 * preceding the selection start.
 */
function countOccurrences(haystack: string, needle: string): number {
  if (!needle) return 0;
  let count = 0;
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(needle, from);
    if (at === -1) return count;
    count += 1;
    from = at + needle.length;
  }
}

/**
 * Wrap the `occurrence`-th (0-based) instance of `needle` within a single text
 * node under `blockEl` using a freshly built <mark> (from `makeMark`). Occurrence
 * counting spans all text nodes in the block so a repeated span highlights the
 * intended one. Multi-node matches are skipped (the gutter still shows the
 * thread); this mirrors the prior single-text-node constraint but scoped to the
 * source block + occurrence rather than the whole article.
 */
function markOccurrenceInBlock(
  blockEl: HTMLElement,
  needle: string,
  occurrence: number,
  makeMark: () => HTMLElement
): void {
  const walker = document.createTreeWalker(blockEl, NodeFilter.SHOW_TEXT);
  let seen = 0;
  let node: Node | null;
  let firstNode: Node | null = null;
  let firstIdx = -1;
  while ((node = walker.nextNode())) {
    const text = node.textContent ?? "";
    let from = 0;
    for (;;) {
      const idx = text.indexOf(needle, from);
      if (idx === -1) break;
      if (firstNode === null) {
        firstNode = node;
        firstIdx = idx;
      }
      if (seen === occurrence) {
        wrapRange(node, idx, needle.length, makeMark);
        return;
      }
      seen += 1;
      from = idx + needle.length;
    }
  }
  // Requested occurrence not found (e.g. rendered text differs from source):
  // fall back to the first match so the highlight still appears.
  if (firstNode) wrapRange(firstNode, firstIdx, needle.length, makeMark);
}

function wrapRange(node: Node, start: number, length: number, makeMark: () => HTMLElement): void {
  try {
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, start + length);
    range.surroundContents(makeMark());
  } catch {
    // surroundContents throws if the range partially crosses elements; skip.
  }
}


