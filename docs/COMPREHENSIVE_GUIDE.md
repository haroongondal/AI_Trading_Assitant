# AI Trading Assistant Backend — Comprehensive Guide

This document walks you from **configuration and run commands** through **every important file**, what happens when you run things, and which **Python concepts** are used where. It is written for someone new to Python and its ecosystem.

---

# Part 1: Configuration and Run Commands

## 1.1 What You Run and What Happens

### Step 1: Copy environment file

```bash
cd backend
cp .env.example .env
```

- **What this does**: Copies the example environment file to `.env`. The app reads `.env` when it starts and loads variables like `OLLAMA_BASE_URL`, `DATABASE_URL`, etc.
- **Python ecosystem**: Many Python apps use a `.env` file for config (similar to Node’s `dotenv`). The library that reads it here is **pydantic-settings**, which we’ll see in `app/core/config.py`.

### Step 2: Create a virtual environment

```bash
python -m venv .venv
```

- **What this does**: Creates a folder `.venv` with an isolated Python interpreter and a place to install packages. Nothing from this project is installed yet.
- **Python concept**: **Virtual environment** — like a project-local Node `node_modules` plus a specific Node version. You want one per project so dependencies don’t clash. `venv` is built into Python 3.

### Step 3: Activate the virtual environment

```bash
source .venv/bin/activate   # Linux/macOS
# or:  .venv\Scripts\activate   on Windows
```

- **What this does**: Makes your shell use the Python and `pip` inside `.venv`. After this, `pip install` and `python`/`uvicorn` are scoped to this project.
- **Python concept**: **Activation** just changes the `PATH` so the first `python` and `pip` found are the ones in `.venv`. There’s no magic; it’s a shell script.

### Step 4: Install dependencies

```bash
pip install -r requirements.txt
```

- **What this does**: Reads `requirements.txt` and installs every listed package (and their dependencies) into `.venv`. So you get FastAPI, LangChain, SQLAlchemy, etc.
- **Python concept**: **pip** is the default package installer (like `npm install`). **requirements.txt** is like `package.json` dependencies, but a simple list of `name==version` lines.

### Step 5: Create data directory (optional)

```bash
mkdir -p data
```

- **What this does**: Creates a `data` folder. The app can create it automatically when it starts (see `app/db/session.py`), but creating it beforehand is fine.
- **Why**: SQLite will store the database file under `backend/data/`, and ChromaDB will store vector data there too.

### Step 6: Start the API server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **What this does**:
  - **uvicorn**: An ASGI server that runs the FastAPI app. It listens on port 8000 and forwards every HTTP request to FastAPI.
  - **app.main:app**: “From the package `app`, module `main`, use the object named `app`.” That object is the FastAPI application instance.
  - **--reload**: Restarts the server when you change Python files (development only).
  - **--host 0.0.0.0**: Listen on all interfaces so you can reach the API from another machine (e.g. frontend on another port or host).
- **Python concept**: **ASGI** (Asynchronous Server Gateway Interface) is the standard for async Python web apps. FastAPI is an ASGI app; uvicorn is an ASGI server (like a runtime that runs your app).

**When uvicorn starts:**

1. It imports `app.main`, which imports the rest of the app (config, DB, routes, etc.).
2. FastAPI’s **lifespan** runs: `init_db()` creates SQLite tables, then the scheduler starts.
3. The server listens. Each HTTP request is handled by the route functions you defined (e.g. `GET /api/health`, `POST /api/chat/stream`).

---

## 1.2 Configuration Files

### `requirements.txt`

- **Role**: Declares Python dependencies and their versions.
- **What each group does** (conceptually):
  - **FastAPI & server**: `fastapi`, `uvicorn`, `sse-starlette` — web framework, ASGI server, SSE streaming.
  - **Config & validation**: `pydantic`, `pydantic-settings` — load and validate config and request/response bodies.
  - **LangChain & Ollama**: `langchain`, `langchain-ollama`, `langchain-community`, `langchain-text-splitters` — LLM, tools, RAG, chunking.
  - **Vector store**: `chromadb` — store and search embeddings for RAG.
  - **HTTP**: `httpx` — async HTTP client (e.g. health check to Ollama).
  - **Scheduler**: `apscheduler` — cron-like jobs (news fetch, analysis).
  - **Database**: `aiosqlite`, `sqlalchemy` — async SQLite and ORM.
  - **Utils**: `python-dotenv`, `feedparser`, `duckduckgo-search` — env loading, RSS, search.

