# AI Trading Assistant – Backend

FastAPI backend: local Ollama LLM with RAG, memory, web search, and portfolio tools; streaming chat; scheduled news + portfolio analysis and notifications.

## Stack

Python 3.11+, FastAPI, LangChain, Ollama, ChromaDB, SQLite, APScheduler.

## Quick start

```bash
cp .env.example .env   # edit if needed
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
mkdir -p data
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API: http://localhost:8000  
- Docs: http://localhost:8000/docs  

## SQLite (local)

The app uses **SQLite** with the async driver `aiosqlite`. No separate DB server is needed.

- **Config**: In `.env`, `DATABASE_URL=sqlite+aiosqlite:///./data/trading_assistant.db`. The file is created at `backend/data/trading_assistant.db` (path is resolved from the backend root).
- **Tables**: Created automatically on first run when the API starts (`init_db` in lifespan).
- **CLI (optional)**: To inspect the DB locally, install the SQLite3 CLI and open the file:
  ```bash
  # Install (Ubuntu/Debian)
  sudo apt install sqlite3

  # Open the DB (from repo root or backend/)
  sqlite3 backend/data/trading_assistant.db
  # Then: .tables   .schema users   .quit
  ```

See [docs/SQLITE.md](docs/SQLITE.md) for more.

## Env vars

See `.env.example`. Main: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBEDDING_MODEL`, `DATABASE_URL`, `CHROMA_PERSIST_DIR`, `RAG_TOP_K`, `DEFAULT_USER_ID`.

## Run with Docker (backend + frontend)

From this directory (backend), with the frontend repo as sibling `../frontend`:

```bash
docker compose up --build
```

Backend: http://localhost:8000. Frontend: http://localhost:3000. Ollama must run on host at port 11434.

## Scheduler

APScheduler runs in-process: news fetch + RAG ingest (08:00, 18:00), portfolio + news analysis and notifications (08:15, 18:15). Manual triggers: `POST /api/jobs/trigger-news`, `POST /api/jobs/trigger-analysis`.

## Project layout

- `app/main.py` – FastAPI app
- `app/api/` – routes (chat, portfolio, notifications, health, jobs)
- `app/agent/` – ReAct agent and streaming
- `app/tools/` – RAG, memory, web search, portfolio
- `app/services/` – Ollama client, news fetch, RAG ingest
- `app/jobs/` – scheduled tasks
- `app/db/` – SQLAlchemy models and session
- `docs/` – [JS→Python reference](docs/JS_TO_PYTHON_REFERENCE.md) for interview prep; [Comprehensive guide](docs/COMPREHENSIVE_GUIDE.md) from configuration to each file and Python concepts (for beginners).

## License

MIT.
