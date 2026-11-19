# Handel — System Architecture

| | |
|---|---|
| **Problem statement** | Tech4Bharat 2026 · 4.1 · Agentic AI |
| **Version** | 0.1 |
| **Date** | 2026-11-19 |
| **Implements** | [`02-specification.md`](02-specification.md) v0.2.1 · [`01-requirements.md`](01-requirements.md) v0.1.3 |
| **Evidence** | [`00-desk-research.md`](00-desk-research.md) |
| **Constraint** | **₹0 running cost.** Only free tiers or free credits. Every paid option is listed separately as an upgrade path. |

---

## 1. Goals and constraints

**Architecture goals, in priority order:**
1. **Correct and safe actions.** No award, payment, quote, referral or data sharing without a person's approval. Prices and costs come only from deterministic rules. *(BD-01 to BD-04, AG-06, spec §11 guardrails)*
2. **Agentic and resilient.** Long-running cases with plans, timers, memory and recovery that survive restarts and network loss. *(AG-01 to AG-05, NF-06)*
3. **Works where users are.** Chat-first, voice-first, Indian languages, low-end phones, and a relay path for people who never join. *(NF-01 to NF-05, NF-10)*
4. **Measurable AI quality.** Every model call can be traced, evaluated and replaced. *(EV-T2, FD-08)*
5. **Free to run.** Zero recurring cost for the prototype and pilot. Upgrades don't require code changes.
6. **Credible path to scale.** Enterprise patterns sized for a 4-person team and a 5-week build.

**Constraints:**

| Constraint | Consequence |
|---|---|
| ₹0 budget | Free tiers with hard daily caps → **multi-provider LLM gateway with routing, caching and budgets** (§7) |
| Free LLM tiers may use inputs to improve their services | **PII redaction before any model call** (§10.3). This also follows DPDP purpose limitation. |
| Sarvam: ₹100 of credit (STT ≈ ₹30/hour, TTS ≈ ₹30 per 10k characters, from third-party reports; verify) | **Speech budget** with caching and selective text-to-speech (§7.4) |
| 4 students, ~5 weeks | **Modular monolith**, one language (Python), one database (Postgres), no Kubernetes |
| Telegram bots can't message first | Invite deep links forwarded by the owner, plus relay mode (spec §5.3) |
| Finale demo must not fail | A local stack that works without the internet beyond Telegram and model APIs, recorded fixtures, and a fallback video (§12.4) |

## 2. Architecture at a glance

**Style:** a **hexagonal modular monolith** with an **event-driven core**.

**Main mechanisms:**
- **Durable workflows:** case state machines, a timer table and a transactional outbox, all in Postgres.
- **Deterministic rules engine:** landed cost, ranking, bidding, costing, rate builder, pooling and referral.
- **LLM perception and language:** used only for extraction, understanding and message writing, never for arithmetic or authority.
- **A policy and approval gate** that every outbound action and money-related step must pass.

> **Why not let an LLM run free in a loop?**
> - Spec §11 forbids model-computed numbers and model-authorised actions.
> - Free tiers can't afford long loops.
>
> So Handel's "agent" is a **planner bound by a state machine**. Code defines which actions are legal in each state. The LLM picks among them and fills in the language. Policy checks every pick. This is still fully agentic by the brochure's definition (plans, acts, remembers, recovers, asks approval), and it can be audited.

### 2.1 System context

```mermaid
flowchart LR
    Owner([Unit owner<br/>voice/text/photo])
    Supplier([Suppliers & transporters])
    Buyer([Buyers<br/>via owner])
    Operator([JanAI Café operator])
    OtherUnit([Other Handel units])

    subgraph Handel
      H[Handel platform]
    end

    TG[[Telegram Bot API]]
    WA[[WhatsApp Cloud API<br/>R2, optional]]
    SARVAM[[Sarvam AI<br/>STT / TTS / translate]]
    LLM[[LLM providers<br/>free tiers]]
    PRICE[[Public price sources<br/>cited, hand-recorded]]

    Owner <--> TG
    Supplier <--> TG
    Supplier -. relay via owner .-> Owner
    Buyer -. forwarded by owner .-> Owner
    Operator <--> TG
    Operator <--> H
    TG <--> H
    WA <-.-> H
    H --> SARVAM
    H --> LLM
    PRICE -.-> H
    OtherUnit <--> H
```

### 2.2 Containers

