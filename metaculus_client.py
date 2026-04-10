"""
Metaculus public API client.

Metaculus is a US-accessible forecasting platform.  Its community predictions
serve as an independent probability estimate to compare against Kalshi prices.

Endpoint: https://www.metaculus.com/api2/questions/
No authentication required for public questions.

Key fields:
  title                            – question text (used for fuzzy matching)
  community_prediction.full.q2    – community median forecast (0.0–1.0)
  close_time                       – ISO 8601 resolution date
  id                               – question ID
"""

import time
from dataclasses import dataclass
from typing import Optional

import requests

BASE_URL = "https://www.metaculus.com/api2"
_PAGE_SIZE = 100
_REQUEST_DELAY = 0.5   # Metaculus rate-limits aggressively; be conservative


@dataclass
class MetaculusQuestion:
    id: int
    title: str
    community_prob: float   # community median, 0.0–1.0
    close_time: str
    url: str

    @property
    def has_forecast(self) -> bool:
        return 0.0 < self.community_prob < 1.0


class MetaculusClient:
    """
    Read-only client for the Metaculus REST API.

    Only fetches open binary/forecast questions that have a community prediction.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "kalshi-scanner/1.0",
        })

    def _get_page(self, page: int) -> dict:
        params = {
            "format": "json",
            "status": "open",
            "type": "forecast",   # binary & continuous forecasts
            "page_size": _PAGE_SIZE,
            "page": page,
        }
        resp = self._session.get(f"{BASE_URL}/questions/", params=params, timeout=30)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Metaculus API error {resp.status_code}: {resp.text[:200]}"
            ) from exc
        return resp.json()

    def get_open_questions(self, max_pages: int = 10) -> list[MetaculusQuestion]:
        """
        Return open Metaculus questions that have a community median forecast.

        Parameters
        ----------
        max_pages:
            Safety cap on pagination (100 questions/page → 1 000 max by default).
        """
        results: list[MetaculusQuestion] = []
        page = 1

        while page <= max_pages:
            data = self._get_page(page)
            raw_list = data.get("results", [])

            for raw in raw_list:
                q = self._parse(raw)
                if q is not None:
                    results.append(q)

            if not data.get("next"):
                break

            page += 1
            time.sleep(_REQUEST_DELAY)

        return results

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse(raw: dict) -> Optional[MetaculusQuestion]:
        title = (raw.get("title") or "").strip()
        if not title:
            return None

        # community_prediction can be None for questions with <5 forecasters.
        cp = raw.get("community_prediction") or {}
        full = cp.get("full") or {}
        q2 = full.get("q2")  # median
        if q2 is None:
            return None

        try:
            prob = float(q2)
        except (TypeError, ValueError):
            return None

        if not (0.0 < prob < 1.0):
            return None

        question_id = raw.get("id", 0)
        url = f"https://www.metaculus.com/questions/{question_id}/"

        return MetaculusQuestion(
            id=question_id,
            title=title,
            community_prob=prob,
            close_time=raw.get("close_time") or "",
            url=url,
        )
