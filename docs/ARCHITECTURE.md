# TaxFlow AI — Architecture & Data Flow

A description of how data moves through TaxFlow AI, drawn from the code as it
stands on `main`. Component names, file paths, ports, and table names below are
the real ones in the repo, not placeholders.

## 1. What the system is

TaxFlow AI is an Australian tax research and compliance product for accounting
firms. A user asks a tax question; the backend runs it through a retrieval +
LLM agent pipeline against a curated knowledge base (ATO rulings, legislation,
AustLII case law, state revenue material), returns an answer with citations and
a verification pass, and lets the firm save that answer as a document, manage
client engagements, upload their own firm knowledge, and track regulatory
alerts.

The repo is a pnpm + turbo monorepo with two deployable apps:

- `apps/dashboard` — Next.js 16 / React 19 front end (Vercel).
- `apps/backend` — Python 3.12 FastAPI service (Docker on a DigitalOcean
  droplet, fronted by Caddy).

Persistent state lives in Supabase (Postgres + pgvector + GoTrue auth). Object
storage is Cloudflare R2 (S3 API). LLM and embedding calls go out through
LiteLLM to Anthropic and OpenAI. Billing is Stripe.

## 2. Top-level component map

```
                          Browser (firm user)
                                  |
                    HTTPS (Vercel edge + SSR)
                                  |
            +---------------------v----------------------+
            |            apps/dashboard (Next.js)         |
            |                                             |
            |  Server Components  +  Route Handlers       |
            |  app/dashboard/*        app/api/*/route.ts  |
            |  (SSR pages)            (server-side proxy) |
            +------+-------------------------+------------+
                   |                         |
   Supabase JS SSR |                         | fetch() with
   (cookie session)|                         | Authorization: Bearer <JWT>
                   |                         | NEXT_PUBLIC_API_URL
       +-----------v-----------+   +---------v-----------------------------+
       |  Supabase GoTrue      |   |     apps/backend (FastAPI)            |
       |  (auth: login, JWT,   |   |                                       |
       |   demo magic-link)    |   |  RequestLoggingMiddleware             |
       +-----------+-----------+   |  -> routers/*  (HTTP layer)           |
                   |               |  -> middleware/auth + trial_gate      |
                   | verify JWT    |  -> services/*  (domain logic)        |
                   +---------------+  -> ports/*     (interfaces)          |
                                   |  -> providers.py (wiring)             |
                                   |  -> adapters/*  (concrete I/O)        |
                                   +--+------+------+------+------+---------+
                                      |      |      |      |      |
                            Postgres  |  R2  | LLM  | embed| Stripe
                           +pgvector  | (S3) |Anthro| OpenAI|
                          (Supabase)  |      |pic   |       |
```

The backend is a ports-and-adapters (hexagonal) design. Routers and services
never talk to Postgres, Stripe, or an LLM directly; they call an interface in
`ports/` and `providers.py` hands back the concrete adapter from `adapters/`.
This is why the whole outbound edge can be swapped or mocked in one place.

## 3. The layers inside the backend

```
 HTTP            routers/         query, documents, ato_response, firm_clients,
 (FastAPI)                        firm_knowledge, knowledge, notifications,
                                  regulatory_alerts, settings, admin, auth,
                                  contact, webhooks, health

 Cross-cutting   middleware/      request_logging (request-id + structured logs)
                                  auth.get_current_client (JWT -> client row)
                                  trial_gate.check_trial_gate / increment_usage

 Domain          services/        agents/ (research, draft, verify, re_research,
 (business                          graph = LangGraph agent loop)
  logic)                          knowledge/ (retrieval, ingest, embedder,
                                    pipeline, scrapers)
                                  ato_correspondence/ (classifier, drafter)
                                  answer_cache, demo_reset, regulatory_monitor,
                                  export

 Ports           ports/           relational, vectorstore, llm, embedding, auth,
 (interfaces)                     billing, storage, scheduler, scrapers

 Wiring          providers.py     get_relational_data() / get_vector_store() /
                                  get_llm() / get_embedder() / get_auth_port() /
                                  get_billing_port() / get_object_storage() /
                                  get_scheduler_port() ...

 Adapters        adapters/        db/repositories.py        (Postgres)
 (concrete I/O)                   vectorstore/pgvector.py   (pgvector search)
                                  llm/litellm_adapter.py    (Anthropic via LiteLLM)
                                  embedding/litellm_adapter (OpenAI embeddings)
                                  auth/supabase.py          (GoTrue JWT verify)
                                  billing/stripe.py         (Stripe)
                                  storage/s3.py             (Cloudflare R2)
                                  scheduler/apscheduler.py  (cron jobs)
                                  render/docx_pdf.py        (document export)
                                  tokenizer/tiktoken.py
```

## 4. Request path: browser to backend

The dashboard does **not** call the backend directly from the browser. Every
data call goes through a Next.js server-side route handler (`app/api/*/route.ts`)
or a server component (`app/dashboard/*/page.tsx`, `layout.tsx`). Those read
`process.env.NEXT_PUBLIC_API_URL` and attach the user's Supabase JWT as a
`Bearer` token.

