# Model routing runbook (Workstream A)

Every generation call in the backend resolves its model through
`providers.resolve_model(tier)` — no service or router code hardcodes a model
ID. Adding a new provider (e.g. OpenCode) is a **config-only** change: no code
edits, no redeploy of new logic. Anthropic is the default; embeddings are out of
scope and stay on OpenAI (1536-dim).

## Tier system

Callers pass an abstract **tier name**, never a raw model string. Two base tiers
plus named per-agent tiers:

| Tier | Used by | Default model |
|---|---|---|
| `haiku` | base cheap/fast tier | `anthropic/claude-haiku-4-5` |
| `sonnet` | base strong tier + research corrective pass | `anthropic/claude-sonnet-4-6` |
| `draft` | `DraftAgent`, `document_graph`, ATO `drafter` | `anthropic/claude-haiku-4-5` |
| `verify` | `VerifyAgent` default | `anthropic/claude-haiku-4-5` |
| `verify_strong` | `VerifyAgent` on severe/flagged answers | `anthropic/claude-sonnet-4-6` |
| `rerank` | LLM re-ranker (`knowledge/retrieval.py`) | `anthropic/claude-haiku-4-5` |
| `classify` | ATO letter `classifier` | `anthropic/claude-haiku-4-5` |

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

`get_llm()` picks the API key **conditionally on `LLM_API_BASE`** so the OpenCode
key can never be sent to Anthropic:

- **`LLM_API_BASE` set (OpenCode / gateway on):**
  `LLM_API_KEY` > `OPENCODE_API_KEY` > `ANTHROPIC_API_KEY`.
- **`LLM_API_BASE` empty (Anthropic default):**
  `LLM_API_KEY` > `ANTHROPIC_API_KEY`. **`OPENCODE_API_KEY` is ignored** — if it
  exists in Doppler/Secrets but the base URL is empty, the app still routes to
  Anthropic AND sends the Anthropic key.

`LLM_API_KEY` is the generic override that always wins when set. The adapter is
constructed as `LiteLLMAdapter(api_key=<resolved>, api_base=settings.LLM_API_BASE
or None)`; a `None` `api_base` preserves today's exact Anthropic behaviour.

## Switching to OpenCode (Doppler env)

OpenCode is opt-in and requires only environment changes:

```
LLM_API_BASE=https://opencode.ai/zen/go/v1
OPENCODE_API_KEY=<opencode key>        # or set LLM_API_KEY instead
MODEL_TIER_MAP={"haiku":"openai/<deepseek-v4-flash>","sonnet":"openai/<deepseek-v4-pro>","draft":"openai/<deepseek-v4-flash>","verify":"openai/<deepseek-v4-flash>","rerank":"openai/<deepseek-v4-flash>","classify":"openai/<deepseek-v4-flash>","verify_strong":"openai/<deepseek-v4-pro>"}
```

`MODEL_TIER_MAP` is JSON; each tier points at an `openai/<model>` route (LiteLLM
speaks the OpenAI-compatible protocol against `LLM_API_BASE`). The key comes from
Doppler/secrets — **never hardcode it**.

**Chosen defaults (user-confirmed):** Anthropic stays the default provider
(`LLM_API_BASE` empty ⇒ everything on the current Anthropic map). The documented
OpenCode example maps the **strong** tier (`sonnet`/`verify_strong`) to
**DeepSeek V4 Pro** and the **cheap/fast** tier
(`haiku`/`draft`/`verify`/`rerank`/`classify`) to **DeepSeek V4 Flash** — supply
the exact `openai/<deepseek-v4-*>` model IDs from the OpenCode catalog when
enabling.

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
   elsewhere. Switching the provider is not a correctness risk but forfeits the
   ~90% cached-input discount. Cost consideration only.
2. **Structured-output support varies.** `RerankScores`, `VerificationResult` and
   `LetterClassification` use `generate_structured` (`response_format`). OpenCode
   models may honour it weakly, but each call-site already wraps it in a
   `StructuredParseError` → plain-generation + tolerant-parse fallback, so a weak
   response just costs one retry. Tiers used for structured output must still
   return usable JSON.
3. **Embeddings stay OpenAI.** `get_embedder()` / `EMBEDDING_PROVIDER` /
   `OPENAI_API_KEY` are untouched (DB vector columns are 1536-dim). Model routing
   covers generation only.
