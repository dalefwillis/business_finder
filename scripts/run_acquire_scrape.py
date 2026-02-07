"""Run a full Acquire.com scrape and save results to the database.

Requires ACQUIRE_USERNAME and ACQUIRE_PASSWORD in environment or .env file.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from rich.console import Console
from rich.table import Table

from business_finder.config import config, FilterConfig
from business_finder.db.operations import (
    save_listing_from_model,
    get_all_listings,
    close_db,
)
from business_finder.scrapers.acquire import AcquireScraper
from business_finder.scrapers.base import ScrapeError
from business_finder.notifications import ScraperStats, send_scraper_success, send_scraper_failure


console = Console()


async def run_refresh(
    max_listings: int | None = None,
    older_than_days: int = 7,
    dry_run: bool = False,
    verbose: bool = False,
    headless: bool = True,
) -> dict:
    """Refresh existing listings to detect status/price changes.

    Args:
        max_listings: Maximum number of listings to refresh (None = all)
        older_than_days: Only refresh listings not refreshed in this many days
        dry_run: If True, scrape but don't save to DB
        verbose: If True, print detailed progress
        headless: If True, run browser in headless mode

    Returns:
        Dict with statistics about the refresh.
    """
    start_time = datetime.now()
    scraper = AcquireScraper(headless=headless)

    console.print(f"\n[bold blue]Starting Acquire.com refresh[/bold blue]")
    console.print(f"  Max listings: {max_listings or 'all'}")
    console.print(f"  Older than: {older_than_days} days")
    console.print(f"  Dry run: {dry_run}")
    console.print()

    result = await scraper.refresh_listings(
        older_than_days=older_than_days,
        max_listings=max_listings,
        verbose=verbose,
    )

    console.print(f"[green]Refresh complete:[/green] {result.success_count} listings refreshed, {result.error_count} errors")

    stats = {
        "refreshed": result.success_count,
        "errors": result.error_count,
        "updated": 0,
        "save_errors": 0,
    }

    if not dry_run and result.listings:
        console.print("\n[bold]Saving refreshed listings...[/bold]")
        for listing in result.listings:
            try:
                _, is_new = save_listing_from_model(listing, is_refresh=True)
                stats["updated"] += 1
                if verbose:
                    console.print(f"  [yellow]UPD[/yellow] {listing.title}")
            except Exception as e:
                stats["save_errors"] += 1
                logger.error(f"Failed to save listing {listing.external_id}: {e}")
                console.print(f"  [red]ERR[/red] {listing.title}: {e}")

        console.print(f"[green]Saved:[/green] {stats['updated']} updated")

    if result.errors:
        console.print(f"\n[bold red]Errors ({result.error_count}):[/bold red]")
        for err in result.errors[:10]:
            console.print(f"  [red]✗[/red] {err.url}")
            console.print(f"    {err.error_type}: {err.error_message}")
        if result.error_count > 10:
            console.print(f"  ... and {result.error_count - 10} more errors")

    # Calculate duration and send Slack notification
    duration = datetime.now() - start_time

    error_details = None
    if result.errors:
        error_details = [
            (err.url, err.error_type, err.error_message)
            for err in result.errors
        ]

    scraper_stats = ScraperStats(
        source_name="Acquire (refresh)",
        duration=duration,
        total_seen=stats["refreshed"] + stats["errors"],
        scraped=stats["refreshed"],
        filtered_out=0,
        already_known=0,
        new_stored=0,
        updated=stats["updated"],
        errors=stats["errors"] + stats.get("save_errors", 0),
        error_details=error_details,
    )
    send_scraper_success(scraper_stats)

    return stats


async def run_scrape(
    max_listings: int | None = None,
    filters: FilterConfig | None = None,
    skip_known: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
    headless: bool = True,
) -> dict:
    """Run the Acquire.com scraper and save results.

    Args:
        max_listings: Maximum number of listings to scrape (None = all)
        filters: Filter configuration (uses central config.filters if None)
        skip_known: If True, skip listings already in the database
        dry_run: If True, scrape but don't save to DB
        verbose: If True, print detailed progress
        headless: If True, run browser in headless mode

    Returns:
        Dict with statistics about the scrape.
    """
    start_time = datetime.now()

    # Use central config if no filters provided
    if filters is None:
        filters = config.filters

    console.print(f"\n[bold blue]Starting Acquire.com scrape[/bold blue]")
    console.print(f"  Max listings: {max_listings or 'all'}")
    console.print(f"  Category blacklist: {len(filters.category_blacklist)} categories")
    console.print(f"  Skip known: {skip_known}")
    console.print(f"  Dry run: {dry_run}")
    console.print(f"  Headless: {headless}")
    console.print()

    scraper = AcquireScraper(
        headless=headless,
        filter_config=filters,
        skip_known=skip_known,
    )

    # Run the scrape with filtering
    result = await scraper.run_with_filter(
        max_listings=max_listings,
        verbose=verbose,
    )

    console.print(f"\n[green]Scrape complete:[/green] {result.success_count} listings scraped, {result.error_count} errors")

    # Save to database
    stats = {
        "scraped": result.success_count,
        "errors": result.error_count,
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

    # Report errors if any
    if result.errors:
        console.print(f"\n[bold red]Errors ({result.error_count}):[/bold red]")
        for err in result.errors[:10]:  # Show first 10 errors
            console.print(f"  [red]✗[/red] {err.url}")
            console.print(f"    {err.error_type}: {err.error_message}")
        if result.error_count > 10:
            console.print(f"  ... and {result.error_count - 10} more errors")

    # Calculate duration and send Slack notification
    duration = datetime.now() - start_time

    error_details = None
    if result.errors:
        error_details = [
            (err.url, err.error_type, err.error_message)
            for err in result.errors
        ]

    scraper_stats = ScraperStats(
        source_name="Acquire",
        duration=duration,
        total_seen=scraper._total_seen,
        scraped=stats["scraped"],
        filtered_out=scraper._filtered_out,
        already_known=scraper._skipped_known,
        new_stored=stats["new"],
        updated=stats["updated"],
        errors=stats["errors"] + stats.get("save_errors", 0),
        error_details=error_details,
    )
    send_scraper_success(scraper_stats)

    return stats


def show_summary():
    """Show a summary of what's currently in the database."""
    listings = get_all_listings(source_id="acquire")

    if not listings:
        console.print("\n[dim]No Acquire listings in database yet.[/dim]")
        return

    console.print(f"\n[bold]Database Summary: {len(listings)} Acquire listings[/bold]")

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

    # Price range
    prices = [l["asking_price"] for l in listings if l.get("asking_price")]
    if prices:
        min_price = min(prices) / 100
        max_price = max(prices) / 100
        console.print(f"\nPrice range: ${min_price:,.0f} - ${max_price:,.0f}")


