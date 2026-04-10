"""
Fuzzy market matcher and value-signal calculator.

Strategy
────────
Kalshi is a CFTC-regulated exchange where US residents can trade.
Metaculus is a US-accessible public forecasting platform with community
probability estimates.  Neither platform enables direct arb between them
(Metaculus is not a trading venue), but price divergence is a *value signal*:

  If the Metaculus community (aggregated expert forecasters) thinks the
  probability is M and Kalshi's market price is K:

    K < M  →  Kalshi is cheap on YES  →  candidate BUY YES on Kalshi
    K > M  →  Kalshi is expensive on YES  →  candidate BUY NO on Kalshi

  The larger |K − M|, the stronger the signal.

Matching
────────
Normalised fuzzy string match (rapidfuzz token-sort) on:
  Kalshi : market title + subtitle
  Metaculus : question title

Minimum similarity threshold is configurable (default 0.72).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz, process

from kalshi_client import KalshiMarket
from metaculus_client import MetaculusQuestion

_STOP_WORDS = frozenset(
    {
        "will", "the", "a", "an", "in", "of", "to", "by", "be", "is",
        "are", "was", "were", "has", "have", "had", "does", "do", "did",
        "for", "on", "at", "from", "with", "that", "this", "than",
        "win", "wins", "winning", "winner", "lose", "loses",
    }
)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in text.split() if t not in _STOP_WORDS and len(t) > 1]
    return " ".join(tokens)


@dataclass
class MatchedPair:
    kalshi: KalshiMarket
    metaculus: MetaculusQuestion
    similarity: float            # 0–1 fuzzy score

    # Value-signal fields (populated by _fill_signal)
    kalshi_mid: float = 0.0
    metaculus_prob: float = 0.0
    divergence: float = 0.0      # |K_mid − M|  (always ≥ 0)
    signal: str = ""             # "BUY_YES" | "BUY_NO" | "NEUTRAL"
    signal_strength: str = ""    # "STRONG" | "MODERATE" | "WEAK"


# Divergence thresholds for labelling signal strength.
_STRONG = 0.12
_MODERATE = 0.06


def _fill_signal(pair: MatchedPair) -> None:
    k = pair.kalshi.yes_mid
    m = pair.metaculus.community_prob
    div = k - m  # positive → Kalshi over-prices YES

    pair.kalshi_mid = k
    pair.metaculus_prob = m
    pair.divergence = abs(div)

    if div < -0.01:
        pair.signal = "BUY_YES"   # Kalshi cheap vs community
    elif div > 0.01:
        pair.signal = "BUY_NO"    # Kalshi expensive vs community
    else:
        pair.signal = "NEUTRAL"

    if pair.divergence >= _STRONG:
        pair.signal_strength = "STRONG"
    elif pair.divergence >= _MODERATE:
        pair.signal_strength = "MODERATE"
    else:
        pair.signal_strength = "WEAK"


def match_markets(
    kalshi_markets: list[KalshiMarket],
    metaculus_questions: list[MetaculusQuestion],
    min_similarity: float = 0.72,
) -> list[MatchedPair]:
    """
    Fuzzy-match each Kalshi market to its closest Metaculus question.

    Returns pairs sorted by similarity score (descending).
    Only pairs above `min_similarity` are included.
    """
    if not kalshi_markets or not metaculus_questions:
        return []

    meta_norm = [_normalise(q.title) for q in metaculus_questions]

    pairs: list[MatchedPair] = []
    for km in kalshi_markets:
        km_norm = _normalise(km.display_name)
        if not km_norm:
            continue

        result = process.extractOne(
            km_norm,
            meta_norm,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=min_similarity * 100,
        )
        if result is None:
            continue

        _, raw_score, idx = result
        pair = MatchedPair(
            kalshi=km,
            metaculus=metaculus_questions[idx],
            similarity=raw_score / 100.0,
        )
        _fill_signal(pair)
        pairs.append(pair)

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs


def filter_signals(
    pairs: list[MatchedPair],
    min_divergence: float = 0.05,
    signals: Optional[list[str]] = None,
    min_liquidity_kalshi: Optional[int] = None,
) -> list[MatchedPair]:
    """
    Filter matched pairs to actionable value signals.

    Parameters
    ----------
    min_divergence:
        Minimum |K_mid − M| to include (default 0.05 = 5 percentage points).
    signals:
        If provided, only return pairs whose signal is in this list,
        e.g. ["BUY_YES"] or ["BUY_YES", "BUY_NO"].
    min_liquidity_kalshi:
        Minimum Kalshi open interest (contracts) to include.
    """
    out: list[MatchedPair] = []
    for p in pairs:
        if p.divergence < min_divergence:
            continue
        if signals and p.signal not in signals:
            continue
        if min_liquidity_kalshi and p.kalshi.open_interest < min_liquidity_kalshi:
            continue
        out.append(p)

    out.sort(key=lambda p: p.divergence, reverse=True)
    return out
