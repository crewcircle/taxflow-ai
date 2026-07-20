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
 *
 * `occurrence` (0-based) disambiguates repeated text WITHIN the block: when the
 * same string appears more than once, pass the index of the occurrence the user
 * actually selected (derived from the DOM position) so the anchor lands on the
 * right span instead of always the first. It applies to the exact path; the
 * fuzzy fallback ignores it (repeats after normalisation are vanishingly rare).
 */
export function resolveOffsetsInBlock(
  block: MarkdownBlock,
  selectedText: string,
  occurrence = 0
): AnchorOffsets | null {
  const raw = selectedText.trim();
  if (!raw) return null;

  const exact = nthIndexOf(block.text, raw, occurrence);
  if (exact !== -1) {
    return {
      blockIndex: block.index,
      startOffset: exact,
      endOffset: exact + raw.length,
      quotedText: raw,
    };
  }
  // If the requested occurrence doesn't exist, fall back to the first one so a
  // selection that repeats fewer times than expected still anchors.
  if (occurrence > 0) {
    const first = block.text.indexOf(raw);
    if (first !== -1) {
      return {
        blockIndex: block.index,
        startOffset: first,
        endOffset: first + raw.length,
        quotedText: raw,
      };
    }
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
 * Index of the `occurrence`-th (0-based) instance of `needle` in `haystack`, or
 * -1 if there are fewer than `occurrence + 1` matches. Used to disambiguate
 * repeated spans by their ordinal position.
 */
export function nthIndexOf(haystack: string, needle: string, occurrence: number): number {
  if (!needle) return -1;
  let from = 0;
  for (let i = 0; i <= occurrence; i++) {
    const at = haystack.indexOf(needle, from);
    if (at === -1) return -1;
    if (i === occurrence) return at;
    from = at + needle.length;
  }
  return -1;
}

/**
 * How many times `needle` occurs in `blockText` strictly before `offset`. Used
 * to derive the ordinal of a stored anchor so the highlighter can re-find the
 * SAME occurrence in the rendered DOM instead of always the first.
 */
export function occurrenceBeforeOffset(blockText: string, offset: number, needle: string): number {
  if (!needle) return 0;
  let count = 0;
  let from = 0;
  for (;;) {
    const at = blockText.indexOf(needle, from);
    if (at === -1 || at >= offset) return count;
    count += 1;
    from = at + needle.length;
  }
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
 *
 * Cross-block quotes: a selection that spanned multiple blocks stores the FULL
 * multi-block text as `quotedText` (offsets were clamped to the first block).
 * That full string never lives inside any single block, so when whole-quote
 * resolution misses we retry with just the first block-segment of the quote
 * (split on blank lines, mirroring `splitBlocks`) — the portion that was
 * actually anchored — so the highlight re-attaches instead of detaching.
 */
export function reanchor(
  blocks: MarkdownBlock[],
  quotedText: string,
  preferredBlockIndex: number
): AnchorOffsets | null {
  const whole = resolveAgainstBlocks(blocks, quotedText, preferredBlockIndex);
  if (whole) return whole;

  // Fallback for cross-block quotes: anchor to the first block-segment only.
  const firstSegment = splitBlocks(quotedText)[0]?.text;
  if (firstSegment && firstSegment !== quotedText.trim()) {
    return resolveAgainstBlocks(blocks, firstSegment, preferredBlockIndex);
  }
  return null;
}

/**
 * Resolve `needle` within `blocks`, trying the preferred block first then every
 * other block in order. Shared by `reanchor`'s whole-quote and first-segment
 * passes.
 */
function resolveAgainstBlocks(
  blocks: MarkdownBlock[],
  needle: string,
  preferredBlockIndex: number
): AnchorOffsets | null {
  const preferred = blocks[preferredBlockIndex];
  if (preferred) {
    const hit = resolveOffsetsInBlock(preferred, needle);
    if (hit) return hit;
  }
  for (const block of blocks) {
    if (block.index === preferredBlockIndex) continue;
    const hit = resolveOffsetsInBlock(block, needle);
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