### `.env` and `.env.example`

- **Role**: `.env` holds real config (and is git-ignored). `.env.example` is a template with no secrets.
- **What the app expects** (see `app/core/config.py`):
  - `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBEDDING_MODEL` — where and which Ollama models to use.
  - `DATABASE_URL` — SQLite (or Postgres) connection string.
  - `API_V1_PREFIX`, `CORS_ORIGINS` — URL prefix and allowed frontend origins.
  - `DEFAULT_USER_ID` — single-user id for demo.
  - `CHROMA_PERSIST_DIR`, `RAG_TOP_K` — where to store vectors and how many to retrieve.

---

# Part 2: Project Layout (Where Things Live)

```
backend/
├── app/
│   ├── main.py           # FastAPI app, lifespan, CORS, routes, exception handler
│   ├── core/
│   │   └── config.py     # Load settings from .env (pydantic-settings)
│   ├── db/
│   │   ├── session.py    # SQLite connection, session factory, get_db, init_db
│   │   └── models.py     # SQLAlchemy table definitions (User, PortfolioPosition, Notification)
│   ├── models/
│   │   └── schemas.py    # Pydantic request/response models (ChatRequest, PortfolioOut, etc.)
│   ├── api/
│   │   ├── __init__.py   # Mounts all route modules under /api
│   │   ├── health.py     # GET /api/health
│   │   ├── chat.py       # POST /api/chat/stream (SSE)
│   │   ├── portfolio.py  # GET/POST/DELETE /api/portfolio
│   │   ├── notifications.py  # GET /api/notifications, PATCH .../read
│   │   └── jobs.py       # POST /api/jobs/trigger-news, trigger-analysis
│   ├── agent/
│   │   └── runner.py     # ReAct agent: stream LLM + run tools (RAG, memory, web, portfolio)
│   ├── tools/
│   │   ├── rag.py        # query_rag tool (ChromaDB + Ollama embeddings)
│   │   ├── memory.py    # remember, recall tools; add_to_conversation
│   │   ├── web_search.py # search_web (DuckDuckGo)
│   │   └── portfolio.py  # get_portfolio (read from DB)
│   ├── services/
│   │   ├── ollama_client.py  # get_llm() -> ChatOllama
│   │   ├── news_fetcher.py   # fetch_news() from RSS
│   │   └── rag_ingest.py     # ingest_documents() -> Chroma
│   └── jobs/
│       └── scheduler.py  # APScheduler: news + ingest, analyze + notify
├── data/                 # Created at runtime: SQLite DB, Chroma data
├── docs/                 # This guide and other docs
├── requirements.txt
├── .env
├── .env.example
└── Dockerfile
```

---

# Part 3: File-by-File — What Each File Does and Which Python Concepts It Uses

## 3.1 `app/main.py` — Application entry point

**What this file does:**

- Creates the FastAPI app and wires CORS, the `/api` router, and a global exception handler.
- Defines a **lifespan**: on startup it runs `init_db()` and `start_scheduler()`; on shutdown it runs `stop_scheduler()`.
- Exposes a simple `GET /health` for liveness.

**What happens when you run `uvicorn app.main:app`:**

1. Python loads `app.main` and evaluates `app = FastAPI(...)`. FastAPI reads `lifespan=lifespan` and will call that context manager when the server starts and stops.
2. When the server starts, it enters the lifespan: runs `await init_db()` (creates tables), then `start_scheduler()` (schedules cron jobs).
3. When a request comes in, FastAPI matches the path to a route (e.g. `GET /api/health` → `health_router`, `POST /api/chat/stream` → `chat_stream`). If an unhandled exception is raised, `global_exception_handler` runs and returns a 500 JSON response.

**Python concepts used:**

- **Imports**: `import logging`, `from fastapi import FastAPI`, etc. Python uses modules and packages; `app.main` means package `app`, module `main`.
- **Decorators**: `@asynccontextmanager`, `@app.exception_handler(Exception)`, `@app.get("/health")`. A decorator is a function that wraps another function; here they register lifespan, exception handler, and routes with FastAPI.
- **async def**: Asynchronous functions. `async def lifespan(...)` and `async def root_health()` can use `await` and are run by the async event loop without blocking the server.
- **Context manager**: `@asynccontextmanager` and `async def lifespan(...): ... yield ...` define an async context manager. The code before `yield` runs on startup; the code after `yield` runs on shutdown. So “enter” = init DB + start scheduler, “exit” = stop scheduler.
- **Logging**: `logging.basicConfig(...)` and `logger = logging.getLogger(__name__)`. Standard library logging; `logger.info(...)` writes formatted messages (e.g. to stdout).

