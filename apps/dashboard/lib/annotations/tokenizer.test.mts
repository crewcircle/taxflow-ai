/**
 * Unit tests for the pure annotation tokenizer. No DOM / network, so they run
 * on Node's built-in test runner with native TS type-stripping — no extra deps:
 *
 *   node --test --experimental-strip-types apps/dashboard/lib/annotations/tokenizer.test.mts
 *
 * (Not wired into CI — the dashboard package has no JS unit-test runner; the
 * Playwright e2e spec covers the DOM/UI path. These lock the offset/occurrence
 * math that BLOCKING 2/3 + HIGH 4 depend on.)
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  splitBlocks,
  resolveOffsetsInBlock,
  reanchor,
  nthIndexOf,
  occurrenceBeforeOffset,
} from "./tokenizer.ts";

test("splitBlocks splits on blank lines and preserves source offsets", () => {
  const md = "First block.\n\nSecond block.";
  const blocks = splitBlocks(md);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].text, "First block.");
  assert.equal(blocks[1].text, "Second block.");
  // offsets index back into the original source
  assert.equal(md.slice(blocks[1].start, blocks[1].end), "Second block.");
});

test("nthIndexOf returns the ordinal occurrence or -1", () => {
  const s = "a b a b a";
  assert.equal(nthIndexOf(s, "a", 0), 0);
  assert.equal(nthIndexOf(s, "a", 1), 4);
  assert.equal(nthIndexOf(s, "a", 2), 8);
  assert.equal(nthIndexOf(s, "a", 3), -1);
  assert.equal(nthIndexOf(s, "", 0), -1);
});

test("occurrenceBeforeOffset counts non-overlapping matches before an offset", () => {
  const md = "You owe $120,000 this year and $120,000 next year.";
  // first "$120,000" starts at 8, second at 31
  assert.equal(occurrenceBeforeOffset(md, 8, "$120,000"), 0);
  assert.equal(occurrenceBeforeOffset(md, 31, "$120,000"), 1);
  assert.equal(occurrenceBeforeOffset(md, md.length, "$120,000"), 2);
});

test("resolveOffsetsInBlock anchors the requested occurrence of repeated text", () => {
  const [block] = splitBlocks("You owe $120,000 this year and $120,000 next year.");
  const first = resolveOffsetsInBlock(block, "$120,000", 0);
  const second = resolveOffsetsInBlock(block, "$120,000", 1);
  assert.ok(first && second);
  assert.equal(first!.startOffset, 8);
  assert.equal(second!.startOffset, 31);
  // the two anchors are distinct spans, not both the first match
  assert.notEqual(first!.startOffset, second!.startOffset);
});

test("resolveOffsetsInBlock falls back to the first match when the occurrence is out of range", () => {
  const [block] = splitBlocks("only one $120,000 here");
  const hit = resolveOffsetsInBlock(block, "$120,000", 3);
  assert.ok(hit);
  assert.equal(hit!.startOffset, block.text.indexOf("$120,000"));
});

test("resolveOffsetsInBlock fuzzy-matches across collapsed whitespace", () => {
  const [block] = splitBlocks("net   taxable\nincome for the year");
  const hit = resolveOffsetsInBlock(block, "net taxable income", 0);
  assert.ok(hit);
  assert.equal(block.text.slice(hit!.startOffset, hit!.endOffset), "net   taxable\nincome");
});

test("resolveOffsetsInBlock returns null when the text is absent", () => {
  const [block] = splitBlocks("a paragraph of text");
  assert.equal(resolveOffsetsInBlock(block, "not present", 0), null);
});

test("reanchor prefers the original block then scans others", () => {
  const blocks = splitBlocks("alpha owes tax\n\nbeta owes tax");
  // stored in block 1, still there
  const same = reanchor(blocks, "beta owes tax", 1);
  assert.equal(same!.blockIndex, 1);
  // stored block index stale (points past end) — still found by scanning
  const scanned = reanchor(blocks, "alpha owes tax", 5);
  assert.equal(scanned!.blockIndex, 0);
  // gone entirely
  assert.equal(reanchor(blocks, "gamma owes tax", 0), null);
});

test("reanchor falls back to the first block-segment of a cross-block quote", () => {
  const blocks = splitBlocks("first paragraph here\n\nsecond paragraph here");
  // A cross-block selection stored the FULL multi-block text as quoted_text.
  const fullQuote = "paragraph here\n\nsecond paragraph";
  // The whole quote lives in no single block, but the first segment does, so
  // reanchor re-attaches to block 0 rather than detaching.
  const hit = reanchor(blocks, fullQuote, 0);
  assert.ok(hit);
  assert.equal(hit!.blockIndex, 0);
  assert.equal(hit!.quotedText, "paragraph here");
  assert.equal(blocks[0].text.slice(hit!.startOffset, hit!.endOffset), "paragraph here");
});

test("reanchor returns null when a cross-block quote's first segment is also gone", () => {
  const blocks = splitBlocks("totally different text\n\nanother block");
  const fullQuote = "missing lead\n\nmissing tail";
  assert.equal(reanchor(blocks, fullQuote, 0), null);
});

test("non-stale highlight needle is the first block's clamped substring", () => {
  // Mirrors the component's non-stale anchor: the highlight needle is
  // block.text.slice(start,end), which for a cross-block selection differs from
  // the full stored quoted_text and DOES exist inside the first block.
  const md = "You owe $120,000 this year.\n\nThat is due in April.";
  const blocks = splitBlocks(md);
  // Simulate a cross-block selection starting mid-block-0.
  const startOffset = blocks[0].text.indexOf("$120,000");
  const endOffset = blocks[0].text.length; // clamped to end of first block
  const needle = blocks[0].text.slice(startOffset, endOffset);
  assert.equal(needle, "$120,000 this year.");
  // The clamped needle resolves inside block 0.
  const hit = resolveOffsetsInBlock(blocks[0], needle, 0);
  assert.ok(hit);
  assert.equal(hit!.startOffset, startOffset);
});
