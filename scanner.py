#!/usr/bin/env python3
"""
Kalshi ↔ Polymarket arbitrage scanner.

Usage
─────
  python scanner.py                    # default settings
  python scanner.py --threshold 0.03  # flag spreads ≥ 3 ¢
  python scanner.py --viable-only      # only show fee-adjusted positives
  python scanner.py --max-kalshi 100   # limit Kalshi markets (faster dev run)
  python scanner.py --min-liquidity 500  # Polymarket liquidity filter (USD)
  python scanner.py --similarity 0.80  # stricter fuzzy match

Environment variables (see .env.example):
  KALSHI_API_KEY   – optional Kalshi API key
  KALSHI_USE_DEMO  – "true" to use demo environment
  SPREAD_THRESHOLD – default threshold decimal (overridden by --threshold)
  MATCH_SIMILARITY – default similarity floor (overridden by --similarity)
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

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from market_matcher import MatchedPair, match_markets, filter_opportunities

load_dotenv()

console = Console()


# ── formatting helpers ────────────────────────────────────────────────────────

def _pct(value: float, precision: int = 1) -> str:
    return f"{value * 100:.{precision}f}%"


def _price_cell(mid: float, bid: float, ask: float) -> Text:
    """Render 'mid (bid/ask)' with colour coding."""
    t = Text()
    t.append(f"{mid:.3f}", style="bold")
    if bid > 0 and ask > 0:
        t.append(f"  [{bid:.2f}–{ask:.2f}]", style="dim")
    return t


def _direction_label(direction: str) -> str:
    if direction == "BUY_POLY_SELL_KALSHI":
        return "Buy Poly / Sell Kalshi"
    return "Buy Kalshi / Sell Poly"


def print_opportunity_table(opps: list[MatchedPair]) -> None:
    table = Table(
        box=box.ROUNDED,
        show_lines=True,
        title=f"[bold green]{len(opps)} Flagged Market(s)[/bold green]",
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Kalshi Market", min_width=30)
    table.add_column("Polymarket Question", min_width=28)
    table.add_column("Kalshi YES\n(mid [bid–ask])", justify="center", min_width=16)
    table.add_column("Poly YES", justify="center", min_width=8)
    table.add_column("Spread", justify="center", min_width=7)
    table.add_column("Est. Net\nProfit", justify="center", min_width=9)
    table.add_column("Direction", min_width=22)
    table.add_column("Match %", justify="center", min_width=8)

    for i, opp in enumerate(opps, 1):
        km = opp.kalshi
        pm = opp.polymarket

        # Colour spread by size
        spread_str = _pct(opp.spread)
        spread_style = (
            "bold red" if opp.spread >= 0.10
            else "yellow" if opp.spread >= 0.07
            else "white"
        )

        net_str = _pct(opp.net_profit)
        net_style = "green" if opp.viable else "dim red"

        table.add_row(
            str(i),
            km.display_name[:60],
            pm.question[:60],
            _price_cell(km.yes_mid, km.yes_bid, km.yes_ask),
            f"{pm.yes_price:.3f}",
            Text(spread_str, style=spread_style),
            Text(net_str, style=net_style),
            _direction_label(opp.arb_direction),
            f"{opp.similarity:.0%}",
        )

    console.print(table)


def print_summary(
    n_kalshi: int,
    n_poly: int,
    n_matched: int,
    n_flagged: int,
    elapsed: float,
    threshold: float,
) -> None:
    console.print()
    console.print("[bold]Summary[/bold]")
    console.print(f"  Kalshi open markets   : {n_kalshi:,}")
    console.print(f"  Polymarket active     : {n_poly:,}")
    console.print(f"  Fuzzy matches found   : {n_matched:,}")
    console.print(f"  Flagged (spread ≥ {_pct(threshold)}) : [bold]{n_flagged}[/bold]")
    console.print(f"  Total time            : {elapsed:.1f}s")
    console.print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    default_threshold = float(os.getenv("SPREAD_THRESHOLD", "0.05"))
    default_similarity = float(os.getenv("MATCH_SIMILARITY", "0.72"))

    parser = argparse.ArgumentParser(
        description="Scan for price discrepancies between Kalshi and Polymarket.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=default_threshold,
        metavar="DECIMAL",
        help="Minimum spread to flag (e.g. 0.05 = 5 ¢ difference in YES price)",
    )
    parser.add_argument(
        "--similarity", "-s",
        type=float,
        default=default_similarity,
        metavar="DECIMAL",
        help="Minimum fuzzy-match score to consider markets equivalent (0–1)",
    )
    parser.add_argument(
        "--viable-only",
        action="store_true",
        help="Only show opportunities with estimated net profit > 0 after fees",
    )
    parser.add_argument(
        "--min-liquidity",
        type=float,
        default=None,
        metavar="USD",
        help="Minimum Polymarket liquidity in USD",
    )
    parser.add_argument(
        "--max-kalshi",
        type=int,
        default=None,
        metavar="N",
        help="Cap the number of Kalshi markets fetched (useful for quick tests)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        default=os.getenv("KALSHI_USE_DEMO", "false").lower() == "true",
        help="Use Kalshi demo environment",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    t0 = time.monotonic()

    # ── Fetch Kalshi ──────────────────────────────────────────────────────────
    console.rule("[bold blue]Kalshi ↔ Polymarket Arbitrage Scanner[/bold blue]")
    console.print()

    with console.status("[bold]Fetching Kalshi markets…[/bold]"):
        try:
            kalshi = KalshiClient(use_demo=args.demo)
            kalshi_markets = kalshi.get_all_open_markets()
        except RuntimeError as exc:
            console.print(f"[red]Kalshi fetch failed:[/red] {exc}")
            return 1

    if args.max_kalshi:
        kalshi_markets = kalshi_markets[: args.max_kalshi]

    console.print(
        f"  [green]✓[/green] Kalshi: [bold]{len(kalshi_markets):,}[/bold] open markets"
    )

    # ── Fetch Polymarket ──────────────────────────────────────────────────────
    with console.status("[bold]Fetching Polymarket markets…[/bold]"):
        try:
            poly = PolymarketClient()
            poly_markets = poly.get_all_active_markets()
        except RuntimeError as exc:
            console.print(f"[red]Polymarket fetch failed:[/red] {exc}")
            return 1

    console.print(
        f"  [green]✓[/green] Polymarket: [bold]{len(poly_markets):,}[/bold] active markets"
    )

    # ── Match ─────────────────────────────────────────────────────────────────
    with console.status(
        f"[bold]Fuzzy-matching markets (similarity ≥ {args.similarity:.0%})…[/bold]"
    ):
        matched = match_markets(kalshi_markets, poly_markets, min_similarity=args.similarity)

    console.print(
        f"  [green]✓[/green] Matched: [bold]{len(matched):,}[/bold] market pairs"
    )

    # ── Filter ────────────────────────────────────────────────────────────────
    opportunities = filter_opportunities(
        matched,
        spread_threshold=args.threshold,
        require_viable=args.viable_only,
        min_liquidity=args.min_liquidity,
    )

    elapsed = time.monotonic() - t0
    console.print()

    # ── Output ────────────────────────────────────────────────────────────────
    if not opportunities:
        console.print(
            f"[yellow]No markets flagged with spread ≥ {_pct(args.threshold)}.[/yellow]\n"
            "Try lowering [bold]--threshold[/bold] or [bold]--similarity[/bold]."
        )
    else:
        print_opportunity_table(opportunities)

    print_summary(
        n_kalshi=len(kalshi_markets),
        n_poly=len(poly_markets),
        n_matched=len(matched),
        n_flagged=len(opportunities),
        elapsed=elapsed,
        threshold=args.threshold,
    )

    console.print(
        "[dim]Prices are indicative. Always verify on-exchange before trading. "
        "Fee estimates are approximate.[/dim]"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
