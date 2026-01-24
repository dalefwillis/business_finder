"""Run a full Flippa.com scrape and save results to the database."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

# Add src to path for script execution
# TODO: Replace with proper packaging (poetry run python -m business_finder.scripts.run_flippa)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from business_finder.config import config, FilterConfig
from business_finder.scrapers.flippa import FlippaScraper, FlippaListingCard, is_us_country
from business_finder.db.operations import (
    save_listing_from_model,
    get_all_listings,
    close_db,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

console = Console()


# =============================================================================
# Country Statistics Helper
# =============================================================================

def collect_country_stats(
    skipped_filter: list[tuple[FlippaListingCard, str]],
    skipped_known: list[FlippaListingCard],
) -> dict:
    """Collect country statistics from filtered and known cards.

    Args:
        skipped_filter: Cards that were filtered out with reasons
        skipped_known: Cards that were already in the database

    Returns:
        Dict with country stats: counts, us_matched, non_us, unknown_ids
    """
    country_counts: Counter[str] = Counter()
    us_matched: Counter[str] = Counter()
    non_us: Counter[str] = Counter()
    unknown_ids: list[str] = []

    # Process all cards
    all_cards: list[tuple[FlippaListingCard, str | None]] = [(card, None) for card in skipped_known]
    all_cards.extend(skipped_filter)

    for card, _ in all_cards:
        country = card.country or "(unknown)"
        country_counts[country] += 1

        if card.country:
            if is_us_country(card.country):
                us_matched[card.country] += 1
            else:
                non_us[card.country] += 1
        else:
            unknown_ids.append(card.external_id)

    return {
        "counts": country_counts,
        "us_matched": us_matched,
        "non_us": non_us,
        "unknown_ids": unknown_ids,
    }


def display_country_stats(stats: dict, us_only: bool = True) -> None:
    """Display country statistics to console.

    Args:
        stats: Country stats dict from collect_country_stats
        us_only: Whether US-only filtering was enabled
    """
    country_counts = stats["counts"]
    us_matched = stats["us_matched"]
    non_us = stats["non_us"]
    unknown_ids = stats["unknown_ids"]

    if not country_counts:
        return

    console.print("\n[bold]Country breakdown (all cards seen):[/bold]")

    total_us = sum(us_matched.values())
    total_non_us = sum(non_us.values())
    total_unknown = len(unknown_ids)

    if us_only:
        console.print(
            f"  [green]US: {total_us}[/green] | "
            f"[yellow]Non-US: {total_non_us}[/yellow] | "
            f"[red]Unknown: {total_unknown}[/red]"
        )
    console.print()

    for country, count in country_counts.most_common():
        if country == "(unknown)":
            marker = "[red]? unknown[/red]"
        elif is_us_country(country):
            marker = "[green]✓ US[/green]"
        else:
            marker = "[yellow]filtered[/yellow]"
        console.print(f"  {country}: {count} {marker}")

    # Warn about potential US variations we might be missing
    if us_only and non_us:
        suspicious = []
        for country in non_us:
            country_lower = country.lower()
            # Check for patterns that might be US but we're not catching
            if any(term in country_lower for term in ["united state", "america"]):
                suspicious.append(country)
            elif country_lower in ("u.s", "u.s.", "u.s.a", "u.s.a."):
                suspicious.append(country)
            elif country_lower in ("us", "usa"):
                suspicious.append(country)

        if suspicious:
            console.print("\n[bold red]WARNING: Potential US variations not recognized:[/bold red]")
            for s in suspicious:
                console.print(f"  [red]- '{s}' ({non_us[s]} listings)[/red]")

    if unknown_ids:
        console.print(f"\n[yellow]Note: {len(unknown_ids)} listings had no country detected[/yellow]")


# =============================================================================
# Main Scrape Function
# =============================================================================

async def run_scrape(
    max_pages: int | None = None,
    filters: FilterConfig | None = None,
    skip_known: bool = False,
    us_only: bool = True,
    verified_only: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Run the Flippa.com scraper and save results.

    Args:
        max_pages: Maximum number of search pages to scrape (None = all)
        filters: Filter configuration (uses central config.filters if None)
        skip_known: If True, skip listings already in the database
        us_only: If True, only include US-based listings
        verified_only: Only include verified listings
        dry_run: If True, scrape but don't save to DB
        verbose: If True, print detailed progress

    Returns:
        Dict with statistics about the scrape.
    """
    scraper = FlippaScraper(headless=True)

    # Use central config if no filters provided
    active_filters = filters if filters is not None else config.filters

    console.print("\n[bold blue]Starting Flippa.com scrape[/bold blue]")
    console.print(f"  Max pages: {max_pages or 'all'}")
    if active_filters.min_annual_revenue:
        console.print(f"  Min profit: ${active_filters.min_annual_revenue / 100:,.0f}")
    else:
        console.print("  Min profit: none")
    console.print(f"  Category blacklist: {len(active_filters.category_blacklist)} categories")
    console.print(f"  US only: {us_only}")
    console.print(f"  Verified only: {verified_only}")
    console.print(f"  Skip known: {skip_known}")
    console.print(f"  Dry run: {dry_run}")
    console.print()

    # Run the scrape with filtering
    result, skipped_filter, skipped_known = await scraper.scrape_with_filter(
        filters=filters,
        max_pages=max_pages,
        skip_known=skip_known,
        us_only=us_only,
        verified_only=verified_only,
        verbose=verbose,
    )

    console.print(
        f"[green]Scrape complete:[/green] {result.success_count} listings scraped, "
        f"{result.error_count} errors"
    )
    if skipped_known:
        console.print(f"[dim]Skipped {len(skipped_known)} already-known listings[/dim]")
    console.print(f"[dim]Skipped {len(skipped_filter)} listings that didn't pass filters[/dim]")

    # Collect and display country statistics
    country_stats = collect_country_stats(skipped_filter, skipped_known)
    display_country_stats(country_stats, us_only=us_only)

    # Save to database
    stats = {
        "scraped": result.success_count,
        "errors": result.error_count,
        "skipped_filter": len(skipped_filter),
        "skipped_known": len(skipped_known),
        "new": 0,
        "updated": 0,
        "save_errors": 0,
    }

    if not dry_run and result.listings:
        console.print("\n[bold]Saving to database...[/bold]")

        for listing in result.listings:
            try:
                _, is_new = save_listing_from_model(listing)
                if is_new:
                    stats["new"] += 1
                    if verbose:
                        console.print(f"  [green]NEW[/green] {listing.title}")
                else:
                    stats["updated"] += 1
                    if verbose:
                        console.print(f"  [yellow]UPD[/yellow] {listing.title}")
            except Exception as e:
                stats["save_errors"] += 1
                logger.error(f"Failed to save listing {listing.external_id}: {e}")
                console.print(f"  [red]ERR[/red] {listing.title}: {e}")

        console.print(f"[green]Saved:[/green] {stats['new']} new, {stats['updated']} updated")
        if stats["save_errors"]:
            console.print(f"[red]Save errors:[/red] {stats['save_errors']}")

    # Report scraping errors if any
    if result.errors:
        console.print(f"\n[bold red]Scrape errors ({result.error_count}):[/bold red]")
        for err in result.errors:
            console.print(f"  [red]✗[/red] {err.url}")
            console.print(f"    {err.error_type}: {err.error_message}")

    # Show sample of skipped if verbose
    if verbose and skipped_filter:
        console.print("\n[dim]Sample of filter-skipped listings:[/dim]")
        for card, reason in skipped_filter[:5]:
            console.print(f"  [dim]- {card.title or card.external_id}: {reason}[/dim]")
        if len(skipped_filter) > 5:
            console.print(f"  [dim]... and {len(skipped_filter) - 5} more[/dim]")

    return stats


