#!/usr/bin/env python3
"""
Kalshi value-signal scanner — compares Kalshi market prices to Metaculus
community forecasts to surface potentially mis-priced markets.

Why Metaculus instead of Polymarket?
  Polymarket is not legally accessible to US traders (CFTC settlement 2022,
  US geofencing).  Metaculus is a US-accessible public forecasting platform
  whose community median probabilities serve as an independent benchmark.
  This is a *value signal*, not a pure arbitrage: you trade on Kalshi based
  on the divergence from expert-community consensus.

Usage
─────
  python scanner.py                        # full live scan
  python scanner.py --mock                 # offline test with sample data
  python scanner.py --threshold 0.08       # flag divergences ≥ 8 pp
  python scanner.py --signal BUY_YES       # only show cheap-YES signals
  python scanner.py --max-kalshi 100       # limit markets (fast dev run)
  python scanner.py --min-oi 1000          # require ≥1000 open contracts

Environment variables (see .env.example):
  KALSHI_API_KEY   – optional; improves rate limits
  KALSHI_USE_DEMO  – "true" to use the demo environment
  SPREAD_THRESHOLD – default divergence threshold
  MATCH_SIMILARITY – default fuzzy-match floor
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from kalshi_client import KalshiClient, KalshiMarket
from metaculus_client import MetaculusClient, MetaculusQuestion
from market_matcher import MatchedPair, match_markets, filter_signals

load_dotenv()

console = Console()


# ── mock data ─────────────────────────────────────────────────────────────────

def _load_mock_data() -> tuple[list[KalshiMarket], list[MetaculusQuestion]]:
    """Load fixture data for offline testing.  No API calls made."""
    from mock_data import KALSHI_MARKETS_RAW, METACULUS_QUESTIONS_RAW
    from kalshi_client import _cents_to_prob
    from metaculus_client import MetaculusClient

    kalshi = [
        KalshiMarket(
            ticker=m["ticker"],
            title=m["title"],
            subtitle=m.get("subtitle", ""),
            yes_bid=_cents_to_prob(m.get("yes_bid", 0)),
            yes_ask=_cents_to_prob(m.get("yes_ask", 0)),
            no_bid=_cents_to_prob(m.get("no_bid", 0)),
            no_ask=_cents_to_prob(m.get("no_ask", 0)),
            last_price=_cents_to_prob(m.get("last_price", 0)),
            volume=m.get("volume", 0),
            open_interest=m.get("open_interest", 0),
            close_time=m.get("close_time", ""),
            category=m.get("category", ""),
        )
        for m in KALSHI_MARKETS_RAW
    ]

    client = MetaculusClient()
    metaculus = [q for raw in METACULUS_QUESTIONS_RAW if (q := client._parse(raw))]

    return kalshi, metaculus


# ── formatting helpers ────────────────────────────────────────────────────────

def _pct(value: float, precision: int = 1) -> str:
    return f"{value * 100:.{precision}f}%"


def _signal_text(pair: MatchedPair) -> Text:
    t = Text()
    colour = {
        "BUY_YES": "green",
        "BUY_NO":  "red",
        "NEUTRAL": "dim",
    }.get(pair.signal, "white")
    label = pair.signal.replace("_", " ")
    t.append(label, style=f"bold {colour}")
    if pair.signal_strength:
        strength_colour = {
            "STRONG":   "bold",
            "MODERATE": "",
            "WEAK":     "dim",
        }.get(pair.signal_strength, "")
        t.append(f"  ({pair.signal_strength})", style=strength_colour)
    return t


def _divergence_text(div: float) -> Text:
    t = Text()
    style = (
        "bold red"    if div >= 0.12 else
        "yellow"      if div >= 0.06 else
        "white"
    )
    t.append(_pct(div), style=style)
    return t


def print_signals_table(signals: list[MatchedPair]) -> None:
    table = Table(
        box=box.ROUNDED,
        show_lines=True,
        title=f"[bold green]{len(signals)} Value Signal(s) Found[/bold green]",
        expand=True,
    )

    table.add_column("#",             style="dim",  width=3,  justify="right")
    table.add_column("Kalshi Market", min_width=32)
    table.add_column("Metaculus Question", min_width=30)
    table.add_column("Kalshi\nMid", justify="center", min_width=8)
    table.add_column("Community\nForecast", justify="center", min_width=10)
    table.add_column("Divergence\n(pp)", justify="center", min_width=10)
    table.add_column("Signal", min_width=18)
    table.add_column("Match %", justify="center", min_width=8)
    table.add_column("Metaculus URL", min_width=20)

    for i, p in enumerate(signals, 1):
        kalshi_mid = f"{p.kalshi_mid:.3f}"
        meta_prob  = f"{p.metaculus_prob:.3f}"

        table.add_row(
            str(i),
            p.kalshi.display_name[:60],
            p.metaculus.title[:60],
            kalshi_mid,
            meta_prob,
            _divergence_text(p.divergence),
            _signal_text(p),
            f"{p.similarity:.0%}",
            f"[link={p.metaculus.url}]{p.metaculus.url}[/link]",
        )

    console.print(table)


def print_summary(
    *,
    n_kalshi: int,
    n_meta: int,
    n_matched: int,
    n_signals: int,
    elapsed: float,
    threshold: float,
    mock: bool,
) -> None:
    console.print()
    console.print("[bold]Summary[/bold]")
    if mock:
        console.print("  [yellow]Mode: MOCK (no API calls made)[/yellow]")
    console.print(f"  Kalshi markets      : {n_kalshi:,}")
    console.print(f"  Metaculus questions : {n_meta:,}")
    console.print(f"  Fuzzy matches       : {n_matched:,}")
    console.print(f"  Signals (div ≥ {_pct(threshold)}) : [bold]{n_signals}[/bold]")
    console.print(f"  Elapsed             : {elapsed:.1f}s")
    console.print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    default_threshold  = float(os.getenv("SPREAD_THRESHOLD",  "0.05"))
    default_similarity = float(os.getenv("MATCH_SIMILARITY",  "0.72"))

    p = argparse.ArgumentParser(
        description="Kalshi value-signal scanner vs Metaculus community forecasts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--mock",       action="store_true",
                   help="Use local fixture data (no API calls)")
    p.add_argument("--threshold",  "-t", type=float, default=default_threshold,
                   metavar="DECIMAL",
                   help="Min |Kalshi_mid − Metaculus| to flag (e.g. 0.05 = 5 pp)")
    p.add_argument("--similarity", "-s", type=float, default=default_similarity,
                   metavar="DECIMAL",
                   help="Min fuzzy-match score (0–1)")
    p.add_argument("--signal",     choices=["BUY_YES", "BUY_NO"],
                   default=None,
                   help="Only show one signal direction")
    p.add_argument("--min-oi",     type=int, default=None, metavar="CONTRACTS",
                   help="Min Kalshi open interest to include")
    p.add_argument("--max-kalshi", type=int, default=None, metavar="N",
                   help="Cap Kalshi markets fetched (fast dev run)")
    p.add_argument("--meta-pages", type=int, default=5, metavar="N",
                   help="Metaculus pages to fetch (100 questions each)")
    p.add_argument("--demo",       action="store_true",
                   default=os.getenv("KALSHI_USE_DEMO", "false").lower() == "true",
                   help="Use Kalshi demo environment")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    t0 = time.monotonic()

    console.rule("[bold blue]Kalshi Value-Signal Scanner[/bold blue]")
    console.print()

    # ── Data fetch ────────────────────────────────────────────────────────────
    if args.mock:
        console.print("[yellow]-- MOCK MODE: loading fixture data --[/yellow]\n")
        try:
            kalshi_markets, metaculus_questions = _load_mock_data()
        except ImportError:
            console.print("[red]mock_data.py not found.  Run without --mock.[/red]")
            return 1
    else:
        # Kalshi
        with console.status("[bold]Fetching Kalshi markets…[/bold]"):
            try:
                kalshi_markets = KalshiClient(use_demo=args.demo).get_all_open_markets()
            except RuntimeError as exc:
                console.print(f"[red]Kalshi fetch failed:[/red] {exc}")
                return 1

        if args.max_kalshi:
            kalshi_markets = kalshi_markets[: args.max_kalshi]

        console.print(
            f"  [green]✓[/green] Kalshi: [bold]{len(kalshi_markets):,}[/bold] open markets"
        )

        # Metaculus
        with console.status("[bold]Fetching Metaculus questions…[/bold]"):
            try:
                metaculus_questions = MetaculusClient().get_open_questions(
                    max_pages=args.meta_pages
                )
            except RuntimeError as exc:
                console.print(f"[red]Metaculus fetch failed:[/red] {exc}")
                return 1

        console.print(
            f"  [green]✓[/green] Metaculus: [bold]{len(metaculus_questions):,}[/bold] "
            "questions with community forecasts"
        )

    # ── Match ─────────────────────────────────────────────────────────────────
    with console.status(
        f"[bold]Matching markets (similarity ≥ {args.similarity:.0%})…[/bold]"
    ):
        matched = match_markets(
            kalshi_markets, metaculus_questions, min_similarity=args.similarity
        )

    console.print(
        f"  [green]✓[/green] Matched: [bold]{len(matched):,}[/bold] pairs"
    )

    # ── Filter ────────────────────────────────────────────────────────────────
    signal_filter = [args.signal] if args.signal else None
    signals = filter_signals(
        matched,
        min_divergence=args.threshold,
        signals=signal_filter,
        min_liquidity_kalshi=args.min_oi,
    )

    elapsed = time.monotonic() - t0
    console.print()

    # ── Output ────────────────────────────────────────────────────────────────
    if not signals:
        console.print(
            f"[yellow]No signals found with divergence ≥ {_pct(args.threshold)}.[/yellow]\n"
            "Try lowering [bold]--threshold[/bold] or [bold]--similarity[/bold]."
        )
    else:
        print_signals_table(signals)

    print_summary(
        n_kalshi=len(kalshi_markets),
        n_meta=len(metaculus_questions),
        n_matched=len(matched),
        n_signals=len(signals),
        elapsed=elapsed,
        threshold=args.threshold,
        mock=args.mock,
    )

    console.print(
        "[dim]Prices are indicative. Metaculus forecasts reflect community "
        "consensus, not guaranteed outcomes. Always do your own research before "
        "placing any trade on Kalshi.[/dim]"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