---

## 3.2 `app/core/config.py` — Settings from environment

**What this file does:**

- Defines a `Settings` class whose attributes are the app’s configuration (Ollama URL, DB URL, etc.).
- Loads those values from the environment and from a `.env` file, with defaults.
- Exposes a single instance `settings` that the rest of the app imports.

**What happens when any code does `from app.core.config import settings`:**

1. Python loads `app.core.config` and runs the module.
2. `Settings(BaseSettings)` is instantiated as `settings = Settings()`. **pydantic-settings** reads `model_config` (e.g. `env_file=".env"`), loads `.env`, and fills each attribute from the environment (or uses the default). So `settings.OLLAMA_BASE_URL` is the string from `OLLAMA_BASE_URL` in `.env` or the default.

**Python concepts used:**

- **Class and inheritance**: `class Settings(BaseSettings)` — Settings extends BaseSettings and gets validation and env loading from it.
- **Type hints**: `OLLAMA_BASE_URL: str = "..."`, `CORS_ORIGINS: list[str] = [...]`. Types are used by Pydantic for validation and by tools/IDEs; at runtime they’re not enforced by Python itself.
- **Class attribute vs instance**: Here all attributes are class-level with defaults; one instance `settings` is created. So we use it like a small config object (e.g. `settings.DATABASE_URL`).

---

## 3.3 `app/db/session.py` — Database connection and sessions

**What this file does:**

- Resolves the SQLite path so the DB file is always under `backend/data/` (relative to the backend root), creates that directory if needed, and builds the final `DATABASE_URL`.
- Creates the SQLAlchemy **async engine** and **session factory**.
- Defines `get_db()` — a generator that yields a session per request and commits or rolls back when done.
- Defines `init_db()` — creates all tables (User, PortfolioPosition, Notification) if they don’t exist.

**What happens when the app starts:**

1. This module is imported (e.g. when `main.py` imports `init_db` and when routes use `Depends(get_db)`).
2. On import, the block that starts with `_backend_root = Path(__file__).resolve()...` runs once. It computes the absolute path to the DB file, creates `backend/data` if needed, and sets `_database_url`.
3. `engine` and `async_session_factory` are created. No connection is opened yet; the engine will open connections when you first use it.
4. When FastAPI’s lifespan runs `await init_db()`, it uses `engine.begin()` to get a connection and run `Base.metadata.create_all`, which issues `CREATE TABLE IF NOT EXISTS` for each model.

**What happens when a route uses `Depends(get_db)`:**

1. FastAPI calls `get_db()`, which is an **async generator** (it has `yield`).
2. It enters `async with async_session_factory() as session`, so a new session (and connection) is created.
3. It yields `session` to the route. The route runs with that session (e.g. `await db.execute(...)`).
4. When the route returns, execution resumes after the `yield`: `await session.commit()` is called (or rollback on exception), then the session is closed. So one request = one transaction.

**Python concepts used:**

- **pathlib.Path**: `Path(__file__).resolve().parent.parent.parent` — `__file__` is the path of the current file; `.resolve()` makes it absolute; `.parent` goes up one directory. So we get the backend root directory in an OS-independent way.
- **Conditional logic at import time**: The `if _database_url.startswith("sqlite+aiosqlite:///./"):` block runs when the module is first imported. So “configuration” that depends on the DB path runs once at startup.
- **async generator**: `async def get_db(): ... yield session ...`. A function that contains `yield` is a generator; with `async def` it’s an async generator. FastAPI knows how to run it and inject the yielded value as the `db` parameter.
- **Context manager (async with)**: `async with async_session_factory() as session:` — “enter” gets a session, “exit” closes it. Same idea as `with open(...) as f` but async.
- **try/except/finally**: After `yield`, we commit on success, rollback on exception, and always close the session. So every code path cleans up.

---

## 3.4 `app/db/models.py` — SQLAlchemy ORM models

**What this file does:**

- Defines the **declarative base** for all models.
- Defines three tables: **User**, **PortfolioPosition**, **Notification**, with columns and relationships (e.g. User has many PortfolioPosition).

**What happens when `init_db()` runs:**

- `Base.metadata.create_all` looks at every class that subclasses `Base` and creates the corresponding table (users, portfolio_positions, notifications) if it doesn’t exist. Column types and foreign keys come from the model definitions.

