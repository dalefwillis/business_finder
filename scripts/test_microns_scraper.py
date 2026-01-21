"""Test script for the Microns.io scraper."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from business_finder.scrapers.microns import MicronsScraper, ListingCard


console = Console()


async def test_get_cards(max_pages: int = 3):
    """Test getting listing cards from the index page."""
    console.print(f"\n[bold blue]Testing get_listing_cards(max_pages={max_pages})...[/bold blue]\n")

    scraper = MicronsScraper(headless=True)
    await scraper.setup()

    try:
        cards = await scraper.get_listing_cards(max_pages=max_pages, verbose=True)
        console.print(f"[green]Found {len(cards)} listing cards[/green]\n")

        # Display in a table
        table = Table(title="Microns.io Listings")
        table.add_column("Title", style="cyan", max_width=40)
        table.add_column("Category", style="magenta")
        table.add_column("Revenue", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Multiple", justify="right")

        for card in cards:
            revenue = f"${card.annual_revenue / 100:,.0f}" if card.annual_revenue else "N/A"
            price = f"${card.asking_price / 100:,.0f}" if card.asking_price else "N/A"
            multiple = f"{card.revenue_multiple:.1f}x" if card.revenue_multiple else "N/A"

            table.add_row(
                card.title[:40] if card.title else "N/A",
                card.category or "N/A",
                revenue,
                price,
                multiple,
            )

        console.print(table)

        # Show filtering example using blacklist
        console.print("\n[bold]Filtering: blacklist non-software, max $100k, min $1k revenue[/bold]")
        blacklist = scraper.CATEGORY_BLACKLIST
        console.print(f"[dim]Blacklisted: {', '.join(blacklist)}[/dim]\n")

        filtered = [c for c in cards if c.passes_filter(
            max_price=10000000,  # $100k in cents
            min_revenue=100000,  # $1k in cents
            category_blacklist=blacklist,
        )]
        console.print(f"[green]{len(filtered)}/{len(cards)} listings pass filter[/green]")
        for card in filtered[:10]:  # Show first 10
            price = f"${card.asking_price/100:,.0f}" if card.asking_price else "N/A"
            rev = f"${card.annual_revenue/100:,.0f}" if card.annual_revenue else "N/A"
            console.print(f"  - {card.title[:40]} | {card.category} | {price} | {rev}/yr")
        if len(filtered) > 10:
            console.print(f"  ... and {len(filtered) - 10} more")

        return cards

    finally:
        await scraper.teardown()


async def test_scrape_listing(url: str):
    """Test scraping a single listing detail page."""
    console.print(f"\n[bold blue]Testing scrape_listing({url})...[/bold blue]\n")

    scraper = MicronsScraper(headless=True)
    await scraper.setup()

    try:
        listing = await scraper.scrape_listing(url)
        console.print("[green]Successfully scraped listing:[/green]")
        console.print(f"  Title: {listing.title}")
        console.print(f"  Category: {listing.category}")
        console.print(f"  Asking Price: ${listing.asking_price / 100:,.0f}" if listing.asking_price else "  Asking Price: N/A")
        console.print(f"  Annual Revenue: ${listing.annual_revenue / 100:,.0f}" if listing.annual_revenue else "  Annual Revenue: N/A")
        console.print(f"  Customers: {listing.customers}" if listing.customers else "  Customers: N/A")
        console.print(f"  Launched: {listing.launched_year}" if listing.launched_year else "  Launched: N/A")
        console.print(f"  Posted: {listing.posted_at}" if listing.posted_at else "  Posted: N/A")
        console.print(f"  Description: {listing.description[:100]}..." if listing.description else "  Description: N/A")
        return listing

    finally:
        await scraper.teardown()


async def main():
    """Run all tests."""
    console.print("[bold]Microns.io Scraper Test[/bold]")
    console.print("=" * 50)

    # Test 1: Get cards
    cards = await test_get_cards()

    # Test 2: Scrape a single listing (use first card URL)
    if cards:
        await test_scrape_listing(cards[0].url)

    console.print("\n[bold green]All tests completed![/bold green]")


if __name__ == "__main__":
    asyncio.run(main())
