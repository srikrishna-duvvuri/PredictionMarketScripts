"""
Polymarket client using the public Gamma API.

Endpoint: https://gamma-api.polymarket.com/markets
No authentication required for read-only access.

Key fields we use:
  question        – the market question string
  outcomePrices   – JSON-encoded list of prices, e.g. '["0.65", "0.35"]'
                    index 0 = YES / first outcome
  outcomes        – JSON-encoded list of outcome labels, e.g. '["Yes", "No"]'
  active          – bool
  closed          – bool
  volume          – total USD volume traded
  liquidity       – current USD liquidity
"""

import json
import time
from dataclasses import dataclass
from typing import Optional

import requests

GAMMA_URL = "https://gamma-api.polymarket.com/markets"

_PAGE_SIZE = 500
_REQUEST_DELAY = 0.15


@dataclass
class PolymarketMarket:
    condition_id: str
    question: str
    yes_price: float   # probability of YES outcome (0.0–1.0)
    no_price: float
    volume: float      # USD
    liquidity: float   # USD
    end_date: str

    @property
    def has_liquidity(self) -> bool:
        return self.liquidity > 0 and 0 < self.yes_price < 1


class PolymarketClient:
    """
    Read-only client for the Polymarket Gamma REST API.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    def _get_page(self, offset: int, limit: int) -> list[dict]:
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
        }
        resp = self._session.get(GAMMA_URL, params=params, timeout=30)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Polymarket API error {resp.status_code}: {resp.text[:200]}"
            ) from exc
        return resp.json()  # returns a list directly

    def get_all_active_markets(self) -> list[PolymarketMarket]:
        """
        Return all active binary markets with normalised YES prices.

        Multi-outcome markets (more than 2 outcomes) are skipped so we only
        compare apples-to-apples with Kalshi binary markets.
        """
        results: list[PolymarketMarket] = []
        offset = 0

        while True:
            raw_list = self._get_page(offset, _PAGE_SIZE)
            if not raw_list:
                break

            for raw in raw_list:
                market = self._parse(raw)
                if market is not None:
                    results.append(market)

            if len(raw_list) < _PAGE_SIZE:
                break  # last page

            offset += _PAGE_SIZE
            time.sleep(_REQUEST_DELAY)

        return results

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse(raw: dict) -> Optional["PolymarketMarket"]:
        """Parse one raw market dict into a PolymarketMarket, or None to skip."""
        question = raw.get("question", "").strip()
        if not question:
            return None

        # outcomePrices is a JSON string inside the JSON response.
        prices_raw = raw.get("outcomePrices")
        outcomes_raw = raw.get("outcomes")
        if not prices_raw or not outcomes_raw:
            return None

        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        except (json.JSONDecodeError, TypeError):
            return None

        # Only handle binary (2-outcome) markets.
        if len(prices) != 2 or len(outcomes) != 2:
            return None

        try:
            p0 = float(prices[0])
            p1 = float(prices[1])
        except (ValueError, TypeError):
            return None

        # Identify which index is YES.
        # Polymarket almost always puts Yes first, but let's be explicit.
        label0 = str(outcomes[0]).lower()
        if label0 in ("yes", "true", "1"):
            yes_price, no_price = p0, p1
        else:
            # Swap if the first outcome is "No".
            yes_price, no_price = p1, p0

        # Filter: skip markets with no meaningful price signal.
        if yes_price <= 0 or yes_price >= 1:
            return None

        return PolymarketMarket(
            condition_id=raw.get("conditionId") or raw.get("id", ""),
            question=question,
            yes_price=yes_price,
            no_price=no_price,
            volume=float(raw.get("volume", 0) or 0),
            liquidity=float(raw.get("liquidity", 0) or 0),
            end_date=raw.get("endDate") or raw.get("endDateIso", "") or "",
        )