```mermaid
flowchart TB
    subgraph Edge
      CADDY[Caddy reverse proxy<br/>auto-HTTPS, rate limit]
    end

    subgraph App["Handel app (one codebase, Python)"]
      API[API service<br/>FastAPI: webhooks, Mini App pages,<br/>operator console, health]
      WORKER[Worker service<br/>outbox dispatcher, perception jobs,<br/>timers, agent steps]
    end

    subgraph Data
      PG[(PostgreSQL<br/>state, events, outbox, timers,<br/>queue, audit, consent)]
      OBJ[(Object storage<br/>voice notes, photos, PDFs)]
    end

    subgraph External
      TG[[Telegram]]
      SARVAM[[Sarvam]]
      LLMs[[LLM gateway targets:<br/>Groq · Gemini · OpenRouter]]
    end

    subgraph Ops
      OTEL[OpenTelemetry → Grafana Cloud free]
      SENTRY[Sentry free]
      LANGFUSE[Langfuse free<br/>LLM traces & evals]
    end

    TG -->|webhook| CADDY --> API
    API --> PG
    API --> OBJ
    WORKER --> PG
    WORKER --> OBJ
    WORKER --> TG
    WORKER --> SARVAM
    WORKER --> LLMs
    API -. traces .-> OTEL
    WORKER -. traces .-> OTEL
    API -. errors .-> SENTRY
    WORKER -. errors .-> SENTRY
    WORKER -. LLM spans .-> LANGFUSE
```

**Two processes, one codebase:**
- The **API** receives and stores events quickly.
- The **worker** does everything slow or external.
- They communicate only through Postgres: events, the job queue and the outbox.

That gives **at-least-once processing with idempotent handlers** without a separate message broker.

## 3. Module structure (hexagonal)

```
handel/
├── domain/                 # pure Python: no I/O, no frameworks
│   ├── cases/              # state machines: purchase, enquiry, deal, pool, referral (spec §7)
│   ├── rules/              # landed cost, ranking, bidding, costing, rate builder, pool split, referral match (spec §8)
│   ├── policy/             # approval gate, bidding rules B2–B5, consent checks, limits
│   └── model/              # entities & value objects (spec §9), Money, Quantity, Weight
├── application/            # use cases & orchestration
│   ├── intake/             # M-02, M-11 intake
│   ├── sourcing/           # M-03, M-06, M-07
│   ├── costing/            # M-01 rate builder, M-11
│   ├── network/            # M-08, M-09, M-10, M-15
│   ├── agent/              # planner, tool registry, step runner (M-12)
│   ├── privacy/            # consent, data requests, redaction (M-13)
│   └── reporting/          # M-14
├── ports/                  # interfaces the application depends on
│   ├── channel.py          # send/receive, buttons, media
│   ├── speech.py           # stt(), tts()
│   ├── llm.py              # complete(), extract(schema), vision_extract(schema)
│   ├── storage.py          # put/get media
│   └── clock.py            # testable time
├── adapters/               # implementations of ports
│   ├── telegram/           # Bot API (webhook + long-poll mode)
│   ├── relay/              # relay drafts & forwarded-reply matching
│   ├── whatsapp/           # R2, behind a feature flag
│   ├── sarvam/             # STT, TTS, translate
│   ├── llm_groq/ llm_gemini/ llm_openrouter/   # LLM providers (paid adapters can be added)
│   ├── postgres/           # repositories, outbox, queue, timers
│   └── s3/                 # R2/S3-compatible object storage
├── interfaces/
│   ├── http/               # FastAPI routes: webhooks, Mini App, operator console
│   └── worker/             # job handlers, dispatcher, scheduler loop
└── evals/                  # offline evaluation harness for T-1..T-6
```

**Rules that keep this credible:**
- `domain/` imports nothing outside the standard library and Pydantic. This is enforced by an import-linter check in CI.
- Every external system is behind a **port**. Swapping Telegram for WhatsApp, Groq for another provider, or R2 for S3 is a new adapter, not a rewrite (NF-10, NFS-12).
- `domain/rules` has **100% branch coverage plus property-based tests** (Hypothesis). This is where money is calculated (Q-03).

## 4. Core runtime design

### 4.1 Event flow
1. **Inbound:** the Telegram webhook (or long poll) → API checks the secret token → writes an `inbound_event` row, de-duplicated on `(channel, update_id)` → returns `200` immediately.
2. **Perception job:** the worker claims the event (`SELECT … FOR UPDATE SKIP LOCKED`) → downloads media to object storage → runs speech-to-text if it's audio → **redacts PII** → runs LLM extraction against a strict JSON schema → stores the result with per-field confidence and source spans.
3. **Case step:** the agent step runner loads the case → the **state machine lists the legal actions** → the planner (rules first, LLM only when ambiguous) picks one → **the policy gate checks it** → domain changes and new outbox messages are written **in one transaction**.
4. **Outbound:** the dispatcher sends outbox rows through the right channel adapter. It applies Telegram's limits (≈1 message/s per chat, ≈30/s overall), retries with backoff, and marks rows `sent` or `failed`.
5. **Timers:** each `timer` row (`due_at`, `case_id`, `kind`) is claimed by the scheduler loop when due. It produces a case event (e.g. `T1_REMINDER_DUE`), which goes back to step 3.

This gives **durable, restartable, idempotent** behaviour (NF-06, NFS-05):
- A crash at any point leaves either a committed state or a retryable job.
- No message is sent twice, because each one has an idempotency key.

