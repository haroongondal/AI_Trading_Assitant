# Market data APIs (PSX, NASDAQ, forex)

This backend’s `get_quote` tool uses **CoinGecko** (crypto, no key), optional **REST** providers when you set keys in `backend/.env`, then **web search** as a fallback.

## What this app uses when keys are set

| Env var | Use case | Notes |
|--------|-----------|--------|
| `TWELVEDATA_API_KEY` | **PSX** symbols in our catalog | Quoted on exchange **XKAR** (Pakistan Stock Exchange in Twelve Data). |
| `FINNHUB_API_KEY` | **US / NASDAQ** and many global tickers | Real-time `quote` endpoint; free tier has per-minute limits. |
| `ALPHA_VANTAGE_API_KEY` | **US** backup | Used if Finnhub does not return a price; free tier is **25 requests/day**. |
| *(none)* | **USD ↔ PKR** hint | `get_quote` uses **open.er-api.com** (`/v6/latest/USD`) for an approximate PKR/USD cross-rate (no key; powered by ExchangeRate-API). |

See `app/services/market_quotes.py` and `app/tools/quote.py`.

## External options (April 2026 landscape)

Summarized from public vendor positioning; verify pricing and terms on each site before production.

### PSX (Pakistan Stock Exchange)

- **Capital Stake** — PSX-focused commercial API (quotes, indices, derivatives, ETFs); strong local coverage.
- **EODHD** — Historical and fundamentals for `PSX.KAR`; free tier for testing.
- **Twelve Data** — PSX as **XKAR**; symbol discovery and market hours; tiered plans.
- **Mettis Global / Investify.pk** — Local PSX data partners (commercial).

**Recommendation:** For automated PSX quotes in this repo, configure **Twelve Data** (`TWELVEDATA_API_KEY`). For deeper local coverage, evaluate **Capital Stake** (integrate separately if they expose a REST key you can call from Python).

### NASDAQ and global equities

- **Alpha Vantage** — Free tier (~25 calls/day), US and global equities, ETFs, indicators.
- **Finnhub** — REST and WebSocket; free tier ~**60 calls/minute** for many US symbols.
- **Marketstack** — JSON API; free plans with monthly caps.
- **Nasdaq Data Link (Quandl)** — Strong for historical datasets and indices; daily free request allowances on some products.

**Recommendation:** Prefer **Finnhub** for real-time US quotes here; **Alpha Vantage** as a sparse backup.

### Forex

- **ExchangeRate-API** — Generous free monthly quotas; many currencies.
- **CurrencyFreaks** — Broad fiat + crypto coverage; free starter tier.
- **Fixer.io** — Fast JSON forex (higher refresh often paid).
- **Open access:** This repo uses **open.er-api.com** for a no-key **USD/PKR** cross when formatting PSX hints (not a substitute for a full FX stack).

**Recommendation:** For production FX beyond a rough PKR/USD hint, add a dedicated provider (e.g. ExchangeRate-API) in `market_quotes.py` if you need audited rates.

## Setup

Add to `backend/.env` (never commit real keys):

```env
# TWELVEDATA_API_KEY=
# FINNHUB_API_KEY=
# ALPHA_VANTAGE_API_KEY=
```

Restart the API after changes.