```
Browser click
  -> Next.js Server Component / Route Handler (runs on Vercel, not the browser)
       - reads Supabase session from cookie (lib/supabase/server.ts)
       - fetch(`${NEXT_PUBLIC_API_URL}/<path>`, Authorization: Bearer <JWT>)
  -> FastAPI RequestLoggingMiddleware (assigns request-id, structured log)
  -> router endpoint
       - Depends(get_current_client): adapters/auth/supabase verifies the JWT
         with GoTrue, maps token -> clients row by email (provisioning on first
         sight in _get_or_provision_client)
       - Depends(check_trial_gate): reads trials row; 402 if subscription
         inactive or queries_used >= queries_cap
  -> service layer (domain logic)
  -> ports -> providers -> adapters -> Postgres / R2 / LLM / Stripe
  <- response JSON (or Server-Sent Events stream for /query/stream)
```

Auth is JWT-based end to end: GoTrue issues the token, the backend verifies it
on every request, and the `clients` row is keyed to the token's email.

## 5. The core flow: a research query

This is the heart of the product — `POST /query` (buffered) and
`GET /query/stream` (SSE token streaming). Both drive the same compiled
LangGraph agent (`services/agents/graph.py`).

```
POST /query  (routers/query.py)
  |
  | get_current_client -> trial_gate
  v
answer_cache check  ---------------- hit --> return cached answer (no pipeline)
  | miss
  v
+-------------------------------------------------------------+
|  research_graph  (services/agents/graph.py, LangGraph)      |
|                                                             |
|  retrieve ---> [optional single re-retrieve if weak signal] |
|      |                                                      |
|      |  hybrid_search (services/knowledge/retrieval.py):    |
|      |    - embed(query)          [OpenAI via LiteLLM]       |
|      |    - semantic search       [pgvector cosine]          |
|      |    - full-text search      [Postgres]                 |
|      |    - RRF merge of the two ranked lists                |
|      |    - optional LLM rerank                              |
|      v                                                      |
|   route ---> generate  [Anthropic via LiteLLM]              |
|                 |                                           |
|                 v                                           |
|          gated verify  (services/agents/verify.py)          |
|                 |                                           |
|                 +-- issues found --> at-most-once           |
|                 |                     corrective regenerate  |
|                 v                                           |
|             final answer + citations + trace                |
+-------------------------------------------------------------+
  |
  v
persist to Postgres:
  - queries row (question, final_answer, citations, confidence_score,
    verification_result, model_used, trace, client_ref, topic_tag, session_id)
  - increment trials.queries_used (trial_gate.increment_usage)
  v
return answer + citations + "why this answer?" trace
```

Notes that matter for the data:

- **Conversation memory** is scoped by `(client_id, session_id)`. The UI mints a
  fresh `session_id` per conversation and reuses it across turns; the agent
  loads prior turns for that pair and prepends a compact "conversation so far"
  block. It never crosses sessions or clients.
- **Retrieval is hybrid**: semantic (pgvector) + full-text, combined with
  Reciprocal Rank Fusion, then an optional LLM rerank. Every returned chunk
  carries a `score` (and `rerank_score` in LLM mode).
- **Verification is gated**, and a corrective regeneration runs **at most once**
  — the bounded control flow is deliberate so a query can't loop.
- **The stored `trace`** is what powers the "why this answer?" panel: it records
  retrieval, generation, verification, any corrective pass, and any
  re-retrieval.

## 6. Knowledge base: ingestion vs. retrieval

There are two distinct knowledge sources, kept separate:

- **Global knowledge** (`knowledge_chunks`) — ATO rulings, legislation, AustLII
  case law, state revenue. Populated by scheduled scrapers.
- **Firm knowledge** (`firm_knowledge`) — documents a firm uploads themselves,
  scoped to their `client_id`.

```
Ingestion (write path, scheduled):
  scheduler (kb_ingestion, daily 16:00 UTC)
    -> services/knowledge/ingest.run_all
    -> adapters/scrapers (ato_rulings, austlii, legislation, state_revenue)
    -> pipeline: structure -> chunk -> embed [OpenAI]  -> knowledge_chunks
                                                          (embedding vector,
                                                           is_current, source_*)

Retrieval (read path, per query):
  hybrid_search -> pgvector semantic + Postgres full-text over knowledge_chunks
                   (+ firm_knowledge for that client) -> RRF -> rerank
```

Both embedding columns are `vector(EMBEDDING_DIMENSION)`. On startup the
lifespan hook `_assert_embedding_dimension()` probes the live embedder and
refuses to boot if its real output length disagrees with the configured
dimension — because a mismatch would silently corrupt inserts and similarity
search. (This guard is toggled by `EMBEDDING_DIM_GUARD_ENABLED`.)

## 7. Documents, ATO correspondence, engagements

