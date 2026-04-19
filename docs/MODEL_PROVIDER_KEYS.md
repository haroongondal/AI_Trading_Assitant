# Model Provider API Keys Guide (Gemini 2.0 + Groq Focus)

Current rollout focus is:

- Google AI Studio (`Gemini 2.0 Flash`)
- Groq (free tier; `GPT-OSS 120B` (reasoning) preferred, then `Llama 3.3 70B Versatile`, with `Llama 3.1 8B Instant` fallback)

Set keys in `backend/.env`, then restart backend.

## Local hosted model (default)

- `OLLAMA_BASE_URL=http://127.0.0.1:11434`
- `OLLAMA_HOSTED_LLAMA31_MODEL=llama3.1`
- Start Ollama:
  - Linux systemd: `sudo systemctl start ollama`
  - Manual: `ollama serve`

## Google AI Studio (Gemini)

- Env var: `GOOGLE_AI_STUDIO_API_KEY`
- Required endpoint is already configured in code (OpenAI-compatible transport):
  - `https://generativelanguage.googleapis.com/v1beta/openai/`
- Full setup steps:
  1. Open [Google AI Studio](https://aistudio.google.com/app/apikey).
  2. Sign in with the Google account you want to use for API access.
  3. Click **Create API key**.
  4. Copy the key once (store in password manager/secret manager).
  5. Add to `backend/.env`:
     - `GOOGLE_AI_STUDIO_API_KEY=your_key_here`
  6. Restart backend (`make dev` or restart service/container).
- Notes:
  - If your organization enforces restrictions, ensure Generative AI API access is permitted.
  - Keep this key server-side only; never expose it to frontend env vars.
- Model wired: `Gemini 2.0 Flash` (`gemini-2.0-flash`)

## Groq models (GroqCloud)

Production chat models exposed in this app:

| UI id | Groq `model` id | Role |
|-------|-----------------|------|
| `groq-gpt-oss-120b` | `openai/gpt-oss-120b` | **Best default for finance + tools** — strong reasoning, portfolio/RAG/memory tools, good for numeric and multi-step analysis. |
| `groq-gpt-oss-20b` | `openai/gpt-oss-20b` | Faster/cheaper GPT-OSS; still tool-capable; use when latency matters more than maximum depth. |
| `groq-llama-3.3-70b` | `llama-3.3-70b-versatile` | Very fast general chat; good tools; weaker than 120B on long reasoning chains. |
| `groq-llama-3.1-8b` | `llama-3.1-8b-instant` | Fastest/cheapest; more tool-call failures on complex prompts. |

**Finance recommendation:** Keep the default selector on **`groq-gpt-oss-120b`** for this trading assistant (tools + quality). Use **`groq-gpt-oss-20b`** for a lighter GPT-OSS.

**Web search in-app:** The `search_web` tool uses **DuckDuckGo** only so it does not compete with your Groq chat quota (e.g. GPT-OSS 120B) on the same API key.

## Groq (free LLM calls)

- Env var: `GROQ_API_KEY`
- Required endpoint is already configured in code (OpenAI-compatible transport):
  - `https://api.groq.com/openai/v1`
- Full setup steps:
  1. Open [Groq Console](https://console.groq.com/keys).
  2. Sign in / create a free account.
  3. Create a new API key from the **API Keys** section.
  4. Copy and securely store the key (it begins with `gsk_...`).
  5. Add to `backend/.env`:
     - `GROQ_API_KEY=your_key_here`
  6. Restart backend (`make dev` or restart service/container).
- Notes:
  - Groq's free tier has generous per-minute / per-day rate limits suitable for development.
  - When a rate limit is hit, the chat SSE stream emits a `rate_limit` event and the
    frontend shows a warning toast.
  - Keep this key server-side only.
  - For GPT-OSS / reasoning models, backend sets `reasoning_format=hidden` in the request
    body so the chain-of-thought is not streamed to the UI (only the final answer is shown).
- Groq model order is controlled by `GROQ_MODEL_CANDIDATES`. Use **comma-separated** IDs (recommended) or a single JSON array; the backend tolerates stray text after a JSON array so `.env` mistakes do not crash startup.
  - `GROQ_MODEL_CANDIDATES=openai/gpt-oss-120b,llama-3.3-70b-versatile,llama-3.1-8b-instant`
  - `GROQ_MODEL_CANDIDATES=["openai/gpt-oss-120b","llama-3.3-70b-versatile","llama-3.1-8b-instant"]`
- If the first model is unavailable for your account, backend tries the next candidate automatically.

## Model visibility and fallback controls (important)

To expose only local + Google + Groq models and hide others from users:

```env
CHAT_MODEL_WHITELIST=local-llama31,groq-gpt-oss-120b,groq-gpt-oss-20b,groq-llama-3.3-70b,groq-llama-3.1-8b
CHAT_MODELS_SHOW_CONFIGURED_ONLY=true
CHAT_INCLUDE_LOCAL_FALLBACK=true
GROQ_MODEL_CANDIDATES=openai/gpt-oss-120b,llama-3.3-70b-versatile,llama-3.1-8b-instant
```

- `CHAT_MODEL_WHITELIST`: explicit list of model IDs allowed in UI/API model list.
- `CHAT_MODELS_SHOW_CONFIGURED_ONLY=true`:
  - only models with valid backend configuration are shown to users.
  - for Google/Groq, this means their API key must be present.
- Frontend default selection behavior:
  - prefers first available provider model (Groq GPT-OSS 120B first)
- Chat runtime behavior:
  - selected model only (no automatic fallback chain)

## Scheduler model fallback behavior

Scheduled analysis uses provider models only (not local fallback), prioritizing Groq models from `GROQ_MODEL_CANDIDATES`.

If a model is unavailable or fails at runtime, scheduler automatically tries the next one.

## Required dependency for third-party providers

Third-party providers use OpenAI-compatible transport in backend.
Install deps after pull/update:

```bash
cd backend
pip install -e .
```

If you see `ModuleNotFoundError: langchain_openai`, this step is missing.

## Temporary debug logs (for 401/404/429 investigation)

Backend now logs structured attempt diagnostics for chat and scheduler:

- `chat_model_attempt`, `chat_model_success`, `chat_model_failed`
- `runner_model_selected`, `runner_stream_chunk_error`, `runner_model_init_failed`
- `scheduler_model_attempt`, `scheduler_model_failed`, `scheduler_model_skip`

Common categories:

- `auth_error` (401/403, invalid key)
- `model_not_found` (404, unsupported model id)
- `quota_or_rate_limit` (429, quota exhausted)
- `local_backend_unreachable` (Ollama down)

These logs are temporary debugging aids and can be removed once provider setup is stable.

## Verify model availability (Gemini/Groq)

1. Start backend (`make dev`).
2. Check model list API:

```bash
curl http://localhost:8000/api/chat/models
```

3. Confirm you see only expected models.
4. In frontend, select a Groq model and run a test chat.

## Optional: stock & FX data for `get_quote`

For more reliable **PSX** / **NASDAQ** prices than web search alone, set `TWELVEDATA_API_KEY`, `FINNHUB_API_KEY`, and/or `ALPHA_VANTAGE_API_KEY` in `backend/.env`. See [MARKET_DATA_APIS.md](MARKET_DATA_APIS.md) for vendor overview and setup.

## Security recommendations

- Do not commit `.env`.
- Rotate keys if leaked.
- Prefer secret managers in production (AWS/GCP/Vercel/Render/etc).
- Keep keys in backend only (never `NEXT_PUBLIC_*`).