**Python concepts used:**

- **Inheritance**: `class User(Base)` — each model inherits from Base and gets mapped to a table.
- **Class attributes with type annotations**: `id: Mapped[str] = mapped_column(...)`. **Mapped** is a SQLAlchemy 2 style: the type hint says “this attribute is a str”, and `mapped_column` defines the actual column (type, primary_key, etc.).
- **Optional types**: `email: Mapped[str | None]` — can be str or None. In Python 3.10+ you can write `X | Y` for union types.
- **relationship()**: Tells SQLAlchemy about links between tables (e.g. User.portfolio_positions → list of PortfolioPosition). Used for loading related rows and for navigation in code.

---

## 3.5 `app/models/schemas.py` — Pydantic request/response models

**What this file does:**

- Defines small **data classes** for HTTP: request bodies (e.g. ChatRequest, PortfolioPositionCreate) and response shapes (e.g. PortfolioPositionOut, NotificationOut).
- FastAPI uses these to validate incoming JSON and to serialize responses (and to generate OpenAPI).

**What happens when a request hits e.g. `POST /api/chat/stream` with a body:**

1. FastAPI sees that the route is `async def chat_stream(request: ChatRequest)`.
2. It parses the JSON body and builds `ChatRequest(message=..., history=...)`. Pydantic validates types and constraints (e.g. `message` must be at least 1 character). If validation fails, FastAPI returns 422 before your function runs.
3. Your function receives a `ChatRequest` instance; you use `request.message`, `request.history`, etc.

**What happens when a route returns e.g. `PortfolioOut(...)`:**

- FastAPI uses the model’s schema to serialize the object to JSON (e.g. `positions` as a list of objects, `total_positions` as a number). So you don’t manually call `json.dumps`.

**Python concepts used:**

- **BaseModel**: Pydantic’s base. Subclass it and define attributes with type hints; you get validation and serialization.
- **Field()**: `Field(..., min_length=1)` — “required” and “at least 1 character”. `...` in Python often means “required” in Pydantic.
- **default_factory**: `history: list[ChatMessage] = Field(default_factory=list)` — use `list()` for the default, not a shared list. So each request gets its own list.
- **model_config**: `model_config = {"from_attributes": True}` — Pydantic can build the model from an ORM object (e.g. from a SQLAlchemy row) by reading its attributes. Used for responses from DB entities.

---

## 3.6 `app/api/__init__.py` — API router assembly

**What this file does:**

- Imports one **router** from each route module (health, chat, portfolio, notifications, jobs).
- Creates a single `APIRouter()` and **includes** each sub-router under a prefix and tag. So all routes end up under `/api` with the right prefix (e.g. `/api/health`, `/api/chat/stream`).

**What happens when the app starts:**

- `main.py` does `app.include_router(api_router, prefix=settings.API_V1_PREFIX)`. So the router from this file is mounted at `/api`. FastAPI merges all included routes; a request to `GET /api/health` is handled by `health_router`’s `@router.get("")` because that router was included with `prefix="/health"`.

**Python concepts used:**

- **Import and aliasing**: `from .health import router as health_router` — import the `router` object from the same package’s `health` module and give it a clear name.
- **Object composition**: We don’t inherit from a base router; we create one and attach others to it with `include_router`. So the API is built by composition.

---

## 3.7 `app/api/health.py` — Health check route

**What this file does:**

- Defines `GET /api/health` (actually `GET ""` with prefix `/health`, so full path is `/api/health`).
- The handler checks the database (run `SELECT 1`) and Ollama (HTTP GET to `/api/tags`). It returns a small JSON with status and per-component ok/error.

**What happens when a client calls `GET /api/health`:**

1. FastAPI invokes `health(db=...)`. The `db` argument is filled by **dependency injection**: FastAPI calls `get_db()`, gets the yielded session, and passes it to `health`.
2. The function runs `await db.execute(text("SELECT 1"))` to verify the DB connection. Then it uses `httpx.AsyncClient()` to call Ollama. Both are async.
3. It returns a dict; FastAPI serializes it to JSON and sends the response.

**Python concepts used:**

- **Depends(get_db)**: **Dependency injection**. FastAPI sees that the route needs `db` and that it should get it by calling `get_db()`. So the route doesn’t create the session itself; it receives it.
- **async with httpx.AsyncClient()**: Async HTTP client used as a context manager. The client is closed when the block exits.
- **f-string**: `f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"` — string with expressions inside `{}`. `.rstrip('/')` is a string method.

