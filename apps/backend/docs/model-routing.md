# Model routing runbook (Workstream A)

Every generation call in the backend resolves its model through
`providers.resolve_model(tier)` — no service or router code hardcodes a model
ID. Switching providers is a **config-only** change: no code edits, no
redeploy of new logic. Embeddings are out of scope and stay on OpenAI
(1536-dim).

**As of the RAG-quality audit (see `docs/rag-quality-audit.md`), the default
is DeepSeek V4 Flash via OpenRouter for the answering path, with GPT-5.1 (also
via OpenRouter) as a deliberate exception for VerifyAgent's escalation tier.**
Requires `LLM_API_KEY`/`LLM_API_BASE` set to OpenRouter in Doppler — see
"Current production routing" below. This replaced an all-Anthropic default;
Anthropic remains fully supported as an override (see "Switching back to
Anthropic").

## Tier system

Callers pass an abstract **tier name**, never a raw model string. Two base tiers
plus named per-agent tiers:

| Tier | Used by | Default model |
|---|---|---|
| `haiku` | base cheap/fast tier | `openrouter/deepseek/deepseek-v4-flash` |
| `sonnet` | base strong tier + research corrective pass | `openrouter/deepseek/deepseek-v4-flash` |
| `draft` | `DraftAgent`, `document_graph`, ATO `drafter` | via alias → `haiku` |
| `verify` | `VerifyAgent` default | via alias → `haiku` |
| `verify_strong` | `VerifyAgent` on severe/flagged answers | `openrouter/openai/gpt-5.1` (**explicit**, not aliased) |
| `rerank` | LLM re-ranker (`knowledge/retrieval.py`) | via alias → `haiku` |
| `classify` | ATO letter `classifier` | via alias → `haiku` |

`verify_strong` is deliberately kept OUT of the alias cascade: it's the model
VerifyAgent escalates to for the *most severely flagged* draft answers, and
collapsing it onto the same cheap model as the draft it's reviewing would
remove the actual capability gap that escalation exists for. See
`docs/rag-quality-audit.md` §2.6-2.7 for why GPT-5.1 specifically (an
independent model family, not just a different Anthropic tier) rather than
keeping Sonnet.

`research.run()` still routes between `haiku`/`sonnet` from retrieval signals via
`route_model()`; `resolve_model(routed)` maps the decision to a concrete model.

### `resolve_model` resolution order

`providers.resolve_model(tier)` tries, in order:

1. `settings.MODEL_TIER_MAP[tier]` — a direct hit (the normal path).
2. `settings.MODEL_TIER_MAP[_TIER_ALIAS[tier]]` — an **alias fallback** so an
   agent tier still resolves when it is omitted from the map. `_TIER_ALIAS` maps
   `draft`/`rerank`/`classify`/`verify` → `haiku` and `verify_strong` → `sonnet`.
   So a deployment that only overrides `haiku`/`sonnet` in `MODEL_TIER_MAP`
   automatically moves every agent tier too.
3. The legacy `ANTHROPIC_HAIKU_MODEL` / `ANTHROPIC_SONNET_MODEL` fields (bare
   Claude IDs get an `anthropic/` prefix) — backwards-compatible fallback.
4. The `tier` string **verbatim** — an unknown tier is treated as an explicit
   model string (e.g. `openai/glm-5` passed straight through).

## Key-resolution precedence

`get_llm()` picks the API key **conditionally on `LLM_API_BASE`** so a gateway
key can never be sent to Anthropic:

- **`LLM_API_BASE` set (OpenRouter / OpenCode / any gateway on):**
  `LLM_API_KEY` > `OPENCODE_API_KEY` > `ANTHROPIC_API_KEY`.
- **`LLM_API_BASE` empty (Anthropic default):**
  `LLM_API_KEY` > `ANTHROPIC_API_KEY`. **`OPENCODE_API_KEY` is ignored** — if it
  exists in Doppler/Secrets but the base URL is empty, the app still routes to
  Anthropic AND sends the Anthropic key.

`LLM_API_KEY` is the generic override that always wins when set. The adapter is
constructed as `LiteLLMAdapter(api_key=<resolved>, api_base=settings.LLM_API_BASE
or None)`; a `None` `api_base` preserves the plain-Anthropic behaviour.

**This is why `LLM_API_KEY`/`LLM_API_BASE` must both be set for the OpenRouter
default below to actually take effect** — the `MODEL_TIER_MAP` model strings
alone are not enough; without `LLM_API_BASE` pointed at OpenRouter, `get_llm()`
still sends whatever key it resolves to Anthropic's endpoint, which fails
against an `openrouter/...` model ID.

## Current production routing (OpenRouter — default since the RAG-quality audit)

Required Doppler secrets (`prd` and any config you want this to apply to):

```
LLM_API_KEY=<openrouter key>
LLM_API_BASE=https://openrouter.ai/api/v1
```

Set only via `doppler secrets set LLM_API_KEY --project taxflow --config prd`
(and `LLM_API_BASE` the same way) — never hardcoded, and not something this
assistant sets on your behalf. As of this writing `prd` has `OPENROUTER_API_KEY`
set but **not** `LLM_API_KEY`/`LLM_API_BASE`, so the new `MODEL_TIER_MAP`
default below has no effect until both are set.

With those two secrets set, `MODEL_TIER_MAP`'s code default routes:

- `haiku` / `sonnet` (and everything that aliases to them —
  `draft`/`verify`/`rerank`/`classify`) → `openrouter/deepseek/deepseek-v4-flash`
- `verify_strong` → `openrouter/openai/gpt-5.1` (explicit, not aliased)

This was validated against a 30-question benchmark across the whole
retrieval+generation path during the RAG-quality audit (see
`docs/rag-quality-audit.md`) — Cohere rerank (+4/30) and section-title boost
were tuned against this same DeepSeek generation path, so switching the
generation model without re-validating retrieval tuning is not recommended.

## Switching to OpenCode (Doppler env)

OpenCode is an alternative OpenAI-compatible gateway, documented here for
reference — it is not the current default. Same environment-only pattern:

```
LLM_API_BASE=https://opencode.ai/zen/go/v1
OPENCODE_API_KEY=<opencode key>        # or set LLM_API_KEY instead
MODEL_TIER_MAP={"haiku":"openai/<deepseek-v4-flash>","sonnet":"openai/<deepseek-v4-pro>","draft":"openai/<deepseek-v4-flash>","verify":"openai/<deepseek-v4-flash>","rerank":"openai/<deepseek-v4-flash>","classify":"openai/<deepseek-v4-flash>","verify_strong":"openai/<deepseek-v4-pro>"}
```

`MODEL_TIER_MAP` is JSON; each tier points at an `openai/<model>` route (LiteLLM
speaks the OpenAI-compatible protocol against `LLM_API_BASE`). The key comes from
Doppler/secrets — **never hardcode it**.

## Overriding one agent's model

Because each agent has its own tier, you can move a single agent without touching
the others by setting just that tier in `MODEL_TIER_MAP`. For example, to run
verification on Sonnet-class everywhere but keep drafting cheap:

```
MODEL_TIER_MAP={"verify":"anthropic/claude-sonnet-4-6"}
```

Unset tiers fall through the alias chain (step 2) to the base tier's mapping, so
partial maps are safe.

## Caveats

1. **Prompt-cache discount off Anthropic.** `cacheable_system()` emits
   `cache_control` breakpoints; LiteLLM forwards them to Anthropic and no-ops them
   elsewhere — including the current OpenRouter default. Not a correctness risk,
   but the ~90% cached-input discount that Anthropic prompt caching gave us is
   gone under the current default; DeepSeek/OpenRouter pricing is still far
   cheaper per-token than Anthropic even without it. Cost consideration only.
2. **Structured-output support varies.** `RerankScores`, `VerificationResult` and
   `LetterClassification` use `generate_structured` (`response_format`).
   OpenRouter/OpenCode models may honour it weakly, but each call-site already
   wraps it in a `StructuredParseError` → plain-generation + tolerant-parse
   fallback, so a weak response just costs one retry. The DeepEval judge pilot
   (`docs/rag-quality-audit.md` §3) found DeepSeek V4 Flash has a real ~15-20%
   JSON-schema-compliance failure rate on complex schemas even with retries —
   this is the same underlying provider now used in the answering path, so
   watch structured-output tiers (`rerank`, `classify`) for elevated retry rates.
3. **Embeddings stay OpenAI.** `get_embedder()` / `EMBEDDING_PROVIDER` /
   `OPENAI_API_KEY` are untouched (DB vector columns are 1536-dim). Model routing
   covers generation only.
4. **Switching back to Anthropic.** Leave `LLM_API_KEY`/`LLM_API_BASE` unset in
   Doppler (or explicitly blank `LLM_API_BASE`) and set
   `MODEL_TIER_MAP={"haiku":"anthropic/claude-haiku-4-5","sonnet":"anthropic/claude-sonnet-4-6","verify_strong":"anthropic/claude-sonnet-4-6"}`
   — the alias cascade still applies, so this is a 3-key map, not 7.
