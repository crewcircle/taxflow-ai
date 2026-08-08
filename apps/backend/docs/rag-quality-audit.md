# RAG quality audit — findings and roadmap

Working record of the retrieval/citation-quality investigation that started
from a 30-question internal accuracy benchmark scoring far below the 80%
target. Covers both **ingestion** (what's in the corpus, how it's chunked)
and **retrieval** (how a query finds the right chunk), what's been tried,
what worked, what didn't, and what's still open.

Related: `scripts/experiments/graphrag_accuracy/README.md` (the LightRAG/
Cognee framework comparison this audit grew out of).

## Current default configuration

| Setting | Default | Status |
|---|---|---|
| `HIERARCHICAL_CHUNKING_ENABLED` | `True` | Shipped |
| `PARENT_EXPANSION_ENABLED` | `True` | Shipped |
| `JURISDICTION_BOOST_WEIGHT` | `0.25` | Shipped |
| `SECTION_TITLE_BOOST_WEIGHT` | `0.3` | Shipped |
| `RETRIEVAL_MAX_PER_SOURCE_URL` | `4` | Shipped |
| `RETRIEVAL_GLOBAL_POOL` / `RETRIEVAL_TOP_K` | `16` / `18` | Shipped |
| `RERANK_MODE` | `"rrf_only"` | Cohere rerank built, validated (+4 net on benchmark), **not yet the default** |
| `QUERY_DECOMPOSITION_ENABLED` | `False` | Built, redesigned once, evidence still inconclusive — **stays off** |

---

## 1. Ingestion — explored

### 1.1 Hierarchical chunking for legislation (shipped)
`LegislationScraper._extract_text` used to call BeautifulSoup's
`get_text(separator="\n")` on the whole page, which inserts the separator at
*every* tag boundary, not just block-level ones — a heading built from
several inline spans (e.g. "40", a non-breaking hyphen, "1") landed on 2-3
separate lines instead of one, which no bare-text regex could ever reliably
match. Confirmed live: `HIERARCHICAL_CHUNKING_ENABLED` had been off for every
legislation ingestion to date as a direct result.

Rewrote extraction to walk `<p>` elements in reading order, skip
legislation.gov.au's own Table-of-Contents paragraph classes (which repeat
every heading as plain text and were polluting the parsed structure), and
stamp real DOM headings with a sentinel prefix
(`structure.LEGISLATION_SENTINELS`) that the parser matches unambiguously.
Verified against live HTML for all 5 ingested Acts (ITAA 1997, ITAA 1936, GST
Act, FBTAA 1986, SGA Act).

**Re-ingested all 5 Acts against prod**: 7,747 flat chunks → 27,385
hierarchical chunks, each carrying a real `heading_path` breadcrumb and
`section_ref`.

### 1.2 Landmark case law seeding (shipped)
`AustLIIScraper` is RSS-feed-based ("recent decisions" feeds) and had never
surfaced a single case, since landmark cases predate any RSS window.
Hand-seeded one individually-verified case: *FCT v Spotless Services Ltd
[1996] HCA 34*. A second candidate, *FCT v Cooling*, was investigated and
**deliberately dropped** — the citation repeated across multiple secondary
sources ("[1990] FCA 297") was verified wrong by direct fetch (an unrelated
1990 insolvency matter), and no correct citation was found. Documented in
`scripts/seed_landmark_cases.py`'s own docstring as a cautionary example.

### 1.3 Pre-2018 ATO ruling gap (shipped)
`ATORulingsScraper` brute-forces PDF URLs but only enumerates
`YEARS = range(2026, 2017, -1)` — a deliberate bound on brute-force
existence-checking cost. TD 2014/25 (bitcoin/cryptocurrency CGT
determination) predates that range and was entirely absent from the corpus.
Verified the URL live (200, `application/pdf`) before seeding via
`scripts/seed_pre2018_ato_rulings.py`. 53 chunks now live in prod.

### 1.4 Corpus gaps checked and found to NOT be gaps
Two questions initially suspected as corpus gaps (zero citations returned)
turned out to already have real content ingested — the failures were
retrieval bugs, not missing data:
- **SMSF concessional contributions cap** (ITAA 1997 s.292-25 area) — 7
  chunks already existed.
- **WFH shortcut method** (PCG 2023/1) — 21 chunks already existed.

### 1.5 Ingestion gaps — still open, not yet explored
- **State legislation isn't ingested at all** — only federal Acts (the same
  5) plus **state revenue office rulings** (interpretive guidance PDFs) are
  in the corpus. The actual text of e.g. the *Payroll Tax Act 2007 (NSW)* —
  including its own grouping-threshold provisions — was never scraped. This
  is the root cause behind q05 (NSW payroll tax grouping): the closest
  matching content in the corpus is a narrow discretion-to-exclude ruling,
  not the Act's own grouping definition, because the Act itself isn't there.