---

## 3.8 `app/api/chat.py` — Streaming chat endpoint

**What this file does:**

- Defines `POST /api/chat/stream`. The body is a `ChatRequest` (message + history). The response is a **Server-Sent Events (SSE)** stream: each token from the agent is sent as an event.
- Uses the agent in `app/agent/runner.py` to generate the reply (with tools). Each token is yielded to the client; optionally the user message is added to the conversation memory.

**What happens when a client sends a message and opens the stream:**

1. FastAPI validates the body as `ChatRequest` and calls `chat_stream(request)`.
2. `chat_stream` builds `history_dicts` from `request.history` (using `model_dump()` to turn Pydantic models into dicts) and returns `EventSourceResponse(_sse_stream(...))`. **EventSourceResponse** is a Starlette/FastAPI response type that consumes an async generator and sends each yielded item as an SSE event.
3. `_sse_stream` is an **async generator**. It iterates over `stream_agent_response(message, history_dicts)`. Each token from the agent is yielded as `{"data": token}`. The SSE library formats that as `data: <token>\n\n` and sends it to the client. So the client sees a stream of tokens (like ChatGPT).
4. When the agent finishes, we optionally call `add_to_conversation(...)` so the user message is stored for the “recall” tool.

**Python concepts used:**

- **Async generator (again)**: `async def _sse_stream(...): ... yield {"data": token}`. The caller (EventSourceResponse) does `async for ... in _sse_stream(...)` and sends each chunk. So “streaming” in Python is often “yield chunks from an async generator.”
- **List comprehension**: `[m.model_dump() for m in request.history]` — build a new list by applying `model_dump()` to each element. Similar to `array.map()` in JS.
- **Exception handling**: We log and re-raise `HTTPException` or yield an error string so the client gets something even when the agent fails.

---

## 3.9 `app/agent/runner.py` — ReAct agent and streaming

**What this file does:**

- Builds the list of **tools** (query_rag, search_web, get_portfolio, remember, recall) and a **tool map** by name.
- Defines `stream_agent_response(message, history)` — an async generator that runs a ReAct loop: send messages to the LLM, stream content tokens; if the LLM returns tool calls, run those tools, append results to the message list, and call the LLM again until it returns a final answer (no more tool calls).

**What happens when the chat endpoint calls `stream_agent_response`:**

1. The LLM is created with `get_llm().bind_tools(TOOLS)` so it knows the tools’ names and schemas.
2. A message list is built: system prompt, then history (as HumanMessage/AIMessage), then the new user message.
3. Loop (up to `max_turns`):
   - `async for chunk in llm.astream(messages)`: the LLM streams chunks. Each chunk may have `content` (text) and/or `tool_calls`. We yield each content token to the client and collect chunks.
   - After the stream, we merge chunks (so we can get full `tool_calls`). If there are no tool calls, we break.
   - Otherwise we run each tool with `_run_tool(name, args)`, build ToolMessage and AIMessage, append them to `messages`, and loop again so the LLM can “see” the tool results and continue.
4. So the client sees a continuous stream of text, with tool runs happening in between without the client needing to know.

**Python concepts used:**

- **Type alias**: `TOOLS: list[BaseTool]` — we’re saying “this variable is a list of BaseTool.” Helps readability and tools.
- **Dict comprehension**: `TOOL_MAP = {t.name: t for t in TOOLS}` — build a dict mapping tool name to tool. Like `Object.fromEntries(TOOLS.map(t => [t.name, t]))` in JS.
- **hasattr and getattr**: `hasattr(tool, "ainvoke")`, `getattr(merged, "tool_calls", [])` — introspect objects at runtime. We use them to support both sync and async tools and to safely read attributes that might be missing.
- **isinstance**: `if isinstance(chunk, AIMessageChunk)` — check type at runtime. Used to filter and merge chunks.
- **AsyncGenerator type hint**: `-> AsyncGenerator[str, None]` — this function is an async generator that yields strings. The second type parameter is the “return” type of the generator (often None).

---

## 3.10 `app/tools/rag.py` — RAG (retrieval) tool

**What this file does:**

- Lazily creates a **Chroma** vector store and an **Ollama embeddings** model (using settings). Exposes `get_rag_retriever()` and `get_vectorstore()` for the agent and for the ingest job.
- Defines the **query_rag** tool: given a query string, run a similarity search over the stored documents and return the top-k chunks as one string. The agent calls this when the user asks about news or documents.

