"""
Kalshi REST API client (v2).

Docs: https://trading-api.kalshi.com/trade-api/v2/swagger-ui
Auth: optional – supply KALSHI_API_KEY for better rate limits.
      Without a key the public market-data endpoints still work.

Prices returned by the API are integers 0–99 (cents).
This module normalises them to floats 0.0–1.0 for easy comparison.
"""

import os
import time
from dataclasses import dataclass
from typing import Iterator, Optional

import requests

BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"
DEMO_URL = "https://demo-api.kalshi.co/trade-api/v2"

_PAGE_SIZE = 200
_REQUEST_DELAY = 0.12  # seconds between paginated requests (~8 req/s)


@dataclass
class KalshiMarket:
    ticker: str
    title: str
    subtitle: str
    yes_bid: float   # best bid for YES  (0.0–1.0)
    yes_ask: float   # best ask for YES  (0.0–1.0)
    no_bid: float
    no_ask: float
    last_price: float
    volume: int
    open_interest: int
    close_time: str
    category: str

    # ── derived ───────────────────────────────────────────────────────────────

    @property
    def yes_mid(self) -> float:
        """Midpoint of the YES market.  Falls back to last_price if no quotes."""
        if self.yes_bid > 0 and self.yes_ask > 0:
            return (self.yes_bid + self.yes_ask) / 2.0
        return self.last_price

    @property
    def display_name(self) -> str:
        return f"{self.title} — {self.subtitle}" if self.subtitle else self.title

    @property
    def has_liquidity(self) -> bool:
        """True when there is a two-sided market (bid AND ask present)."""
        return self.yes_bid > 0 and self.yes_ask > 0


def _cents_to_prob(value: int | float) -> float:
    """Convert a Kalshi price (0–99 cents) to a probability (0.0–1.0)."""
    if value is None:
        return 0.0
    # Guard: if somehow already a fraction, return as-is.
    return float(value) / 100.0 if float(value) > 1.0 else float(value)


class KalshiClient:
    """
    Thin wrapper around the Kalshi v2 REST API.

    Parameters
    ----------
    api_key:
        Optional API key.  If omitted the client tries the KALSHI_API_KEY
        environment variable, then falls back to unauthenticated requests.
    use_demo:
        Point at the demo (paper-trading) environment.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_demo: bool = False,
    ) -> None:
        self.base_url = DEMO_URL if use_demo else BASE_URL
        key = api_key or os.getenv("KALSHI_API_KEY", "")

        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        if key:
            # Kalshi accepts a bare API key in the Authorization header.
            self._session.headers["Authorization"] = f"Token {key}"

    # ── low-level ──────────────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, params=params, timeout=30)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Kalshi API error {resp.status_code}: {resp.text[:200]}"
            ) from exc
        return resp.json()

    # ── public ────────────────────────────────────────────────────────────────

    def iter_open_markets(self) -> Iterator[dict]:
        """Yield raw market dicts for every open market, handling pagination."""
        cursor: Optional[str] = None
        while True:
            params: dict = {"status": "open", "limit": _PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor

            data = self._get("/markets", params)
            markets = data.get("markets") or []
            yield from markets

            cursor = data.get("cursor")
            if not cursor:
                break
            time.sleep(_REQUEST_DELAY)

    def get_all_open_markets(self) -> list[KalshiMarket]:
        """Return all open binary markets with normalised prices."""
        results: list[KalshiMarket] = []

        for raw in self.iter_open_markets():
            # Skip multi-outcome (non-binary) markets – they have no yes_ask.
            if raw.get("can_close_early") is None and "yes_ask" not in raw:
                continue

            yes_bid = _cents_to_prob(raw.get("yes_bid", 0))
            yes_ask = _cents_to_prob(raw.get("yes_ask", 0))
            no_bid = _cents_to_prob(raw.get("no_bid", 0))
            no_ask = _cents_to_prob(raw.get("no_ask", 0))
            last_price = _cents_to_prob(raw.get("last_price", 0))

            # Drop markets with zero price data (illiquid / delisted ghost entries).
            if yes_ask == 0 and last_price == 0:
                continue

            results.append(
                KalshiMarket(
                    ticker=raw.get("ticker", ""),
                    title=raw.get("title", ""),
                    subtitle=raw.get("subtitle", "") or "",
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    no_ask=no_ask,
                    last_price=last_price,
                    volume=int(raw.get("volume", 0) or 0),
                    open_interest=int(raw.get("open_interest", 0) or 0),
                    close_time=raw.get("close_time", "") or "",
                    category=raw.get("category", "") or "",
                )
            )

        return results