- **Documents** (`documents` table): a research answer can be drafted into a
  firm-styled advice memo (`services/agents/draft.py`). The DOCX/PDF file is
  **not** stored; `download_document()` regenerates it on demand from
  `content_md` via `adapters/render/docx_pdf.py`, with the binary going through
  R2 object storage when needed.
- **ATO correspondence** (`services/ato_correspondence/`): an inbound ATO letter
  is classified (`classifier.py`) and a response is drafted (`drafter.py`),
  saved as a `documents` row with `document_type = 'ato_response'`.
- **Engagements** (`engagements`, plus `queries.engagement_id` /
  `documents.engagement_id`): work is grouped under a client engagement.
  `firm_clients` is the firm's client roster; the "who is this for?" picker
  searches it.

## 8. Billing and trial gating

```
Signup -> clients row + trials row (trial_status, queries_cap, docs_cap)
Every gated request -> trial_gate.check_trial_gate
    - subscription inactive        -> 402
    - queries_used >= queries_cap  -> 402
Upgrade -> POST /api/checkout -> Stripe Checkout
Stripe -> POST /webhooks/stripe
    - verify_and_parse_webhook (signature check, adapters/billing/stripe.py)
    - checkout.session.completed -> clients.subscription_status = 'active'
```

## 9. Scheduled (background) jobs

Registered in `adapters/scheduler/apscheduler.py`, started by the FastAPI
lifespan (`start_scheduler`) on every backend boot, each wrapped in a
`_leader_guard` so only one worker runs it:

```
kb_ingestion        cron  daily 16:00 UTC   scrape + embed new knowledge
regulatory_monitor  cron  Sun 20:00 UTC     check regulatory feeds
demo_reset          cron  daily 17:00 UTC   DELETE demo clients' queries/docs/
                                            annotations/query_feedback
re_research_drain   interval (short)        drain the re_research_jobs queue
```

> Operational note: `demo_reset` deletes rows for every client where
> `is_demo = true`. It is meant to nightly-reset the three shared demo personas
> only. If a real client ever gets `is_demo = true`, this job will delete that
> client's work product on its next run — the blast radius is defined entirely
> by which rows carry that flag.

## 10. Deployment topology

```
Front end:  apps/dashboard  --(vercel deploy --prod)-->  Vercel
Back end:   apps/backend
              CI (.github/workflows/ci.yml, push to main):
                test-backend  (runs migrate + read-path deploy gate against a
                               throwaway pgvector service container)
                     |
                deploy-backend:
                  doppler run --project taxflow --config prd --
                    bash scripts/deploy_backend.sh
                      1. apply_migrations.sh against MIGRATION_DATABASE_URL
                         (Supabase session pooler, port 5432) — schema before code
                      2. ssh root@droplet: write /opt/taxflow/.env
                      3. rsync backend code to the droplet
                      4. docker compose build + up (sha-tagged image)
                      5. /health smoke test; roll back to previous tag on failure

Droplet:    Caddy (:80/:443, TLS) --> backend container (expose :8000)
Data:       Supabase (Postgres + pgvector + GoTrue),  Cloudflare R2
Secrets:    Doppler (taxflow / prd)
```

Migrations are tracked in a private ledger (`taxflow_internal.applied_migrations`)
with SHA-256 checksums; `apply_migrations.sh` is idempotent, serialized by a
Postgres session advisory lock, and applies each migration + records the ledger
row in a single transaction so a partial apply never persists.

## 11. Data stores at a glance

```
Postgres (Supabase) — relational + vector
  clients            firm roster, is_demo, subscription_status, voice_sample
  trials             per-client usage caps + counters
  queries            research Q&A history (answer, citations, trace, session_id)
  documents          advice memos + ATO responses (content_md; file regenerated)
  engagements        grouping of work under a client engagement
  firm_clients       searchable client names for the "who is this for?" picker
  annotations        threaded notes on documents/queries
  knowledge_chunks   global KB (pgvector embeddings, full-text, is_current)
  firm_knowledge     firm-uploaded KB (pgvector), scoped by client_id
  query_feedback     thumbs up/down + notes, cascades on query delete
  regulatory_alerts  output of the regulatory monitor
  notifications      in-app notifications
  taxflow_internal.applied_migrations   migration ledger (private schema)

Cloudflare R2 (S3 API) — generated DOCX/PDF binaries (on demand)
Supabase GoTrue        — auth: sessions, JWTs, demo magic-link login
```

## 12. Trust boundaries

- The **browser** never holds service credentials and never calls Postgres,
  Stripe, or an LLM directly. It talks only to Next.js (its own origin) and to
  GoTrue for the auth session.
- **Next.js server routes** hold the Supabase session and forward the user's JWT
  to the backend; they are the only browser-facing caller of the backend.
- The **backend** is the only component with service-role credentials
  (Postgres, R2, Stripe secret, LLM keys), injected at deploy time from Doppler
  into `/opt/taxflow/.env`. It verifies every JWT before doing work and enforces
  per-client trial limits.
- **Row scoping** is by `client_id`, derived from the verified JWT's email — a
  query, document, or firm-knowledge row is only ever read/written for the
  authenticated client.
```