# =============================================================================
# Database Summary
# =============================================================================

def show_summary() -> None:
    """Show a summary of what's currently in the database."""
    listings = get_all_listings(source_id="flippa")

    if not listings:
        console.print("\n[dim]No Flippa listings in database yet.[/dim]")
        return

    console.print(f"\n[bold]Database Summary: {len(listings)} Flippa listings[/bold]")

    # Count by category
    categories: dict[str, int] = {}
    for listing in listings:
        cat = listing.get("category") or "(uncategorized)"
        categories[cat] = categories.get(cat, 0) + 1

    table = Table(title="Listings by Category")
    table.add_column("Category", style="cyan")
    table.add_column("Count", justify="right")

    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        table.add_row(cat, str(count))

    console.print(table)

    # Show price range
    prices = [listing["asking_price"] for listing in listings if listing.get("asking_price")]

    if prices:
        console.print(f"\nPrice range: ${min(prices) / 100:,.0f} - ${max(prices) / 100:,.0f}")


# =============================================================================
# CLI Entry Point
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Flippa.com scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --max-pages 5 --dry-run     # Test scrape of 5 pages
  %(prog)s --min-profit 10000 -v       # Filter by $10k+ annual profit
  %(prog)s --include-intl              # Include international listings
  %(prog)s --summary-only              # Just show database stats
""",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of search pages to scrape (default: all)",
    )
    parser.add_argument(
        "--min-profit",
        type=int,
        default=None,
        help="Minimum annual profit in dollars to include",
    )
    parser.add_argument(
        "--skip-blacklist",
        action="store_true",
        help="Don't apply category blacklist (include all categories)",
    )
    parser.add_argument(
        "--include-intl",
        action="store_true",
        help="Include international listings (default: US only)",
    )
    parser.add_argument(
        "--verified-only",
        action="store_true",
        help="Only include listings with verified status",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-scrape all listings, even ones already in the database",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape but don't save to database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed progress",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Just show database summary, don't scrape",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("business_finder").setLevel(logging.DEBUG)

    # Build filter config from CLI args
    min_profit_cents = args.min_profit * 100 if args.min_profit else None

    filters = config.filters.with_overrides(
        min_annual_revenue=min_profit_cents,
        category_blacklist=[] if args.skip_blacklist else None,
    )

    try:
        if args.summary_only:
            show_summary()
        else:
            stats = asyncio.run(
                run_scrape(
                    max_pages=args.max_pages,
                    filters=filters,
                    skip_known=not args.refresh,
                    us_only=not args.include_intl,
                    verified_only=args.verified_only,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                )
            )

            # Show final summary
            console.print("\n" + "=" * 50)
            console.print("[bold]Final Statistics:[/bold]")
            console.print(f"  Scraped:          {stats['scraped']}")
            console.print(f"  New:              {stats['new']}")
            console.print(f"  Updated:          {stats['updated']}")
            console.print(f"  Skipped (filter): {stats['skipped_filter']}")
            console.print(f"  Skipped (known):  {stats['skipped_known']}")
            console.print(f"  Scrape errors:    {stats['errors']}")
            if stats.get("save_errors"):
                console.print(f"  Save errors:      {stats['save_errors']}")

            if not args.dry_run:
                show_summary()

    finally:
        close_db()


if __name__ == "__main__":
    main()
