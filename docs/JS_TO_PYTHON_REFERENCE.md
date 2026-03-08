# JavaScript to Python Reference (AI Trading Assistant)

Use this to explain the backend code in C-level interviews by mapping Python concepts to what you already know in JavaScript/Node.

---

## 1. Async I/O

| JavaScript / Node | Python (this project) |
|-------------------|------------------------|
| `async function fn() { await x; }` | `async def fn(): await x` |
| `Promise` | Same mental model: `await` pauses until the result is ready |
| `fetch(url).then(r => r.json())` | `async with httpx.AsyncClient() as c: r = await c.get(url)` |

**Where we use it**: Chat streaming (`async for chunk in llm.astream(...)`), DB sessions (`async with async_session_factory()`), tool runs (`await tool.ainvoke(args)`).

---

## 2. HTTP server and routes

| JavaScript / Node (Express) | Python (FastAPI) |
|----------------------------|------------------|
| `app.get("/path", (req, res) => { ... })` | `@router.get("/path")` then `async def handler(): return {...}` |
| `app.use("/api", router)` | `app.include_router(api_router, prefix="/api")` |
| `res.status(500).json({ error })` | `raise HTTPException(status_code=500, detail="...")` or `JSONResponse(status_code=500, content={...})` |

**Decorators**: `@router.get(...)` is like wrapping the function in a higher-order function that registers the route. Same idea as middleware or route wrappers in Express.

---

## 3. Request / response types

| JavaScript / Node (e.g. Zod) | Python (Pydantic) |
|------------------------------|-------------------|
| `z.object({ message: z.string() })` | `class ChatRequest(BaseModel): message: str` |
| Runtime validation + TypeScript types | Runtime validation + type hints; automatic OpenAPI schema |
| `req.body` manually parsed | FastAPI injects `body: ChatRequest` and validates |

**Where we use it**: `ChatRequest`, `PortfolioPositionCreate`, `NotificationOut`, etc. in `app/models/schemas.py`.

---

## 4. Environment config

| JavaScript / Node | Python |
|-------------------|--------|
| `process.env.OLLAMA_BASE_URL` | `os.getenv("OLLAMA_BASE_URL")` or Pydantic Settings |
| `.env` with dotenv | `pydantic-settings` with `env_file=".env"` |

**Where we use it**: `app/core/config.py` – `Settings` class with `OLLAMA_BASE_URL`, `DATABASE_URL`, etc. Loaded once and used as `settings.OLLAMA_BASE_URL`.

---

## 5. Streaming response

| JavaScript / Node | Python (FastAPI + SSE) |
|-------------------|-------------------------|
| `res.write(chunk)` in a loop | Async generator that `yield`s chunks; `EventSourceResponse(gen)` sends SSE |
| `Readable` stream | `async def gen(): yield {"data": token}` – each yield is one SSE event |

**Where we use it**: `app/api/chat.py` – `_sse_stream()` is an async generator; we `yield {"data": token}` and `EventSourceResponse` turns that into `data: <payload>\n\n`.

---

## 6. Package management and project layout

| JavaScript / Node | Python |
|-------------------|--------|
| `package.json`, `npm install` | `requirements.txt`, `pip install -r requirements.txt` |
| `src/routes/`, `src/services/` | `app/api/`, `app/services/` |
| Import from `"@/lib/api"` | `from app.services.ollama_client import get_llm` (package = directory with `__init__.py`) |

---

## 7. Type hints vs TypeScript

- **Python**: `def f(x: str) -> int:` – optional at runtime but used by tools and FastAPI for validation/OpenAPI.
- **TypeScript**: `function f(x: string): number` – same idea; Python type hints are like "TypeScript in the signature."

---

## 8. Context managers (`with`)

- **Python**: `async with async_session_factory() as session:` – "open session, use it, then close/cleanup."
- **JavaScript**: Similar to `try { const session = await getSession(); ... } finally { await session.close(); }`.

**Where we use it**: DB sessions in `app/db/session.py` and inside tools (e.g. `get_portfolio` opening a session to read positions).

---

## 9. List / dict comprehensions

- **Python**: `[p.symbol for p in positions]` ≈ `positions.map(p => p.symbol)`  
- **Python**: `{t.name: t for t in TOOLS}` ≈ `Object.fromEntries(TOOLS.map(t => [t.name, t]))`

---

## 10. Agent and tools (LangChain)

- **Tools**: Plain (async) functions decorated with `@tool`; the LLM gets their name and description and chooses when to call them (like a router that "decides the best tool").
- **ReAct loop**: The backend runs the LLM; if it returns tool calls, we run those tools, append results to the conversation, and call the LLM again until it returns a final answer. All of that is in `app/agent/runner.py` – you can say "we implement a ReAct-style agent that streams tokens and executes tools when the model requests them."

Use this doc next to the code when explaining structure, async flow, and production touches (config, errors, logging) in the interview.