- **SIS Act** (Superannuation Industry (Supervision) Act 1993) — confirmed
  absent (0 chunks). Only ITAA 1997's concessional-cap provisions are
  covered for SMSF questions, not the SIS Act side of the same topic.
- **Rate/threshold-sensitive facts not independently verified against a
  current source** beyond what the corpus itself already shows: FBT rate
  (q03), instant asset write-off threshold (q10), SMSF concessional cap
  dollar figure (q24), WFH shortcut cents-per-hour rate (q28). One fixture
  fact (`questions.json`'s R&D offset rate) was confirmed stale via repeated
  corpus evidence and corrected (43.5% → 8.5%, the tiered rate post-2021
  reform) — these four were checked the same way and found inconclusive
  either way, left unchanged rather than guessed at.

---

## 2. Retrieval — explored

### 2.1 VerifyAgent topic-mismatch gate (shipped)
`_estimate_confidence` only ever counted citation/chunk quantity, not
topical relevance — a confident, well-cited answer citing topically
unrelated sources (e.g. NSW payroll-tax rulings cited for a federal FBT
question) skipped verification entirely. `should_verify` now also checks
topic alignment between the question and its cited sources via the existing
`classify_topic` regex classifier (no LLM call), reusing it symmetrically.

### 2.2 Jurisdiction-aware soft boost (shipped)
State revenue offices publish near-identically-titled rulings independently
per state (e.g. "Commissioners Discretion To Exclude From A Group" exists
for both NSW and WA). Nothing in retrieval carried jurisdiction at all, so a
topically-similar wrong-state ruling could out-rank the correct one — root
cause of an NSW payroll-tax question retrieving a WA ruling. Added a
soft-boost (mirroring the existing source_type boost) when a question
explicitly names an AU state/territory, plus surfaced jurisdiction directly
in the LLM re-ranker's own prompt. Verified live: NSW content now dominates
that question's top-10, where WA previously ranked #1.

### 2.3 Per-source-url diversity cap (shipped)
A single long ruling chunked with overlapping windows could place many
near-duplicate chunks at the top of the candidate pool, crowding out a
different, more relevant source entirely (13 chunks of one ruling dominating
the pool for an SMSF question, pushing the actually-relevant ITAA 1997
content out). Capped candidates per `source_url` in the pre-rerank pool.

### 2.4 Retrieval pool sizing (shipped)
`RETRIEVAL_GLOBAL_POOL`/`RETRIEVAL_TOP_K` (8/10) were tuned for flat
~512-token chunks. Hierarchical chunking packs by logical unit (many
subsections are 50-150 tokens) and legislation grew ~3.5x more chunks for
the same 5 Acts, so the same pool size covered proportionally less text.
Scaled to 16/18.

### 2.5 Section-title soft boost (shipped)
Deterministic, zero-LLM-call complement to the reranker: boosts a candidate
whose *own* section heading title shares content words with the question —
e.g. favours a sibling titled "Concessional contributions cap" over one
titled "Excess non-concessional contributions tax" when the question asks
about the concessional cap. Runs at the RRF-merge stage before any rerank,
so it helps even with `RERANK_MODE="rrf_only"`. Verified live: more
concessional-cap-relevant content surfaces for that question, though it
doesn't fully close the gap alone (the exact section still doesn't always
enter the pool — see §2.8).

### 2.6 Cohere Rerank via OpenRouter (built, validated, not yet default)
A cross-encoder does fine-grained joint query/passage scoring, specifically
better than RRF or the LLM reranker's coarse 0-1 judgment at discriminating
between structurally-similar sibling provisions — the "right Division, wrong
Section" pattern found repeatedly (e.g. ITAA 1997 Subdivision 292-B
concessional cap vs 292-C non-concessional). Hosted via OpenRouter's
`/rerank` endpoint (`cohere/rerank-4-fast`, $0.002/search) rather than a
local cross-encoder, since this backend deliberately carries no ML/torch
dependency (documented constraint: 2 vCPU / 4GB droplet).

Live-verified against the real endpoint: asked it to rank three candidates
for "SMSF concessional contributions cap" and it correctly scored Subdivision
292-B (0.74) above 292-C (0.54) above an unrelated ruling (0.15).