def main():
    parser = argparse.ArgumentParser(description="Scrape Acquire.com listings")
    parser.add_argument(
        "--max-listings",
        type=int,
        default=None,
        help="Maximum number of listings to scrape (default: all)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh existing listings to detect status/price changes (weekly job)",
    )
    parser.add_argument(
        "--include-known",
        action="store_true",
        help="When scraping, include listings already in the database",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape but don't save to database",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed progress",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Just show database summary, don't scrape",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show browser window (useful for debugging)",
    )

    args = parser.parse_args()

    if args.summary_only:
        show_summary()
        return

    start_time = datetime.now()
    try:
        if args.refresh:
            # Refresh mode: re-visit existing listings to detect changes
            stats = asyncio.run(
                run_refresh(
                    max_listings=args.max_listings,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                    headless=not args.no_headless,
                )
            )

            # Show final summary
            console.print("\n" + "=" * 50)
            console.print("[bold]Refresh Statistics:[/bold]")
            console.print(f"  Refreshed:      {stats['refreshed']}")
            console.print(f"  Updated:        {stats['updated']}")
            console.print(f"  Errors:         {stats['errors']}")
        else:
            stats = asyncio.run(
                run_scrape(
                    max_listings=args.max_listings,
                    skip_known=not args.include_known,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                    headless=not args.no_headless,
                )
            )

            # Show database summary
            show_summary()

    except KeyboardInterrupt:
        console.print("\n[yellow]Scrape interrupted by user[/yellow]")
    except Exception as e:
        duration = datetime.now() - start_time
        console.print(f"\n[bold red]Fatal error:[/bold red] {e}")
        logger.exception("Scraper failed with exception")

        # Send failure notification
        send_scraper_failure(
            source_name="Acquire",
            duration=duration,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise
    finally:
        close_db()


if __name__ == "__main__":
    main()
