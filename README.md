# AI Trading Assistant – Backend

FastAPI backend: local Ollama LLM with RAG, memory, web search, and portfolio
tools; streaming chat; scheduled news + portfolio analysis and notifications.

## Stack

Python 3.11+, FastAPI, LangChain, Ollama, ChromaDB, SQLite, APScheduler.

## Quick start

**One-time setup:**

```bash
cd backend
cp .env.example .env   # edit if needed
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
make setup                 # pip install -e . + mkdir data (or: pip install -e . && mkdir -p data)
ollama pull nomic-embed-text   # required for RAG/news ingest (embeddings)
```

**Start the server (from `backend/`):**

```bash
make dev
```

- **Important:** `uvicorn` is only installed in the venv. Use `make dev` (Linux/macOS) or run `source .venv/bin/activate` then `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`. On Windows without Make: activate the venv and run `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` (or use `.\\.venv\\Scripts\\uvicorn.exe ...`).

- API: http://localhost:8000
- Docs: http://localhost:8000/docs

**Project and run commands:**

| Role            | In Node/frontend | In Python/backend        |
| --------------- | -----------------| ------------------------ |
| Project + deps  | `package.json`   | **`pyproject.toml`** (PEP 621) |
| Run scripts     | `npm run dev`    | **`Makefile`** (`make dev`, `make setup`) |

- **pyproject.toml** – name, version, description, `dependencies[]`. Install: `pip install -e .`
- **Makefile** (Linux/macOS): `make dev` | `make start` | `make install` | `make setup`. On Windows without Make, activate the venv and run uvicorn directly.

## SQLite (local)

The app uses **SQLite** with the async driver `aiosqlite`. No separate DB server
is needed.

- **Config**: In `.env`,
  `DATABASE_URL=sqlite+aiosqlite:///./data/trading_assistant.db`. The file is
  created at `backend/data/trading_assistant.db` (path is resolved from the
  backend root).
- **Tables**: Created automatically on first run when the API starts (`init_db`
  in lifespan).
- **CLI (optional)**: To inspect the DB locally, install the SQLite3 CLI and
  open the file:

  ```bash
  # Install (Ubuntu/Debian)
  sudo apt install sqlite3

  # Open the DB (from repo root or backend/)
  sqlite3 backend/data/trading_assistant.db
  # Then: .tables   .schema users   .quit
  ```

See [docs/SQLITE.md](docs/SQLITE.md) for more.

## Env vars

See `.env.example`. Main: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`,
`OLLAMA_EMBEDDING_MODEL`, `DATABASE_URL`, `CHROMA_PERSIST_DIR`, `RAG_TOP_K`,
`DEFAULT_USER_ID` (fallback when no JWT session), `OLLAMA_HOSTED_LLAMA31_MODEL`.
For third-party model selector options, also set API keys as needed:
`GOOGLE_AI_STUDIO_API_KEY`, `GROQ_API_KEY`, `HUGGINGFACE_API_KEY`,
`OPENROUTER_API_KEY`, `GITHUB_MODELS_API_KEY`, `CEREBRAS_API_KEY`.
**Google OAuth (optional):** set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, and `AUTH_JWT_SECRET` together (see `.env.example`).
Optional: `GOOGLE_OAUTH_*` URLs, `GOOGLE_OAUTH_SCOPES`, `AUTH_JWT_ALGORITHM`,
cookie names (`AUTH_ACCESS_COOKIE_NAME`, `OAUTH_STATE_COOKIE_NAME`),
`AUTH_COOKIE_SAMESITE`, `AUTH_COOKIE_SECURE`, `AUTH_ERROR_REDIRECT_QUERY`.
Portfolio, chat agent tools, notifications, and scheduled analysis are scoped per
authenticated user; the scheduler runs analysis once per user in the database.
Scheduler: `SCHEDULER_ENABLED` (default `false`) and `SCHEDULER_CRON` (default `"0 9,21 * * *"`).
Agent: `AGENT_MAX_TURNS`, `OLLAMA_TEMPERATURE`, `OLLAMA_NUM_CTX`.
WhatsApp (optional): `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_RECIPIENT_PHONE`, `WHATSAPP_TEMPLATE_NAME`.
Email (optional): `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_SMTP_STARTTLS`, `EMAIL_SMTP_USERNAME`, `EMAIL_SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_DEFAULT_TO`.

## Chat model selector

- Frontend fetches available chat models from `GET /api/chat/models`.
- Chat stream accepts optional `model_id` in `POST /api/chat/stream`.
- Default selected model is local hosted `Llama 3.1` (`local-llama31`) tagged as `very slow`.
- Provider-backed models are automatically disabled in UI unless required key/dependency is present.
- Some providers are marked as `limited tools` and run in no-tool mode for stability.

See [docs/MODEL_PROVIDER_KEYS.md](docs/MODEL_PROVIDER_KEYS.md) for token setup.

## Troubleshooting

- If backend fails on startup with `ModuleNotFoundError: langchain_openai`,
  run `pip install -e .` in `backend/` (or `make setup`) to install new dependencies.
- If a selected provider model returns unavailable, verify its API key in `.env`
  and restart backend.

## Run with Docker (backend + frontend)

From this directory (backend), with the frontend repo as sibling `../frontend`:

```bash
docker compose up --build
```

Backend: http://localhost:8000. Frontend: http://localhost:3000. Ollama must run
on host at port 11434.

## Scheduler

APScheduler is controlled with `SCHEDULER_ENABLED` and `SCHEDULER_CRON` in `.env`. Default cron is twice daily (`"0 9,21 * * *"`). Each run: news fetch + RAG ingest, then portfolio + news analysis and in-app notification per user (and WhatsApp if configured).
If SMTP is configured, the same analysis is also emailed to each user's `email` from the users table.

**Manual trigger (same as cron run):**

```bash
curl -X POST http://localhost:8000/api/jobs/trigger-analysis
```

**News-only (fetch + ingest, no analysis):**

```bash
curl -X POST http://localhost:8000/api/jobs/trigger-news
```

If you see no notifications, ensure `ollama pull nomic-embed-text` was run and try the trigger-analysis curl above; then `GET /api/notifications`.

## Project layout

- `app/main.py` – FastAPI app
- `app/api/` – routes (chat, portfolio, notifications, auth, health, jobs)
- `app/agent/` – ReAct agent and streaming
- `app/tools/` – RAG, memory, web search, portfolio
- `app/services/` – Ollama client, news fetch, RAG ingest
- `app/jobs/` – scheduled tasks
- `app/db/` – SQLAlchemy models and session
- `docs/` – [JS→Python reference](docs/JS_TO_PYTHON_REFERENCE.md) for interview
  prep; [Comprehensive guide](docs/COMPREHENSIVE_GUIDE.md) from configuration to
  each file and Python concepts (for beginners).

## License

MIT.