**Full 30-question benchmark result: 16/30 → 20/30 (+4 net)**, zero infra
errors that run. q14 (the exact thin-capitalisation/Division 820
sibling-section case this was built for) fully recovered from 2/5 to 5/5.
Some individual regressions occurred alongside the wins (q12, q03, q30) —
expected of any reranking change; net effect clearly positive.

### 2.7 Query decomposition (built, redesigned once, evidence inconclusive — OFF by default)
One LLM call rewriting the question into a more specific search query before
the full-text search leg only (not the shared embedding, which is computed
once upstream and reused across several call sites).

**First design (destructive) — net regression, confirmed reproducible.**
The original prompt said "keep it short (1-2 sentences)", which encouraged
the model to strip natural-language question words and compress into a bare
keyword fragment (e.g. *"PAYG withholding variation eligibility conditions
employer application process"* instead of the original question). Two
independent 30-question runs on top of Cohere reranking both scored below
the Cohere-only baseline (20/30 → 17/30, then → 15/30), and 4 specific
questions (q07, q15, q19, q27) regressed in **both** runs — not
attributable to noise.

**Second design (append-only) — partial fix, net effect still unclear.**
Redesigned the prompt to default to returning the question completely
unchanged, and only ever *append* a clarifying phrase, never delete/reword/
compress. Verified directly: all 4 previously-hurt questions now
consistently return unchanged text, and the original target case (q24) now
genuinely appends ("...current financial year? concessional contributions
cap") rather than replacing.

A third full run scored **16/30** — still below the 20/30 Cohere-only
baseline. 2 of the 4 originally-regressed questions recovered to baseline
(q15, q19); 2 did not (q07, q27) — but by that point the query text for
those two was *verified identical* to the no-decomposition case, so their
low scores can no longer be attributed to decomposition at all; that has to
be the benchmark's own run-to-run noise (this session repeatedly observed
3+ point swings on identical configs). The run also newly regressed 3
*different* questions not hurt in either prior run.

**Conclusion**: the append-only redesign is a real, confirmed fix over the
destructive version (removed a genuine bug) and should be kept regardless.
But there isn't enough signal from single 30-question runs to claim
decomposition is a net positive — the benchmark's inherent noise floor is
large enough to swamp whatever real effect remains. **Decision: leave
`QUERY_DECOMPOSITION_ENABLED` off by default.** Revisiting this would need a
sturdier evaluation methodology (see §4), not another single run.

### 2.8 Retrieval gaps — still open, not yet explored
- **Genuine recall misses, not rank-order problems.** q05 (NSW payroll tax
  grouping) and q24 (SMSF concessional cap): even after jurisdiction
  boosting, section-title boosting, and a 2x-widened pool, the exact right
  content never enters the candidate window at all in some cases. No
  reranking-stage fix (Cohere or otherwise) can help if the chunk was never
  retrieved in the first place — this needs either RRF/embedding tuning
  specific to these corpora, or the ingestion-side fix in §1.5 (NSW Payroll
  Tax Act itself isn't in the corpus for q05 specifically).
- **Corrective pass doesn't reliably fix a verify-caught hallucination.**
  q24: VerifyAgent correctly caught the draft answer misdescribing its own
  sources ("the source documents do not mention any contribution caps at
  all, so the claim... is false") — a real, precise catch. But the
  corrective rewrite, even with widened retrieval, reproduced essentially
  the same wrong claim. Traced to the widened retrieval *itself* still
  landing on Subdivision 292-C instead of 292-B — the corrective LLM call
  had nothing better to ground itself in, verify feedback notwithstanding.
  Not yet fixed; would need the recall fix above before the corrective pass
  can succeed here.
- **"Still good law" supersession checking** — flagged from competitor
  research (vLex/Harvey both verify a cited source hasn't been amended or
  superseded since ingestion; TaxFlow's VerifyAgent checks topical alignment
  but not supersession/currency). Not scoped or built.
- **Cross-encoder fine-tuning or domain-specific prompting** — the Cohere
  reranker is used off-the-shelf; research flagged that generic-corpus
  rerankers underperform on legal text without some domain adaptation
  (fine-tuning on ~1-5k domain-labeled pairs is the usual fix). Not
  attempted — would require building a labeled pair dataset first.
- **ColBERTv2 / late-interaction retrieval** — still just a bounded-
  experiment candidate per the original framework research, never actually
  tried. Real infra cost (multi-vector storage/indexing); would need a
  time-boxed spike, not a default-path change.

---

## 3. Evaluation methodology — explored

### 3.1 Hand-rolled scorer literalism (multiple rounds of fixes, shipped)
The benchmark's own `score_answer()` heuristic (exact substring matching
against `expected_topics`/`expected_citations`) repeatedly under-reported
real answer quality, independent of any retrieval quality issue:
- Multi-number citation brackets (`[1, 7]`) were silently dropped by a
  regex that only matched a lone digit (`[N]`).
- `"s.N"`/`"Div N"` style citations and topics didn't match natural
  phrasing ("section 9-80" vs the literal "s.9-80" string).
- The citation dict's richer `section` field (real heading breadcrumb, e.g.
  "...Section 25-35 (Bad debts)") was never checked — only the often-bare
  `citation` label was, even when the section field was an exact match.
- One fixture fact (R&D offset rate) was flatly stale (pre-2021 law).

Fixing all of the above moved the raw score from 5/30 to 15/30 on the *same*
underlying answers — i.e. roughly two-thirds of the initial "failure" was
scorer artifact, not real retrieval regression.

### 3.2 DeepEval pilot — LLM-judged faithfulness/relevancy (explored, not adopted)
Piloted DeepEval's `FaithfulnessMetric`/`AnswerRelevancyMetric` (LLM-as-judge)
against the same 30 answers, judged by DeepSeek V4 Flash via OpenRouter
(cheaper on output tokens than the absolute-cheapest OpenRouter model, and
already proven reliable elsewhere in this pipeline).

**Result: old scorer 15/24 pass vs DeepEval 21/24 pass** (24/28, excluding
infra errors) — nearly every case where they disagreed was the old scorer
being too harsh exactly where hand-diagnosis predicted (natural phrasing,
adjacent-but-correct sections, honest refusals). The judge also
independently caught things the crude scorer structurally couldn't: q05's
low *relevancy* despite high faithfulness (an honest but unhelpful refusal),
and q24's exact numeric hallucination (misstating a $15,000 FHSS limit
against a $50,000/$6,600 figure actually in context).