**What happens when the agent calls `query_rag("latest bitcoin news")`:**

1. `get_rag_retriever()` is called (and creates the vector store and retriever on first use).
2. `retriever.invoke(query)` runs the vector search (embed query, find nearest chunks), and returns a list of documents.
3. We join their `page_content` and return that string to the LLM so it can answer using that context.

**Python concepts used:**

- **Module-level “singleton”**: `_embeddings = None`, `_vectorstore = None`, and inside functions we do `global _vectorstore` then assign. So we create the embeddings and vector store once and reuse them. This is a simple form of lazy initialization.
- **@tool decorator**: From LangChain. It turns a function into a **tool** the LLM can call: the function’s name and docstring are used to build the schema the model sees. So the model knows “there is a tool called query_rag that takes a query string.”
- **str.join**: `"\n\n---\n\n".join(doc.page_content for doc in docs)` — join strings with a separator. The argument is a generator expression (like a list comprehension but lazy).

---

## 3.11 `app/tools/memory.py` — Remember and recall tools

**What this file does:**

- Keeps in-memory structures: `_user_memory` (facts per user) and `_user_conversation` (recent messages per user).
- **remember** tool: append a fact string to the user’s list.
- **recall** tool: return a summary of stored facts and recent conversation for the user.
- **add_to_conversation**: called by the chat endpoint to push a user (or assistant) message into the buffer so “recall” can use it.

**Python concepts used:**

- **Module-level mutable state**: The dicts are defined at module level. When the process runs, they persist across requests. So this is “in-memory only”; restart clears them. Production would use DB or Redis.
- **Default argument for dict.get**: `_user_memory.get(uid, [])` — if the key is missing, return `[]`. Avoids KeyError.
- **Slicing**: `_user_conversation.get(uid, [])[-10:]` — last 10 elements. Negative index means “from the end.”
- **List and string building**: We build `parts` and then `"\n\n".join(parts)` to form the reply string.

---

## 3.12 `app/tools/web_search.py` — Web search tool

**What this file does:**

- Wraps LangChain’s **DuckDuckGoSearchRun** in a **@tool**-decorated function **search_web**. The agent can call it for live web results (e.g. current crypto/forex info).

**Python concepts used:**

- **Module-level instance**: `_search = DuckDuckGoSearchRun()` is created once at import. The tool function calls `_search.invoke(query)`. So we reuse one client.

---

## 3.13 `app/tools/portfolio.py` — Portfolio tool

**What this file does:**

- Defines **get_portfolio** as an async tool: it opens a DB session, loads the default user’s portfolio positions, formats them as text, and returns that string. The agent uses it when the user asks about their portfolio.

**What happens when the agent calls `get_portfolio()`:**

1. The tool runs `async with async_session_factory() as session`. So it creates its own session (it’s not inside a FastAPI request, so it can’t use `Depends(get_db)`).
2. It calls `_get_portfolio_summary(user_id, session)`, which runs a SQLAlchemy `select(PortfolioPosition).where(...)`, gets the list of positions, and formats them.
3. The session is closed when the `async with` block exits. The formatted string is returned to the LLM.

**Python concepts used:**

- **async def in a tool**: LangChain tools can be async. The agent runner uses `await tool.ainvoke(args)` when the tool has `ainvoke`. So the DB access is non-blocking.
- **SQLAlchemy select**: `select(PortfolioPosition).where(...)` builds a query; `await db.execute(...)` runs it; `.scalars().all()` returns the list of ORM objects.
- **f-string and conditional**: `f"... {p.notes}" if p.notes else ""` — inline conditional expression to append notes only when present.

---

## 3.14 `app/services/ollama_client.py` — LLM client

**What this file does:**