### 4.2 Sequence: purchase request to award

```mermaid
sequenceDiagram
    autonumber
    actor O as Owner
    participant TG as Telegram
    participant API
    participant W as Worker
    participant SV as Sarvam
    participant L as LLM gateway
    participant DB as Postgres
    actor S as Suppliers

    O->>TG: voice note "2 ton MS sheet 2mm…"
    TG->>API: webhook update
    API->>DB: inbound_event (dedup)
    W->>DB: claim event
    W->>SV: STT (lang auto / mixed speech)
    W->>L: extract Need (redacted text, JSON schema)
    W->>DB: Need draft + confidence
    W->>DB: outbox: MSG-08 confirm (voice + text, buttons)
    W->>TG: send confirm
    O->>TG: [Yes]
    TG->>API: callback
    W->>DB: case → Sourcing; outbox: MSG-02 ×N; timers T1/T2/deadline
    W->>TG: RFQs to joined suppliers
    W->>TG: MSG-02R relay drafts to owner (non-joined)
    S-->>TG: replies (text / voice / photo)
    W->>L: quote extraction (vision for photos)
    W->>DB: Quote + LandedCost (rules engine)
    Note over W,DB: deadline timer fires → rounds (compete-mode only, RULE-B*)
    W->>DB: shortlist (rules engine ranking)
    W->>TG: MSG-09 shortlist to owner (voice summary)
    O->>TG: [Approve]
    W->>DB: approval record (policy gate passes)
    W->>TG: MSG-06 award (exact terms) to supplier
    S-->>TG: [Confirm]
    W->>DB: case → Awarded; audit events
```

### 4.3 The agent: a planner bound by a state machine

| Part | Responsibility | Implemented as |
|---|---|---|
| **State machine** | Legal states, transitions and **allowed actions** per state | Declarative tables in `domain/cases/*` |
| **Plan** | Ordered next steps with due times, visible to the owner (AG-02) | `case.plan` JSON, rebuilt after every event |
| **Tool registry** | Actions the planner may take: `send_rfq`, `ask_clarification`, `request_freight`, `run_round`, `shortlist`, `request_approval`, `propose_referral`, … | Typed Python functions with JSON schemas |
| **Planner** | Chooses the next action | **Deterministic rules first** (most transitions are obvious). An **LLM call** only for open questions, e.g. "is this a reply to the RFQ or a new need?" or "which clarification to ask". It can only choose from the allowed list. |
| **Policy gate** | Validates the action against BD-01 to BD-04, RULE-B2 to RULE-B5, consent, limits and the approval requirement | `domain/policy`. Rejected actions are logged and escalated to the owner. |
| **Memory** | Case timeline, plus long-term memory per unit (supplier stats, price history, preferences) | Postgres tables. Retrieval by plain SQL. **No vector database is needed** at this scale. |
| **Recovery** | Spec M-12 table | Timer kinds + failure events mapped to recovery actions |

**How it is used, depending on the LLM tier:**
- **Free tier:** the planner runs mostly on deterministic rules. LLM calls happen only at perception points and genuinely ambiguous decisions, which saves the scarce free quota.
- **Paid upgrade:** the same tool registry can be given to a stronger tool-calling model (§7.5) without changing domain code.

## 5. Data architecture

**Store:** PostgreSQL 16, one database with schemas per module (`core`, `cases`, `network`, `privacy`, `ops`).

| Table group | Key tables | Notes |
|---|---|---|
| Identity and tenancy | `unit`, `person`, `channel_identity`, `supplier`, `transporter` | Every business row carries `unit_id`. **Row-level security** policies isolate units (multi-tenant ready). |
| Profiles | `capability`, `rate_card`, `material` | `rate_card.derived` is stored with its inputs for explanations (NF-09) |
| Cases | `need`, `purchase_case`, `quote`, `freight_quote`, `landed_cost`, `enquiry`, `cost_sheet`, `deal`, `pool`, `referral` | State + `version` (optimistic locking) |
| Workflow infrastructure | `inbound_event`, `job` (queue), `outbox`, `timer`, `case_event` | `job` and `outbox` use `SKIP LOCKED`. `case_event` is the case timeline. |
| Governance | `approval`, `consent`, `data_request`, `audit_event` | `audit_event` is **append-only with a hash chain** (each row stores the hash of the previous one), so tampering is evident (DT-04) |
| Market data | `price_point` | `source`, `date` and `is_mock` are always set (DT-03) |
| AI telemetry | `model_call` | provider, model, prompt version, latency, tokens, cost (₹0 on free tiers), result reference, eval label |

**Media:** S3-compatible object storage. Keys are random UUIDs. The database stores the key, SHA-256 hash, MIME type and retention date.

