"""
Fuzzy market matcher and spread calculator.

Matching strategy
─────────────────
1. Normalise both market titles (lowercase, strip punctuation, common words).
2. For each Kalshi market, use rapidfuzz to find the best Polymarket candidate
   whose normalised question scores above `min_similarity`.
3. Return the ranked list of (KalshiMarket, PolymarketMarket, score) triples.

Spread / arb logic
──────────────────
On prediction markets every outcome pays exactly $1, so:

  If Kalshi YES mid = K  and Polymarket YES mid = P  (K > P):
    → Buy YES on Polymarket (cost P), buy NO on Kalshi (cost 1−K)
    → Total cost = P + (1−K) = 1 − (K−P)
    → Guaranteed profit per $1 notional = K − P

  The opportunity is viable when: K − P  >  estimated round-trip fees

Estimated fees (conservative)
  Kalshi:      ~7 ¢ per contract (taker fee ≈ 10 % of notional)
  Polymarket:  ~2 % of winnings  ≈ 2 ¢ on a 50/50 market
  Round-trip:  ~5–9 ¢ depending on prices; we default to 5 ¢ threshold.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

from kalshi_client import KalshiMarket
from polymarket_client import PolymarketMarket

# Words that add noise without aiding matching.
_STOP_WORDS = frozenset(
    {
        "will", "the", "a", "an", "in", "of", "to", "by", "be", "is",
        "are", "was", "were", "has", "have", "had", "does", "do", "did",
        "for", "on", "at", "from", "with", "that", "this", "than",
        "win", "wins", "winning", "winner", "lose", "loses",
        "election", "elections",
    }
)


def _normalise(text: str) -> str:
    """Lower-case, strip accents/punctuation, remove stop-words."""
    # Unicode normalise → ASCII
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    # Replace punctuation with spaces
    text = re.sub(r"[^\w\s]", " ", text)
    # Collapse whitespace
    tokens = text.split()
    tokens = [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]
    return " ".join(tokens)


@dataclass
class MatchedPair:
    kalshi: KalshiMarket
    polymarket: PolymarketMarket
    similarity: float        # 0–1 fuzzy score

    # Spread info (populated by compute_spread)
    spread: float = 0.0          # |K_yes_mid − P_yes_price|
    arb_direction: str = ""      # "BUY_POLY_SELL_KALSHI" | "BUY_KALSHI_SELL_POLY"
    gross_profit: float = 0.0    # = spread (per $1 notional, before fees)
    net_profit: float = 0.0      # gross_profit − estimated fees
    viable: bool = False         # True when net_profit > 0


def match_markets(
    kalshi_markets: list[KalshiMarket],
    poly_markets: list[PolymarketMarket],
    min_similarity: float = 0.72,
) -> list[MatchedPair]:
    """
    Match each Kalshi market to its closest Polymarket equivalent.

    Returns a list of MatchedPair objects sorted by similarity score (desc).
    Only pairs that exceed `min_similarity` are included.
    """
    if not kalshi_markets or not poly_markets:
        return []

    # Pre-normalise Polymarket questions once (avoids O(n²) normalisation).
    poly_norm = [_normalise(p.question) for p in poly_markets]

    pairs: list[MatchedPair] = []

    for km in kalshi_markets:
        km_norm = _normalise(km.display_name)
        if not km_norm:
            continue

        # rapidfuzz returns (matched_string, score, index)
        result = process.extractOne(
            km_norm,
            poly_norm,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=min_similarity * 100,  # rapidfuzz uses 0–100
        )
        if result is None:
            continue

        _, raw_score, idx = result
        score = raw_score / 100.0  # normalise to 0–1

        pair = MatchedPair(
            kalshi=km,
            polymarket=poly_markets[idx],
            similarity=score,
        )
        _fill_spread(pair)
        pairs.append(pair)

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs


def _fill_spread(pair: MatchedPair) -> None:
    """Compute and store spread metrics on an existing MatchedPair (in-place)."""
    k_mid = pair.kalshi.yes_mid
    p_mid = pair.polymarket.yes_price

    spread = k_mid - p_mid  # positive → Kalshi priced higher

    if spread > 0:
        direction = "BUY_POLY_SELL_KALSHI"
    else:
        direction = "BUY_KALSHI_SELL_POLY"
        spread = -spread

    # Estimated round-trip fee (see module docstring).
    # Simple linear model: base 3 ¢ + 10 % of the winning side's price.
    fee_kalshi = 0.03 + 0.10 * k_mid
    fee_poly = 0.02 * p_mid
    est_fees = fee_kalshi + fee_poly

    pair.spread = spread
    pair.arb_direction = direction
    pair.gross_profit = spread
    pair.net_profit = spread - est_fees
    pair.viable = pair.net_profit > 0


def filter_opportunities(
    pairs: list[MatchedPair],
    spread_threshold: float = 0.05,
    require_viable: bool = False,
    min_liquidity: Optional[float] = None,
) -> list[MatchedPair]:
    """
    Filter and sort matched pairs down to actionable opportunities.

    Parameters
    ----------
    spread_threshold:
        Minimum raw spread (|K_mid − P_mid|) as a decimal, e.g. 0.05 = 5 ¢.
    require_viable:
        If True, also require net_profit > 0 after fee estimates.
    min_liquidity:
        If set, require Polymarket liquidity ≥ this USD value.
    """
    out: list[MatchedPair] = []
    for p in pairs:
        if p.spread < spread_threshold:
            continue
        if require_viable and not p.viable:
            continue
        if min_liquidity is not None and p.polymarket.liquidity < min_liquidity:
            continue
        out.append(p)

    out.sort(key=lambda p: p.spread, reverse=True)
    return out
