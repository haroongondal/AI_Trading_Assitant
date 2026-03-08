# SQLite – local setup and usage

The backend uses **SQLite** for users, portfolio positions, and notifications. No separate database server is required.

## Configuration

1. **`.env`** (in the `backend/` directory):
   ```env
   DATABASE_URL=sqlite+aiosqlite:///./data/trading_assistant.db
   ```
   This path is resolved relative to the backend root, so the file is always created at `backend/data/trading_assistant.db` regardless of where you run `uvicorn` from.

2. **Dependencies**: Already in `requirements.txt`:
   - `aiosqlite` – async SQLite driver
   - `sqlalchemy[asyncio]` – ORM and async engine

3. **Data directory**: `backend/data/` is created automatically when the app starts. The same directory is used for ChromaDB (RAG) data.

## Tables

Created on first startup by `init_db()` in the FastAPI lifespan:

- `users` – id, name, email, created_at
- `portfolio_positions` – user_id, symbol, quantity, entry_price, notes, created_at
- `notifications` – user_id, title, body, suggested_action, read, created_at

## Install SQLite3 CLI (optional)

Use the SQLite3 command-line tool to inspect or query the database locally.

**Ubuntu / Debian:**
```bash
sudo apt update
sudo apt install sqlite3
```

**macOS (Homebrew):**
```bash
brew install sqlite3
```

**Verify:**
```bash
sqlite3 --version
```

## Using the SQLite3 CLI

From the project root or from `backend/`:

```bash
# Open the database
sqlite3 backend/data/trading_assistant.db
```

Inside the SQLite shell:

```text
.tables                    # list tables
.schema users              # show CREATE TABLE for users
.schema portfolio_positions
.schema notifications
SELECT * FROM users;
.quit                      # exit
```

## Resetting the database

To start with a clean DB (e.g. for testing):

```bash
rm -f backend/data/trading_assistant.db
# Restart the API; tables will be recreated on startup.
```