**Retention and erasure (DT-05):**
- Raw media is deleted after **90 days** by default.
- Structured data is kept while the account is active.
- On a `DELETE` request, the person's rows are deleted or nulled, and their price points are **anonymised** (supplier link removed) so market history survives without personal data (AT-12).

**Encryption:**
- TLS in transit.
- Managed-database encryption at rest.
- Phone numbers stored encrypted at **column level** (`pgcrypto`, key in the environment), with a keyed hash for lookups.

## 6. Channel layer (M-16)

| Adapter | Mode | Details |
|---|---|---|
| **Telegram** (R0) | **Webhook** in the cloud (with the `secret_token` header checked). **Long polling** for local demo and fallback (no public URL needed). | Voice (OGG/Opus), photos, documents, inline keyboards, deep links `t.me/<bot>?start=<token>` (payload ≤ 64 bytes, a signed short code), Mini App for the bid and case pages |
| **Relay** (R0) | Inside Telegram, with the owner | Relay drafts carry a short **case tag** (e.g. `#H7K2`). When the owner forwards a reply back, it's matched by tag, then by the forwarded sender's name and number, then by asking the owner. |
| **WhatsApp Cloud API** (R2, flag off) | Webhook | Utility templates for MSG-02/03/06; the 24-hour window is tracked per contact; falls back to relay. Free to build against with a test number, but only a few verified recipients. |

**Mini App pages** (bid page, case page):
- Server-rendered HTML with **HTMX**, no single-page-app framework. Under 200 KB (NFS-04).
- Opened from Telegram with signed `initData`, which is verified on the server. Outside Telegram, an **HMAC-signed, expiring token** is used instead.

## 7. AI architecture

### 7.1 Model gateway

All model calls go through one gateway in `adapters/llm_*`, behind `ports/llm.py`. It provides:
- **Task routing:** each task (`extract_need`, `extract_quote_text`, `extract_quote_image`, `extract_drawing`, `classify_intent`, `write_message`, `explain`) has an ordered list of providers.
- **Structured output:** every extraction uses a Pydantic schema and is validated. On a validation failure, Handel retries once with the error, then falls back to the next provider, then asks a person (spec §11 fallbacks).
- **Budgets and quotas:** per-provider counters for requests per minute and per day, kept in Postgres. When a provider is near its cap, the gateway routes to the next one. Each task has a priority (owner-facing first).
- **Cache:** responses are cached by a hash of the input and the prompt version, which avoids paying twice for the same extraction (common with forwarded duplicates).
- **Observability:** every call is logged to `model_call` and Langfuse, with its prompt version.
- **Redaction:** PII is redacted before the call and restored after (§10.3).

### 7.2 Provider plan (free tiers)

Free-tier limits change often and sources disagree (see sources). **Check each console before the build, and again before the finale.**

| Task | Primary (free) | Fallback (free) | Notes |
|---|---|---|---|
| Text extraction, intent and planner decisions (`extract_*_text`, `classify_intent`, planner) | **Groq** free tier: an open-weight instruction model with JSON / tool calling | Gemini **Flash-Lite** free tier, then OpenRouter `:free` models | Groq's free tier is reported at ~14,400 requests/day and ~30/min (third-party reports). Choose the exact model with the eval harness (§7.6). |
| Image extraction (quote photos, drawings, bills: AI-04, AI-05, AI-09) | **Gemini Flash-Lite** (vision) free tier | A Groq vision-capable open model, if available, then **ask the sender for a voice note** | Gemini free quotas reported in late 2026: Flash ≈ 20 requests/day, Flash-Lite ≈ 500/day. **Images are the scarcest resource**, so resize and compress before sending, and cache the result. |
| Message writing in Indian languages (AI-07) | **Templates (spec §10) + Sarvam Translate** | The LLM writes, then Sarvam translates | Templates first: deterministic, safe (RULE-B2 to RULE-B4) and costs no LLM quota |
| Explanations (AI-08) | Generated from rules-engine traces (no LLM) | LLM rephrasing | Explanations come from the calculation trace, so they're always correct |

### 7.3 Speech