**Judge reliability caveat, found and only partially fixed**: the cheap
judge model failed to return valid/schema-conforming JSON on ~15-20% of
calls. Added a schema-validating retry loop (DeepEval's own default
`a_generate_with_schema` doesn't validate at all) — first attempt escalated
temperature on retry, which made things *worse* (a case that failed 3x at
temp=0.4 succeeded cleanly at temp=0); reverted to retrying at temp=0
consistently. Even after that fix, failure rate didn't measurably improve
run-to-run (23-24/28 judged across attempts). **Not resolved** — a more
reliable (likely pricier) judge model is the next lever, not more retry
engineering on this one.

### 3.3 Evaluation gaps — still open, not yet explored
- **DeepEval was never adopted as the primary scorer** — it was a pilot
  proving the concept, run against already-generated answers, not wired
  into the actual benchmark loop or CI.
- **A more reliable judge model** hasn't been tried (cost/reliability
  trade-off deliberately not explored yet).
- **Single-run noise across the whole benchmark** is large enough that
  several genuine findings this session (query decomposition's net effect,
  the reproducibility of "zero infra errors" runs) couldn't be resolved with
  confidence from one run. Averaging 3-5 runs per configuration would be the
  fix, at real additional API cost/time per config tested.
- **RAGAS** (the more RAG-purpose-built alternative to DeepEval, per the
  original framework research) was never actually piloted, only
  recommended as a secondary option.

---

## 4. Summary: what's shipped vs what's next

**Shipped and live in prod:** hierarchical legislation chunking + full
re-ingestion, landmark case seeding, the pre-2018 ATO ruling gap, VerifyAgent
topic-mismatch gating, jurisdiction-aware boost, per-source-url diversity
cap, retrieval pool sizing, section-title boost, corrective-pass token
budget fix, DB connection pre-ping, LLM request timeout/retry, and every
scorer literalism fix.

**Built and validated, awaiting a decision to flip the default:** Cohere
Rerank via OpenRouter (`RERANK_MODE="cohere"`) — clean +4/30 win, ready to
enable.

**Built, evidence inconclusive, deliberately left off:** query
decomposition (`QUERY_DECOMPOSITION_ENABLED`) — real bug fixed
(destructive→append-only), but net benefit not established.

**Not yet started, highest-leverage candidates:**
1. Ingest NSW Payroll Tax Act (and likely other state Acts) as legislation,
   not just rulings — the clearest remaining root cause with a known fix.
2. Investigate the q05/q24-style pure recall misses (right chunk never in
   candidate pool) — a different problem than anything reranking can solve.
3. A "still good law" / supersession check in VerifyAgent, the one concrete
   technique competitor research surfaced that TaxFlow doesn't do yet.
4. Decide on DeepEval (or RAGAS) as the real scoring methodology going
   forward, given the hand-rolled scorer's demonstrated ceiling even after
   multiple rounds of fixes.