- Exposes **get_llm()** which returns a **ChatOllama** instance configured with `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and temperature. The agent and the scheduler use this to talk to Ollama.

**Python concepts used:**

- **Function as factory**: We don’t store one global LLM; we return a new instance each time (or the caller could cache it). So configuration is always read from `settings` at call time.
- **Keyword arguments**: `ChatOllama(base_url=..., model=..., temperature=...)` — arguments passed by name for clarity.

---

## 3.15 `app/services/news_fetcher.py` — RSS news fetch

**What this file does:**

- Defines a list of **RSS feed URLs** (crypto/forex). **fetch_news(limit_per_feed)** parses each feed with **feedparser**, deduplicates by link, and returns a list of dicts with title, summary, link, and published time. Used by the scheduler to feed the RAG ingest job.

**Python concepts used:**

- **Type hints for arguments and return**: `def fetch_news(limit_per_feed: int = 10) -> list[dict[str, Any]]` — parameter type and default, return type. `dict[str, Any]` is “dict with string keys and any value.”
- **set for deduplication**: `seen_links: set[str] = set()` and `seen_links.add(link)` — sets store unique values, so we avoid duplicate articles.
- **Conditional expression**: `datetime(*published[:6]) if published else datetime.utcnow()` — use parsed date if available, else now.
- **re.sub**: Regular expression to strip HTML tags from summary text. `import re` is used inside the function (lazy import; could be at top).

---

## 3.16 `app/services/rag_ingest.py` — Ingest documents into Chroma

**What this file does:**

- Uses **RecursiveCharacterTextSplitter** to split documents into chunks (size 500, overlap 80).
- **ingest_documents(docs)** takes a list of dicts (title, summary, link, published), builds LangChain **Document** objects, splits them, and adds the chunks to the Chroma vector store (via **get_vectorstore()**). The scheduler calls this after fetching news.

**Python concepts used:**

- **Constants at module level**: `TEXT_SPLITTER = RecursiveCharacterTextSplitter(...)` — created once and reused for all ingest runs.
- **List building with a loop**: We build a `documents` list, then pass it to `split_documents`. So we transform “list of dicts” → “list of Document” → “list of chunks” → add to store.
- **f-string for multiline**: A long prompt or text can be built with `f"""..."""` (triple-quoted f-string).

---

## 3.17 `app/jobs/scheduler.py` — Scheduled jobs

**What this file does:**

- Defines two async jobs: **job_fetch_news_and_ingest** (fetch RSS, then ingest into RAG) and **job_analyze_and_notify** (load user and portfolio, get RAG context, call LLM, parse response, insert a **Notification** row).
- Uses **APScheduler** with **AsyncIOScheduler** and **CronTrigger** to run these at 08:00 and 18:00 (news) and 08:15 and 18:15 (analysis).
- **start_scheduler()** adds the jobs and starts the scheduler; **stop_scheduler()** shuts it down (called from lifespan on shutdown).

**What happens when the app starts:**

- In lifespan, `start_scheduler()` is called. It registers the four jobs (two for news, two for analysis) with cron triggers and calls `scheduler.start()`. The scheduler runs in the same process as the API and uses the same event loop. At the scheduled times it will run the async job functions.

**What happens inside job_analyze_and_notify:**

1. Open a DB session with `async with async_session_factory() as db`.
2. Ensure the default user exists (select or insert).
3. Load portfolio positions and format as text.
4. Use the RAG retriever to get “latest crypto and forex news” context.
5. Build a prompt with portfolio + news and call `get_llm().ainvoke(messages)`.
6. Parse the response for “ANALYSIS:” and “SUGGESTED ACTION:”, create a **Notification** row, `db.add(notif)`, `await db.commit()`.
7. Session closes when exiting the `async with` block.

**Python concepts used:**

- **CronTrigger**: From APScheduler; you specify hour and minute (e.g. 8 and 0 for 08:00). The scheduler then invokes the job at those times.
- **Async function as job**: The job functions are `async def`. The scheduler runs them on the async loop, so we can use `await` inside (DB, LLM, etc.).
- **String parsing**: We split the LLM output on "SUGGESTED ACTION:" and "ANALYSIS:" to extract body and suggested_action. In production you might use structured output (e.g. JSON) instead.

---

## 3.18 `app/api/portfolio.py` and `app/api/notifications.py` — CRUD routes

**portfolio.py:**

- **GET /api/portfolio**: Ensures the default user exists, loads their positions, returns `PortfolioOut` (list of positions + count).
- **POST /api/portfolio**: Body is `PortfolioPositionCreate`. Creates a new **PortfolioPosition** row and returns it.
- **DELETE /api/portfolio/{id}**: Deletes the position if it belongs to the default user.

**notifications.py:**

- **GET /api/notifications**: Returns all notifications for the default user (newest first).
- **PATCH /api/notifications/{id}/read**: Sets `read=True` for that notification.

**Python concepts used:**

- **response_model**: In the decorator, e.g. `@router.get("", response_model=PortfolioOut)`. FastAPI will serialize the return value using that Pydantic model and validate the shape.
- **model_validate**: `PortfolioPositionOut.model_validate(p)` — build a Pydantic model from an ORM instance (needs `from_attributes=True` in the schema). So we convert SQLAlchemy rows to response DTOs cleanly.
- **HTTPException**: `raise HTTPException(status_code=404, detail="...")` — FastAPI catches this and returns the corresponding HTTP response. So we use exceptions for “not found” and similar.

---

## 3.19 `app/api/jobs.py` — Manual job triggers

**What this file does:**

- **POST /api/jobs/trigger-news**: Calls `job_fetch_news_and_ingest()` once (for demo/testing).
- **POST /api/jobs/trigger-analysis**: Calls `job_analyze_and_notify()` once.

So you can run the same logic as the cron jobs without waiting for the schedule.

---

# Part 4: Python Concepts Quick Reference

| Concept | Where you see it | In one line |
|--------|-------------------|-------------|
| **Module / package** | `app/`, `app/main.py`, `from app.core.config import settings` | A file is a module; a folder with `__init__.py` is a package. Imports load code and expose names. |
| **import / from** | Every file | Load another module and use its names. `from X import Y` loads X and binds Y in the current scope. |
| **Type hints** | `def f(x: str) -> int:`, `list[PortfolioPositionOut]` | Annotations for parameters and return; used by Pydantic and tools, not enforced by the interpreter. |
| **async def / await** | Routes, get_db, agent, jobs | Async functions run on an event loop; `await` pauses until the result is ready (like Promise in JS). |
| **Decorator** | `@router.get("")`, `@tool`, `@asynccontextmanager` | A function that wraps another; syntax `@deco def f(): ...` is equivalent to `f = deco(f)`. |
| **Context manager** | `async with session_factory() as session:` | “Enter” (get resource), “exit” (release). `with` / `async with` guarantee cleanup. |
| **Async generator** | `async def get_db(): yield session` | A function that yields values; the caller iterates with `async for`. Used for streaming and dependency injection. |
| **Class and inheritance** | `class Settings(BaseSettings)`, `class User(Base)` | Define a type with attributes and methods; subclass to extend or specialize. |
| **Pydantic BaseModel** | `app/models/schemas.py`, `app/core/config.py` | Subclass to get validation and serialization from type hints and Field(). |
| **List/dict comprehension** | `[m.model_dump() for m in request.history]`, `{t.name: t for t in TOOLS}` | Build a list or dict in one expression (like map/filter or Object.fromEntries). |
| **pathlib.Path** | `app/db/session.py` | Object-oriented path handling; `.parent`, `.resolve()`, `/` to join, `.as_posix()` for URLs. |
| **logging** | All modules | `logger = logging.getLogger(__name__)`; `logger.info(...)`, `logger.exception(...)` for structured log output. |
| **Dependency injection** | `Depends(get_db)` in route parameters | FastAPI calls the dependency function and passes the result into the route. So “how to get db” is centralized in get_db. |

---

# Part 5: Request flow example (chat)

To tie it together, here’s what happens for one **POST /api/chat/stream** request:

1. **uvicorn** receives the request and passes it to **FastAPI**.
2. FastAPI matches the path to **chat_stream** in **app/api/chat.py** and parses the body into **ChatRequest** (Pydantic).
3. **chat_stream** returns **EventSourceResponse(_sse_stream(...))**.
4. **EventSourceResponse** starts iterating **async for token in stream_agent_response(...)** (from **app/agent/runner.py**).
5. **stream_agent_response** builds messages, then loops: **llm.astream(messages)** streams chunks. Each content token is **yield**ed, so it goes back to **_sse_stream** and then to the client as SSE. If the LLM returns tool calls, **runner** calls **_run_tool** for each (which may call **query_rag**, **get_portfolio**, etc. in **app/tools/**), appends results to messages, and streams again.
6. Tools that need the DB (e.g. **get_portfolio**) create their own session via **async_session_factory()** in **app/db/session.py** and run queries against **app/db/models.py**.
7. When the agent is done, **_sse_stream** optionally calls **add_to_conversation** (in **app/tools/memory.py**) and the stream ends. The client has received all tokens as SSE events.

End-to-end: configuration (**.env** → **config.py**) is loaded at import time; the **DB** is initialized in **lifespan** and used by routes and tools; **routes** in **api/** use **schemas** for validation and **Depends(get_db)** for sessions; the **agent** in **agent/runner.py** uses **tools** and **services** (LLM, RAG, etc.); **jobs** in **jobs/scheduler.py** run on a schedule and use the same DB and LLM. This document has walked through each of those pieces and the Python concepts they use so you can reason about the project and extend it.
