/**
 * Small shared helpers for the annotation layer. Offset/anchor computation
 * itself now lives inside @recogito/text-annotator (it anchors directly
 * against rendered DOM Ranges, so there's no more markdown-block-splitting or
 * fuzzy re-anchoring to hand-roll here).
 */

/**
 * Strip markdown emphasis/code-span syntax, leaving the enclosed text as-is.
 * Needed because a quoted claim (from VerifyAgent) is copied from the raw
 * markdown source and may carry "**bold**"/"__bold__"/"`code`" markers that
 * never appear as literal characters in the rendered DOM - react-markdown
 * consumes them to produce <strong>/<code> elements, so a needle destined for
 * matching against rendered text must have this syntax removed first.
 */
export function stripMarkdownEmphasis(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/`(.+?)`/g, "$1");
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
