"""
Fixture data for offline testing.

Run with:  python scanner.py --mock

Kalshi prices are raw API integers (0–99 cents).
Metaculus community_prediction mirrors the real API shape.

The examples below are illustrative only — numbers are invented to exercise
each signal type (BUY_YES, BUY_NO, NEUTRAL) and strength (STRONG, MODERATE).
"""

KALSHI_MARKETS_RAW = [
    # --- BUY_YES signal (Kalshi cheaper than community) ----------------------
    {
        "ticker": "FED-2025-MAR-CUT",
        "title": "Fed rate decision",
        "subtitle": "Will the Fed cut rates at the March 2025 meeting?",
        "yes_bid": 28,
        "yes_ask": 32,
        "no_bid": 68,
        "no_ask": 72,
        "last_price": 30,
        "volume": 85_000,
        "open_interest": 22_000,
        "close_time": "2025-03-20T18:00:00Z",
        "category": "Economics",
    },
    {
        "ticker": "RECESSION-2025",
        "title": "US Recession",
        "subtitle": "Will the US enter a recession in 2025?",
        "yes_bid": 20,
        "yes_ask": 24,
        "no_bid": 76,
        "no_ask": 80,
        "last_price": 22,
        "volume": 120_000,
        "open_interest": 45_000,
        "close_time": "2025-12-31T23:59:59Z",
        "category": "Economics",
    },
    # --- BUY_NO signal (Kalshi more expensive than community) ----------------
    {
        "ticker": "AI-AGI-2025",
        "title": "Artificial general intelligence",
        "subtitle": "Will AGI be achieved by end of 2025?",
        "yes_bid": 10,
        "yes_ask": 14,
        "no_bid": 86,
        "no_ask": 90,
        "last_price": 12,
        "volume": 60_000,
        "open_interest": 18_000,
        "close_time": "2025-12-31T23:59:59Z",
        "category": "Technology",
    },
    {
        "ticker": "BITCOIN-100K-2025",
        "title": "Bitcoin price",
        "subtitle": "Will Bitcoin reach $100K by end of 2025?",
        "yes_bid": 62,
        "yes_ask": 66,
        "no_bid": 34,
        "no_ask": 38,
        "last_price": 64,
        "volume": 250_000,
        "open_interest": 95_000,
        "close_time": "2025-12-31T23:59:59Z",
        "category": "Crypto",
    },
    # --- NEUTRAL / below threshold -------------------------------------------
    {
        "ticker": "SENATE-DEM-CONTROL",
        "title": "Senate control",
        "subtitle": "Will Democrats control the Senate after 2026 elections?",
        "yes_bid": 41,
        "yes_ask": 45,
        "no_bid": 55,
        "no_ask": 59,
        "last_price": 43,
        "volume": 300_000,
        "open_interest": 110_000,
        "close_time": "2026-11-10T00:00:00Z",
        "category": "Politics",
    },
    {
        "ticker": "UKRAINE-CEASEFIRE-2025",
        "title": "Ukraine ceasefire",
        "subtitle": "Will a ceasefire be reached in Ukraine by end of 2025?",
        "yes_bid": 53,
        "yes_ask": 57,
        "no_bid": 43,
        "no_ask": 47,
        "last_price": 55,
        "volume": 180_000,
        "open_interest": 60_000,
        "close_time": "2025-12-31T23:59:59Z",
        "category": "Geopolitics",
    },
]


# Metaculus API response shape  (mirrors real /api2/questions/ results[] items)
METACULUS_QUESTIONS_RAW = [
    # Matches "Fed rate decision — Will the Fed cut rates at the March 2025 meeting?"
    # Community says 45% → Kalshi at ~30% → BUY_YES (STRONG: +15pp)
    {
        "id": 21001,
        "title": "Will the Federal Reserve cut interest rates at its March 2025 meeting?",
        "community_prediction": {"full": {"q2": 0.45}},
        "close_time": "2025-03-20T18:00:00Z",
        "status": "open",
    },
    # Matches "US Recession — Will the US enter a recession in 2025?"
    # Community says 35% → Kalshi at ~22% → BUY_YES (STRONG: +13pp)
    {
        "id": 21002,
        "title": "Will the United States enter a recession in 2025?",
        "community_prediction": {"full": {"q2": 0.35}},
        "close_time": "2025-12-31T23:59:59Z",
        "status": "open",
    },
    # Matches "AGI — Will AGI be achieved by end of 2025?"
    # Community says 3% → Kalshi at ~12% → BUY_NO (STRONG: +9pp)
    {
        "id": 21003,
        "title": "Will artificial general intelligence (AGI) be achieved by the end of 2025?",
        "community_prediction": {"full": {"q2": 0.03}},
        "close_time": "2025-12-31T23:59:59Z",
        "status": "open",
    },
    # Matches "Bitcoin price — Will Bitcoin reach $100K by end of 2025?"
    # Community says 51% → Kalshi at ~64% → BUY_NO (MODERATE: +13pp)
    {
        "id": 21004,
        "title": "Will Bitcoin (BTC) reach $100,000 by the end of 2025?",
        "community_prediction": {"full": {"q2": 0.51}},
        "close_time": "2025-12-31T23:59:59Z",
        "status": "open",
    },
    # Matches "Senate control" — community also ~41% → NEUTRAL
    {
        "id": 21005,
        "title": "Will Democrats control the US Senate after the 2026 midterm elections?",
        "community_prediction": {"full": {"q2": 0.42}},
        "close_time": "2026-11-10T00:00:00Z",
        "status": "open",
    },
    # Matches "Ukraine ceasefire" — community ~58% → Kalshi ~55% → NEUTRAL
    {
        "id": 21006,
        "title": "Will a ceasefire be reached in Ukraine by end of 2025?",
        "community_prediction": {"full": {"q2": 0.58}},
        "close_time": "2025-12-31T23:59:59Z",
        "status": "open",
    },
    # Extra Metaculus question with no Kalshi equivalent (tests non-match path)
    {
        "id": 21007,
        "title": "Will fusion power produce net energy commercially before 2030?",
        "community_prediction": {"full": {"q2": 0.08}},
        "close_time": "2030-01-01T00:00:00Z",
        "status": "open",
    },
]