| Function | Primary | Fallback |
|---|---|---|
| Speech-to-text (AI-01) | **Sarvam** STT (Saaras line; 22 languages + English; mixed speech) | Self-hosted **AI4Bharat IndicConformer** (open model, CPU) on the same VM, or ask for text |
| Text-to-speech (AI-02) | **Sarvam** TTS | Text only (spec AI-02 fallback). Pre-rendered audio for fixed template phrases. |
| Translation | **Sarvam** Translate | The LLM gateway |
| Government alternative | **Bhashini** APIs (check access terms and whether they're free) | — |

### 7.4 Speech budget (₹100 Sarvam credit)

Rates are from third-party reports (§7.3 sources). **Verify on Sarvam's pricing page.**

| Use | Assumption | Estimated cost |
|---|---|---|
| Speech-to-text for owner and supplier voice notes | 150 notes × 15 s ≈ 38 min at ₹30/hour | ≈ ₹19 |
| Speech-to-text for the T-2 eval (30 notes × 2 runs) | ≈ 15 min | ≈ ₹8 |
| Text-to-speech for decision prompts only (MSG-08, MSG-09, MSG-10) | 60 prompts × 250 characters = 15k characters at ₹30 per 10k | ≈ ₹45 |
| Translation | ~20k characters | ≈ ₹20–40 (rates vary by report) |
| **Total** | | **≈ ₹90–110: tight** |

**Controls:**
- **Cache all TTS output.** Pre-render fixed phrases once.
- Text-to-speech **only at decision points** (NFS-03).
- **CI and development use recorded fixtures**, never live APIs (§12.2).
- A spend counter in `model_call` **turns off TTS when spend reaches ₹80**, keeping STT for the demo.
- **Extra credits, legitimately:** ask the organisers about the sponsor credits mentioned in third-party listings; apply to Sarvam's startup programme. **Don't create duplicate accounts to multiply free credits.** That usually breaks terms of service and would hurt credibility.

### 7.5 Paid upgrade path (not used in the prototype)

The gateway lets a stronger provider be added by configuration, without code changes. For production, a paid tool-calling model would replace the free planner and vision routes. Examples:
- Anthropic's Claude via the official `anthropic` SDK: e.g. `claude-opus-5-5` for planning, `claude-haiku-5-5` for high-volume extraction.
- Equivalent paid tiers from other providers.

**Choose using the same eval harness, measuring cost per completed case.** Nothing in the domain or policy layers changes.

### 7.6 Evaluation harness (EV-T2, FD-08)
- `evals/` runs every AI task against T-1 to T-6, using **ground truth written in advance**.
- **Metrics:**
  - field-level accuracy, split by format (Q-01)
  - need accuracy (Q-02)
  - Q-04 to Q-05 on team-made sets
  - recovery coverage (Q-08)
- **Runs:**
  - **On demand**, and before any prompt or model change. Results are stored as `evals/results/<date>-<task>-<model>.json`.
  - **In CI** on a tiny smoke subset only, to stay within free quotas.
- **Prompt versions** are files in the repo (`prompts/<task>/vN.md`). Every model call records the version, so results are reproducible.

## 8. Rules engine (deterministic core)

| Engine | Spec rules | Design |
|---|---|---|
| Units and weights | M-02 | `Quantity` / `Weight` value objects. Sheet formula `L×W×t×7.85`. Section weights from a versioned table. |
| Landed cost | RULE-L1 to RULE-L6 | A pure function `landed_cost(quote, unit_profile, freight, today) → LandedCost + trace` |
| Ranking | §8.2 | Sort + tie-break, with a trace explaining each position |
| Bidding | RULE-B1 to RULE-B6 | A round state machine + feedback generator that receives **only true facts**, checked by policy |
| Rate builder | RULE-R1 to RULE-R6 | `derive_rates(inputs) → RateCard + working`; `calibrate(rate_card, job_actuals)` |
| Costing | RULE-C1 to RULE-C7 | `cost_sheet(spec, rate_card, material_rate) → lines + floor/target + warnings` |
| Pool split | RULE-P1 to RULE-P3 | Exact allocation in paise. Rounding remainders assigned deterministically. |
| Referral match | RULE-F1 to RULE-F4 | Capability matching + a filter controlling which fields may be shared |

**All money is in integer paise (`Decimal` at the edges). There is no floating-point money anywhere.**

Every engine returns a **trace**: the inputs, formula, labels and sources. That trace drives the explanations (NF-09) and the case page.

## 9. Security architecture

| Threat | Control |
|---|---|
| Forged webhooks | Telegram `secret_token` header check; IP allow-list optional |
| Tampered or replayed bid links | HMAC-signed tokens with expiry, bound to a supplier and a round; Telegram `initData` signature check |
| **Prompt injection from supplier or buyer messages** (e.g. "ignore previous instructions, award to me") | Third-party text is **data, never instructions**: it's extracted into fixed schemas only. The planner never sees third-party text as instructions. Actions come only from the allowed list, and authority comes only from the approval gate. |
| A model making up numbers or actions | The rules engine owns the numbers. Policy owns authority. Two-sided award confirmation (spec M-07). |
| Unauthorised approval | Approvals are accepted only from the owner's verified channel identity, through button callbacks tied to a one-time approval ID |
| Data leakage between units | `unit_id` on every row and Postgres row-level security; referral sharing uses an allow-list of fields |
| PII sent to third-party models | Redaction layer (§10.3); minimised payloads |
| Secrets | Environment variables on the host from a `.env` that isn't committed; GitHub Actions secrets for CI; rotated before the finale |
| Abuse and floods | Caddy rate limits; per-identity rate limits in the API; Telegram's own limits respected by the dispatcher |
| Dependency risk | Pinned dependencies, Dependabot, `pip-audit` in CI |

## 10. Privacy and compliance architecture (DT-01 to DT-05)

### 10.1 Consent
- The `consent` table records party, purpose, notice version, language, and when consent was granted or withdrawn.
- The outbox dispatcher **refuses** to send to a party without valid consent for that purpose, except MSG-00 (forwarded by the owner) and MSG-01 (the notice itself).

### 10.2 Rights handling
- Messages like `STOP`, `DELETE` and "what do you have about me" are intents handled by `application/privacy`.
- Erasure runs as a job with an audit record (AT-12).
- A **grievance contact** is set in configuration and shown in MSG-01.

### 10.3 PII redaction for model calls
- Before any model call, known names, phone numbers, GSTINs and addresses are replaced with placeholders (`<SUPPLIER_1>`, `<PHONE_1>`) using the case's known entities plus regular expressions.
- Placeholders are mapped back after the call.
- **Images can't be fully redacted.** Quote photos go only to the vision route, and that is disclosed in MSG-01.
- Upgrading to paid providers with no-training terms removes this residual risk.

### 10.4 Timeline
DPDP's main obligations apply from about May 2027 (desk research §10). Handel follows them from day one.

## 11. Deployment architecture (₹0)

### 11.1 Target (free tiers)

```mermaid
flowchart LR
    subgraph OCI["Oracle Cloud Always Free (ARM VM)"]
      CADDY[Caddy<br/>HTTPS via Let's Encrypt]
      API[api container]
      WORKER[worker container]
      STT[IndicConformer<br/>fallback STT, optional]
    end
    NEON[(Neon Postgres free)]
    R2[(Cloudflare R2 free)]
    DNS[Free subdomain<br/>e.g. DuckDNS]
    GRAF[Grafana Cloud free]
    SEN[Sentry free]
    LF[Langfuse Cloud free]
    GH[GitHub Actions<br/>CI/CD]

    DNS --> CADDY --> API
    API --> NEON
    WORKER --> NEON
    API --> R2
    WORKER --> R2
    API -.-> GRAF
    WORKER -.-> GRAF
    WORKER -.-> LF
    API -.-> SEN
    GH -->|ssh deploy / image pull| OCI
```

| Component | Free option chosen | Why | Fallback |
|---|---|---|---|
| Compute | **Oracle Cloud Always Free ARM VM** (Docker Compose) | Always on, no sleeping, enough RAM for the optional local STT model. *(Needs a card for verification; ARM capacity varies by region; check the current terms.)* | **Render** free web service (750 h/month, but sleeps after 15 min idle, so webhooks see cold starts) + worker in the same process; or the team laptop |
| Database | **Neon** free Postgres (≈1 GB per project) | Managed Postgres, branching for test databases | Supabase free (500 MB; pauses when inactive), or Postgres on the VM |
| Object storage | **Cloudflare R2** free tier | S3-compatible, generous free storage, no egress fees *(check current limits)* | Supabase Storage free, or MinIO on the VM |
| HTTPS and domain | Free subdomain + **Caddy** automatic Let's Encrypt | Needed for the Telegram webhook and Mini App | Telegram **long polling** (no public URL) + a Cloudflare quick tunnel for the Mini App |
| CI/CD | **GitHub Actions** | Lint, type-check, tests, smoke evals, image build, deploy | — |
| Monitoring | **Grafana Cloud** free (OpenTelemetry), **Sentry** free | Traces, metrics, logs, errors | Logs only |
| LLM tracing | **Langfuse** Cloud free | Prompt versions, traces, eval scores | `model_call` table |

### 11.2 Environments
- **local:** Docker Compose with Postgres and MinIO, Telegram long polling, model calls using recorded fixtures by default.
- **staging:** a Neon branch + a second Telegram bot.
- **prod-demo:** the main bot, Neon main branch, R2.

**Database migrations:** Alembic, run on deploy. Each migration is reversible.

### 11.3 Capacity and scale path
- **Load estimate:** each unit runs about 20 purchases and 10 enquiries a month, at roughly 30 messages each. That's about **900 messages per unit per month**. 1,000 units ≈ 0.9M messages/month ≈ **0.35 messages/s on average**, which is trivial for one VM and Postgres.
- **The bottleneck is model quota, not compute.** Handled by routing and caching on free tiers, and by paid tiers at scale.

**Growth steps, without redesign:**
1. Split the worker into queue-specific workers (perception, dispatch, timers).
2. Move the queue from Postgres to a dedicated broker only if contention appears.
3. Add read replicas for reporting.
4. Partition by `unit_id`, then deploy per region or cluster.

## 12. Quality engineering

### 12.1 Testing pyramid

| Layer | Tooling | Target |
|---|---|---|
| Rules engines | `pytest` + **Hypothesis** property tests (e.g. landed cost never negative; ranking is stable; pool shares add up exactly) | 100% branch coverage |
| State machines and policy | Table-driven tests for every transition and every forbidden action | All transitions and guards |
| Application | Use-case tests with fake ports (in-memory channel, recorded LLM and STT fixtures) | AT-01 to AT-16 as automated scenarios |
| Adapters | Contract tests against recorded API responses | Telegram, Sarvam, LLM providers |
| AI quality | `evals/` harness (§7.6) | Q-01 to Q-08 |
| End to end | A scripted demo run on staging with 3–4 team phones as suppliers | Before each release |

### 12.2 CI pipeline (GitHub Actions)
1. **Static checks:** `ruff`, `mypy --strict` on `domain/` and `application/`, import-linter (domain stays pure).
2. **Tests:** `pytest` with recorded fixtures. **No live API calls, so no quota is spent.**
3. **Smoke eval:** 5 items per task against the live free tier. Manual trigger only.
4. **Security:** `pip-audit`.
5. **Build and deploy:** build ARM and AMD images, push to GitHub Container Registry, deploy over SSH with `docker compose pull && up -d`, then run migrations.

### 12.3 Observability
- **Traces:** an OpenTelemetry span per inbound event → job → model call → outbound message, with `case_id` as an attribute.
- **Dashboards** (Grafana):
  - cases by state
  - time to shortlist
  - outbox lag
  - model calls by provider, plus quota headroom
  - Sarvam spend counter
  - error rate
- **Alerts:** outbox stuck for more than 5 minutes; provider quota above 80%; Sarvam spend above ₹80.

### 12.4 Making the finale demo reliable (NFS-13)
- **Primary:** prod-demo in the cloud.
- **Fallback A:** the same stack on a team laptop over a mobile hotspot, using long polling (no webhook or DNS needed).
- **Fallback B:** **fixture mode**, where pre-recorded STT and LLM results are replayed for the demo script, so a free-tier quota running out on stage can't break the demo. This is disclosed as "replay mode" if used.
- **Fallback C:** a recorded video of the full flow.
- Recovery scenarios (AT-07, AT-08) can be triggered from an operator command, e.g. `/simulate supplier_silent`.

## 13. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Language and runtime | **Python 3.12** | Best ecosystem for AI, speech and data. One language across the team. |
| Web framework | **FastAPI** + Uvicorn | Async, typed, fast to build. Webhooks and Mini App in one service. |
| Validation and schemas | **Pydantic v2** | One schema serves domain models, LLM structured output and APIs |
| Database access | **SQLAlchemy 2** (async) + **Alembic** | Mature; supports row-level security and `SKIP LOCKED` patterns |
| Queue, outbox and timers | **Postgres tables** + a small in-house claimer (or a Postgres queue library) | No extra infrastructure; jobs are committed in the same transaction as state changes |
| Telegram | **aiogram 3** (or python-telegram-bot) | Async, supports webhooks and long polling, inline keyboards, Mini Apps |
| Pages | **Jinja2 + HTMX** | Tiny pages for low-end phones; no build step |
| Model clients | Official SDKs or HTTP clients per provider, inside gateway adapters | Isolated behind `ports/llm.py` |
| Tests | pytest, Hypothesis, respx (HTTP mocking) | Deterministic, fast |
| Quality tools | ruff, mypy, import-linter, pip-audit | CI gates |
| Packaging | Docker (multi-arch), Docker Compose | Same everywhere: laptop, VM, CI |

## 14. Architecture decision records (summary)

| ADR | Decision | Status |
|---|---|---|
| ADR-001 | Hexagonal modular monolith (API + worker) instead of microservices | Accepted: team size and timeline; seams are ready for splitting later |
| ADR-002 | Deterministic rules own numbers; policy owns authority; LLM limited to perception and language | Accepted: spec §11, credibility, free-tier economics |
| ADR-003 | Postgres as the single store for state, queue, outbox and timers | Accepted: transactional consistency, ₹0, simple to run |
| ADR-004 | Planner bound by a state machine instead of an open agent loop | Accepted: safety, auditability, quota; the path to a paid tool-calling model stays open (§7.5) |
| ADR-005 | Multi-provider LLM gateway with quotas, caching and fallback | Accepted: free tiers are small and change without notice |
| ADR-006 | Sarvam for speech and translation; IndicConformer as self-hosted fallback | Accepted: Indian-language quality; ₹100 credit managed by a budget |
| ADR-007 | Telegram + relay first; WhatsApp adapter behind a flag (R2) | Accepted: desk research §8 |
| ADR-008 | PII redaction before model calls; images disclosed | Accepted: DPDP purpose limitation; free-tier data terms |
| ADR-009 | Oracle Always Free VM + Neon + R2 | Accepted, with fallbacks (§11.1) |
| ADR-010 | Hash-chained, append-only audit log | Accepted: makes tampering with awards and approvals evident |

## 15. Requirements traceability

| Requirement / spec item | Architecture element |
|---|---|
| AG-01 to AG-05 (agentic) | §4.1 event flow, §4.3 planner, durable timers, recovery mapping |
| AG-06, BD-01 to BD-04 | §4.3 policy gate, approval records, §9 approval authenticity |
| AG-07 | Tool registry actions (send, request, round, refer) |
| FR-BUY-01 to FR-BUY-14 | `application/sourcing`, rules engines §8, channel layer §6 |
| FR-QUO-01 to FR-QUO-08 | `application/costing`, rate builder and costing engines |
| FR-MKT-01 to FR-MKT-03 | `application/network` (referral), enquiry intake, reporting |
| FR-POOL-01, FR-POOL-02 | Pool split engine; approval per member |
| NF-01 to NF-04 | Sarvam STT/TTS, template messaging, buttons ≤ 4 |
| NF-05, NF-10 | Telegram/relay/WhatsApp adapters behind `ports/channel.py`; Mini App < 200 KB |
| NF-06 | Postgres outbox, queue, timers; idempotent handlers |
| NF-07 | Operator console and operator mode (`interfaces/http`) |
| NF-09 | Rules-engine traces → explanations |
| DT-01 to DT-05 | §10 privacy architecture; consent-gated dispatcher; hash-chained audit |
| HC-04, NFS-13 | §12.4 demo reliability |
| HC-05 | No scraping; cited price points (`price_point.source`) |
| HC-06, DT-03 | `is_mock` flags; "Prototype / MOCK / Demo unit / Replay mode" labels |
| EV-T1 | This document |
| EV-T2, FD-08 | §7.6 eval harness, `model_call` telemetry, Langfuse |

## 16. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Free LLM quotas shrink or a provider removes its free tier | High | High | Multi-provider gateway, caching, rules-first planner, fixture/replay mode for the demo |
| Sarvam credit runs out | Medium | Medium | Budget controls (§7.4), cached TTS, IndicConformer fallback, text fallback |
| Handwritten Indian-language quotes read poorly | High | Medium | Per-field confidence → confirm with the sender; ask for a voice note; report accuracy honestly per format |
| Oracle ARM capacity unavailable | Medium | Medium | Render free + long polling, or laptop hosting |
| Telegram adoption by real suppliers | Medium | Medium | Relay mode; WhatsApp adapter in R2 |
| Scope overrun | High | High | Release cut order (spec §16); rules engine and Buy loop first |

## 17. Build order (maps to spec §16)

1. **Week 1 (R0, to 1 Dec):**
   - repo scaffold, CI, Docker Compose
   - domain model and **rules engines with property tests**
   - Postgres outbox, queue and timers
   - Telegram adapter (long polling), relay
   - Buy loop with typed text only
2. **Week 2:**
   - Sarvam STT and TTS
   - LLM gateway (Groq + Gemini) with schemas, redaction, cache and quotas
   - photo quote extraction
   - bidding rounds and relationship mode
   - approval gate, two-sided award
3. **Week 3 (R1, ~10 Dec):**
   - rate builder, costing, loss warnings
   - basic referral
   - DPDP features
   - operator mode
   - eval harness on T-1 to T-6
   - cloud deploy
4. **Week 4 (R2, to 20 Dec):**
   - deals, pools, benchmarks, freight requests
   - second language
   - WhatsApp adapter (if verified)
   - dashboards, demo hardening, replay mode
5. **20–27 Dec:** freeze, rehearse, fallback video.

---

### Sources for free-tier and platform facts
Third-party reports, checked 2026-11-19. **Re-check on each provider's console before relying on them.**
- Gemini free-tier limits: [imisofts](https://imisofts.com/blog/gemini-api-free-tier-limits/), [AIFreeAPI](https://www.aifreeapi.com/en/posts/google-gemini-api-free-tier), [TokenMix](https://tokenmix.ai/blog/gemini-api-free-tier-limits)
- Groq and OpenRouter free tiers: [OpenRouter blog](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/), [CostBench Groq](https://costbench.com/software/llm-api-providers/groq/free-plan/), [Requesty](https://www.requesty.ai/blog/openrouter-free-models)
- Sarvam credits and pricing: [Sarvam docs: pricing](https://docs.sarvam.ai/api/getting-started/pricing), [Sarvam docs: rate limits](https://docs.sarvam.ai/api-reference-docs/ratelimits), [smallest.ai](https://smallest.ai/blog/sarvam-ai-speech-to-text-pricing)
- Hosting and databases: [SnapDeploy comparison](https://snapdeploy.dev/blog/free-cloud-deployment-platforms-2026-comparison), [AgentDeals DB comparison](https://agentdeals.dev/database-free-tier-comparison-2026), [Neon vs Supabase (DEV)](https://dev.to/devopsdaily/neon-vs-supabase-free-tiers-we-benchmarked-both-so-you-dont-have-to-hic)
- Telegram limits: [Telegram Bot FAQ](https://core.telegram.org/bots/faq), [community limits](https://limits.tginfo.me)
