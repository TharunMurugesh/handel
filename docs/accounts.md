# Handel — External Accounts Register

| | |
|---|---|
| **Purpose** | P0 gate item: every external account exists and its limits, credits and settings are **verified on the provider's own console**. |
| **Rule** | **No secrets in this file.** Keys go in `.env` (local) or GitHub Actions secrets. |
| **Re-check** | Before P4 (gateway routing) and again in P9 (before the finale). |

"Expected limit" values come from [`03-architecture.md`](03-architecture.md) v0.2 §7 and §11 (provider pages read 2026-11-20) and are **unverified for our account**. Replace them with what the console shows, and fill in the date.

| Service | Used for | Expected limit (unverified) | Verified limit | Needs card? | Account holder (role) | Verified on |
|---|---|---|---|---|---|---|
| Telegram bot — staging | Staging bot | Bot API ≈ 1 msg/s per chat, ≈ 30/s overall | | No | | |
| Telegram bot — prod-demo | Main demo bot | Same | | No | | |
| Claude API (Anthropic) | All LLM tasks: extraction, vision, intent, planner, call turns | Team credits; rate limits per the console's tier; check data retention settings | | | | |
| Sarvam AI | STT, TTS, translate; realtime STT/TTS for calls | Team credits. PAYG: STT ₹0.49/min, TTS `bulbul:v4-flash` ₹1/1k chars; 20 concurrent STT sockets, 60 TTS. **Set workspace data retention** (default is indefinite) | | | | |
| Vobiz | Phone calls: supplier RFQ calls, owner calls, decision calls | KYC (Aadhaar + PAN, or PAN + GST); a **regular** Indian number (not 140-series); trial numbers are outbound only; voice "from ₹0.42/min" (India rate to confirm); concurrency/CPS bought as capacity. **Ask compliance about supplier quote calls (spec A-18)** | | | | |
| Neon | Postgres (staging branch, prod-demo) | ≈ 1 GB per project | | | | |
| Cloudflare R2 | Media storage | Free tier, no egress fees | | | | |
| Oracle Cloud Always Free | ARM VM (api, worker, voice, Caddy), **Indian region** | Always Free ARM shape; capacity varies by region | | Yes (verification) | | |
| Sentry | Error tracking | Free developer plan | | | | |
| Grafana Cloud | Traces, metrics, logs | Free tier | | | | |
| Langfuse Cloud | LLM traces, eval scores | Free hobby tier | | | | |
| GitHub | Repo, Actions CI, container registry | Free for public repos; minutes cap for private | | No | | |

## Fallbacks if an account can't be created

| If this fails | Use instead (architecture §11.1) |
|---|---|
| Oracle VM | Render free web service + Telegram long polling, or a team laptop |
| Neon | Supabase free, or Postgres on the VM |
| Cloudflare R2 | Supabase Storage, or MinIO on the VM |
| Langfuse | `model_call` table only |
