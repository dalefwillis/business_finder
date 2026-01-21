"""Run a full Microns.io scrape and save results to the database."""

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from business_finder.db.operations import (
    save_listing_from_model,
    get_all_listings,
    close_db,
)
from business_finder.scrapers.microns import MicronsScraper, ListingCard


console = Console()


async def run_scrape(
    max_pages: int | None = None,
    min_revenue: int | None = None,
    max_price: int | None = None,
    skip_blacklist: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Run the Microns.io scraper and save results.

    Args:
        max_pages: Maximum number of index pages to scrape (None = all)
        min_revenue: Minimum annual revenue in cents to include
        max_price: Maximum asking price in cents to include
        skip_blacklist: If True, don't apply category blacklist
        dry_run: If True, scrape but don't save to DB
        verbose: If True, print detailed progress

    Returns:
        Dict with statistics about the scrape.
    """
    scraper = MicronsScraper(headless=True)

    # Determine blacklist
    category_blacklist = None if skip_blacklist else scraper.CATEGORY_BLACKLIST

    console.print(f"\n[bold blue]Starting Microns.io scrape[/bold blue]")
    console.print(f"  Max pages: {max_pages or 'all'}")
    console.print(f"  Min revenue: ${min_revenue/100:,.0f}" if min_revenue else "  Min revenue: none")
    console.print(f"  Max price: ${max_price/100:,.0f}" if max_price else "  Max price: none")
    console.print(f"  Category blacklist: {'disabled' if skip_blacklist else 'enabled'}")
    console.print(f"  Dry run: {dry_run}")
    console.print()

    # Run the scrape with filtering
    result, skipped = await scraper.scrape_with_filter(
        min_revenue=min_revenue,
        max_price=max_price,
        category_blacklist=category_blacklist,
        max_pages=max_pages,
    )

    console.print(f"[green]Scrape complete:[/green] {result.success_count} listings scraped, {result.error_count} errors")
    console.print(f"[dim]Skipped {len(skipped)} listings that didn't pass filters[/dim]")

    # Save to database
    stats = {
        "scraped": result.success_count,
        "errors": result.error_count,
        "skipped": len(skipped),
        "new": 0,
        "updated": 0,
    }

    if not dry_run and result.listings:
        console.print("\n[bold]Saving to database...[/bold]")
        for listing in result.listings:
            listing_id, is_new = save_listing_from_model(listing)
            if is_new:
                stats["new"] += 1
                if verbose:
                    console.print(f"  [green]NEW[/green] {listing.title}")
            else:
                stats["updated"] += 1
                if verbose:
                    console.print(f"  [yellow]UPD[/yellow] {listing.title}")

        console.print(f"[green]Saved:[/green] {stats['new']} new, {stats['updated']} updated")

    # Report errors if any
    if result.errors:
        console.print(f"\n[bold red]Errors ({result.error_count}):[/bold red]")
        for err in result.errors:
            console.print(f"  [red]✗[/red] {err.url}")
            console.print(f"    {err.error_type}: {err.error_message}")

    # Show sample of skipped if verbose
    if verbose and skipped:
        console.print(f"\n[dim]Sample of skipped listings:[/dim]")
        for card in skipped[:5]:
            reason = []
            if category_blacklist and card.category in category_blacklist:
                reason.append(f"blacklisted category: {card.category}")
            if min_revenue and (card.annual_revenue is None or card.annual_revenue < min_revenue):
                reason.append(f"low revenue: ${(card.annual_revenue or 0)/100:,.0f}")
            if max_price and (card.asking_price is None or card.asking_price > max_price):
                reason.append(f"high price: ${(card.asking_price or 0)/100:,.0f}")
            console.print(f"  [dim]- {card.title}: {', '.join(reason)}[/dim]")
        if len(skipped) > 5:
            console.print(f"  [dim]... and {len(skipped) - 5} more[/dim]")

    return stats


def show_summary():
    """Show a summary of what's currently in the database."""
    listings = get_all_listings(source_id="microns")

    if not listings:
        console.print("\n[dim]No Microns listings in database yet.[/dim]")
        return

    console.print(f"\n[bold]Database Summary: {len(listings)} Microns listings[/bold]")

    # Count by category
    categories = {}
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
    prices = [l["asking_price"] for l in listings if l.get("asking_price")]
    revenues = [l["annual_revenue"] for l in listings if l.get("annual_revenue")]

    if prices:
        console.print(f"\nPrice range: ${min(prices)/100:,.0f} - ${max(prices)/100:,.0f}")
    if revenues:
        console.print(f"Revenue range: ${min(revenues)/100:,.0f} - ${max(revenues)/100:,.0f}")


def main():
    parser = argparse.ArgumentParser(description="Run Microns.io scraper")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of index pages to scrape (default: all)",
    )
    parser.add_argument(
        "--min-revenue",
        type=int,
        default=None,
        help="Minimum annual revenue in dollars to include",
    )
    parser.add_argument(
        "--max-price",
        type=int,
        default=None,
        help="Maximum asking price in dollars to include",
    )
    parser.add_argument(
        "--skip-blacklist",
        action="store_true",
        help="Don't apply category blacklist (include all categories)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape but don't save to database",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Just show database summary, don't scrape",
    )

    args = parser.parse_args()

    # Convert dollars to cents for revenue/price filters
    min_revenue = args.min_revenue * 100 if args.min_revenue else None
    max_price = args.max_price * 100 if args.max_price else None

    try:
        if args.summary_only:
            show_summary()
        else:
            stats = asyncio.run(run_scrape(
                max_pages=args.max_pages,
                min_revenue=min_revenue,
                max_price=max_price,
                skip_blacklist=args.skip_blacklist,
                dry_run=args.dry_run,
                verbose=args.verbose,
            ))

            # Show final summary
            console.print("\n" + "=" * 50)
            console.print("[bold]Final Statistics:[/bold]")
            console.print(f"  Scraped: {stats['scraped']}")
            console.print(f"  New:     {stats['new']}")
            console.print(f"  Updated: {stats['updated']}")
            console.print(f"  Skipped: {stats['skipped']}")
            console.print(f"  Errors:  {stats['errors']}")

            if not args.dry_run:
                show_summary()

    finally:
        close_db()


if __name__ == "__main__":
    main()
