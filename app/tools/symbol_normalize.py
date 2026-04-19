"""
Map common misspellings and aliases to canonical tickers for portfolio storage.
"""

_ALIASES: dict[str, str] = {
    "ETHERIUM": "ETH",
    "ETHEREUM": "ETH",
    "ETHR": "ETH",
    "BITCOIN": "BTC",
    "BITCOIN'S": "BTC",
    "BIT COIN": "BTC",
    "BITCOIN CASH": "BCH",
    "DOGECOIN": "DOGE",
    "SOLANA": "SOL",
    "RIPPLE": "XRP",
    "CARDANO": "ADA",
    "POLKADOT": "DOT",
    "AVALANCHE": "AVAX",
    "POLYGON": "MATIC",
    "CHAINLINK": "LINK",
    "LITECOIN": "LTC",
    # Optional name/alias → primary ticker (any exchange)
    "SAZGAR": "SAZEW",
    "SAZGARENGINEERING": "SAZEW",
    "SAZGARENGINEERINGWORKS": "SAZEW",
    "MARIENERGIES": "MARI",
    "MARIENERGY": "MARI",
    "MARIENERGIESLIMITED": "MARI",
}


def normalize_trading_symbol(symbol: str) -> str:
    """Uppercase, strip spaces, apply known aliases (typos, full names → tickers)."""
    raw = symbol.strip().upper()
    collapsed = raw.replace(" ", "")
    if collapsed in _ALIASES:
        return _ALIASES[collapsed]
    if raw in _ALIASES:
        return _ALIASES[raw]
    return collapsed
