/**
 * Annotation anchoring tokenizer — the SINGLE module boundary for markdown
 * block-splitting + character-offset tokenization used to anchor annotations.
 *
 * This is a pure, deterministic module with no React/DOM dependencies so it can
 * later slot cleanly into the intended post-MVP DocumentRender/Tokenizer port
 * (see the ports/adapters refactor doc) and be reused verbatim by Phase 3's
 * editor. Nothing here touches the network or the DOM — callers pass in a
 * source-markdown string and a selected substring and get back block/offset
 * coordinates. Keep all block/offset logic HERE, not scattered across UI code.
 *
 * Anchor unit = (blockIndex, startOffset, endOffset) character offsets into the
 * FINAL persisted source markdown, where "blocks" are the top-level markdown
 * blocks (split on blank lines) matching how the renderer chunks content, plus
 * the exact `quotedText` substring for fuzzy re-anchoring.
 */

export interface MarkdownBlock {
  /** 0-based index of this block among the top-level blocks. */
  index: number;
  /** Char offset in the source where this block's (trimmed) text starts. */
  start: number;
  /** Char offset in the source where this block's (trimmed) text ends (exclusive). */
  end: number;
  /** The block's source-markdown text (trimmed of surrounding blank lines). */
  text: string;
}

export interface AnchorOffsets {
  blockIndex: number;
  startOffset: number;
  endOffset: number;
  quotedText: string;
}

/**
 * Loose match: collapse whitespace and lowercase, so fuzzy re-anchoring shrugs
 * off cosmetic differences (mirrors the sources viewer's normalise()).
 */
export function normalise(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLowerCase();
}

/**
 * Split source markdown into top-level blocks on blank lines, preserving each
 * block's character offsets into the original string. Empty/whitespace-only
 * segments are dropped so a run of blank lines never yields a phantom block.
 */
export function splitBlocks(md: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const separator = /\n[ \t]*\n/g;
  const segments: Array<{ start: number; end: number }> = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = separator.exec(md)) !== null) {
    segments.push({ start: cursor, end: match.index });
    cursor = match.index + match[0].length;
  }
  segments.push({ start: cursor, end: md.length });

  for (const seg of segments) {
    let s = seg.start;
    let e = seg.end;
    while (s < e && /\s/.test(md[s])) s++;
    while (e > s && /\s/.test(md[e - 1])) e--;
    if (e <= s) continue;
    blocks.push({ index: blocks.length, start: s, end: e, text: md.slice(s, e) });
  }
  return blocks;
}

/**
 * Resolve a selected substring to (blockIndex, startOffset, endOffset) within a
 * given block's source text. Offsets are block-relative. Tries an exact
 * indexOf first, then a normalised fuzzy match, so a selection that spans
 * rendered markup (e.g. bold/citation syntax) still anchors. Returns null when
 * the text can't be located in the block.
 */
export function resolveOffsetsInBlock(
  block: MarkdownBlock,
  selectedText: string
): AnchorOffsets | null {
  const raw = selectedText.trim();
  if (!raw) return null;

  const exact = block.text.indexOf(raw);
  if (exact !== -1) {
    return {
      blockIndex: block.index,
      startOffset: exact,
      endOffset: exact + raw.length,
      quotedText: raw,
    };
  }

  // Fuzzy: locate the normalised needle inside the normalised block text, then
  // map the normalised index back to a raw offset by walking characters.
  const needle = normalise(raw);
  if (!needle) return null;
  const normBlock = normalise(block.text);
  const at = normBlock.indexOf(needle);
  if (at === -1) return null;

  const rawStart = mapNormalisedIndexToRaw(block.text, at);
  const rawEnd = mapNormalisedIndexToRaw(block.text, at + needle.length);
  return {
    blockIndex: block.index,
    startOffset: rawStart,
    endOffset: rawEnd,
    quotedText: block.text.slice(rawStart, rawEnd),
  };
}

/**
 * Given a normalised-string index, return the corresponding index into the raw
 * string. Walks the raw string reproducing the same whitespace collapsing that
 * `normalise` performs, counting normalised characters until the target.
 */
function mapNormalisedIndexToRaw(raw: string, normIndex: number): number {
  let normCount = 0;
  let i = 0;
  // Skip the leading whitespace that normalise().trim() would remove.
  while (i < raw.length && /\s/.test(raw[i])) i++;
  let prevWasSpace = false;
  for (; i < raw.length; i++) {
    if (normCount >= normIndex) return i;
    const isSpace = /\s/.test(raw[i]);
    if (isSpace) {
      if (prevWasSpace) continue; // collapsed run — no normalised char emitted
      prevWasSpace = true;
      normCount += 1; // a single collapsed space
    } else {
      prevWasSpace = false;
      normCount += 1;
    }
  }
  return raw.length;
}

/**
 * Fuzzy re-anchor a stored quotedText against (possibly changed) source blocks.
 * Returns the block + offsets where the text now lives, or null if it's gone
 * (caller then shows the annotation detached in the gutter). Prefers the
 * originally-anchored block, then falls back to scanning every block.
 */
export function reanchor(
  blocks: MarkdownBlock[],
  quotedText: string,
  preferredBlockIndex: number
): AnchorOffsets | null {
  const preferred = blocks[preferredBlockIndex];
  if (preferred) {
    const hit = resolveOffsetsInBlock(preferred, quotedText);
    if (hit) return hit;
  }
  for (const block of blocks) {
    if (block.index === preferredBlockIndex) continue;
    const hit = resolveOffsetsInBlock(block, quotedText);
    if (hit) return hit;
  }
  return null;
}

/**
 * Stable source-markdown hash for stale-anchor detection. MUST match the
 * backend (`routers/annotations.py:source_hash`): SHA-256 hex, truncated to 16
 * chars. Async because it uses the Web Crypto SubtleCrypto API.
 */
export async function sourceHash(md: string): Promise<string> {
  const bytes = new TextEncoder().encode(md ?? "");
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 16);
}
