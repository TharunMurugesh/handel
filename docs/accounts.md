# Handel — External Accounts Register

| | |
|---|---|
| **Purpose** | P0 gate item: every external account exists and its free-tier limits are **verified on the provider's own console**. |
| **Rule** | **No secrets in this file.** Keys go in `.env` (local) or GitHub Actions secrets. |
| **Re-check** | Before P4 (gateway routing) and again in P9 (before the finale). |

"Expected limit" values come from third-party reports in [`03-architecture.md`](03-architecture.md) §7 and §11 and are **unverified**. Replace them with what the console shows, and fill in the date.

| Service | Used for | Expected limit (unverified) | Verified limit | Needs card? | Account holder (role) | Verified on |
|---|---|---|---|---|---|---|
| Telegram bot — staging | Staging bot | Bot API ≈ 1 msg/s per chat, ≈ 30/s overall | | No | | |
| Telegram bot — prod-demo | Main demo bot | Same | | No | | |
| Groq | Text extraction, intent, planner | ≈ 14,400 req/day, ≈ 30/min | | | | |
| Google Gemini API | Vision (quote photos, drawings) | Flash-Lite ≈ 500 req/day; Flash ≈ 20/day | | | | |
| OpenRouter | `:free` fallback models | Varies by model | | | | |
| Sarvam AI | STT, TTS, translate | ₹100 credit; STT ≈ ₹30/h; TTS ≈ ₹30/10k chars | | | | |
| Neon | Postgres (staging branch, prod-demo) | ≈ 1 GB per project | | | | |
| Cloudflare R2 | Media storage | Free tier, no egress fees | | | | |
| Oracle Cloud Always Free | ARM VM (api, worker, Caddy) | Always Free ARM shape; capacity varies by region | | Yes (verification) | | |
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
