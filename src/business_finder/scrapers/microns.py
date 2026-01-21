"""Microns.io scraper.

Discovered selectors via Claude Chrome exploration (2026-01-21):
- Main listings page: /online-businesses-and-startups-for-sale (NOT homepage)
- Pagination: ?c150de50_page=N (12 cards per page, ~30 pages total = ~350 listings)
- Listing cards: `.listing-card`
- Card link: `a[href*="/startup-listings/"]` inside card
- Card text structure (newline-separated):
  [0] Category, [1] Title, [2] Description, [3] Revenue, [5] Price
- Detail page title: `h2.h2-heading-2`
- Detail page price: `h3.h3-heading-2` in `.seller-listing_priceholder`
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime

from .base import BaseScraper, ScraperConfig, ScrapeError, ScrapeResult
from ..models.listing import ListingCreate
from ..config import config, FilterConfig


@dataclass
class ListingCard:
    """Data extracted from a listing card (without clicking through)."""

    url: str
    slug: str
    category: str | None
    title: str | None
    description: str | None
    annual_revenue: int | None  # in cents
    asking_price: int | None  # in cents
    revenue_multiple: float | None

    def passes_filter(
        self,
        min_revenue: int | None = None,
        max_price: int | None = None,
        category_blacklist: list[str] | None = None,
    ) -> bool:
        """Check if this listing passes the given filters.

        Args:
            min_revenue: Minimum annual revenue in cents
            max_price: Maximum asking price in cents
            category_blacklist: List of categories to exclude (case-insensitive)

        Returns:
            True if listing passes all filters.
        """
        if min_revenue and (self.annual_revenue is None or self.annual_revenue < min_revenue):
            return False
        if max_price and (self.asking_price is None or self.asking_price > max_price):
            return False
        if category_blacklist and self.category:
            # Case-insensitive category matching
            blacklist_lower = {c.lower() for c in category_blacklist}
            if self.category.lower() in blacklist_lower:
                return False
        return True


class MicronsScraper(BaseScraper):
    """Scraper for Microns.io marketplace.

    Supports two-phase scraping:
    1. get_listing_cards() - Fast extraction from index page for filtering
    2. scrape_listing() - Full details from individual listing pages
    """

    # URLs discovered via Claude Chrome
    LISTINGS_PATH = "/online-businesses-and-startups-for-sale"
    PAGINATION_PARAM = "c150de50_page"
    CARDS_PER_PAGE = 12

    # Selectors discovered via Claude Chrome
    CARD_SELECTOR = ".listing-card"
    CARD_LINK_SELECTOR = "a[href*='/startup-listings/']"

    # Detail page selectors (updated 2026-01-21 via Claude Chrome)
    DETAIL_TITLE_SELECTOR = "h2.h2-heading-2"
    DETAIL_PRICE_CONTAINER = ".seller-listing_priceholder"
    DETAIL_PRICE_SELECTOR = "h3.h3-heading-2"
    DETAIL_CATEGORY_SELECTOR = ".listing_tag_holder"
    DETAIL_ARR_SELECTOR = "h5.h5-heading-2, h5.h5-heading"  # Value next to "ARR" label

    # Categories observed on the site (full scan 2026-01-21, 350 listings)
    KNOWN_CATEGORIES = [
        "Micro-SaaS",        # 112 (32.0%)
        "Web app",           # 49 (14.0%)
        "Mobile app",        # 39 (11.1%)
        "Newsletter",        # 31 (8.9%)
        "E-commerce",        # 29 (8.3%)
        "Marketplace",       # 14 (4.0%)
        "Directory",         # 12 (3.4%)
        "Browser Extension", # 11 (3.1%)
        "Agency",            # 8 (2.3%)
        "Content",           # 5 (1.4%)
        "Community",         # 5 (1.4%)
    ]

    def __init__(self, headless: bool = True):
        config = ScraperConfig(
            source_id="microns",
            base_url="https://www.microns.io",
            headless=headless,
        )
        super().__init__(config)

    @staticmethod
    def _parse_price(text: str | None) -> int | None:
        """Parse price string like '$54,200' to cents."""
        if not text:
            return None
        # Remove $ and commas, convert to cents
        cleaned = re.sub(r"[^\d.]", "", text)
        if not cleaned:
            return None
        try:
            return int(float(cleaned) * 100)
        except ValueError:
            return None

    # Month names for locale-independent date parsing
    _MONTHS = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    @classmethod
    def _parse_date(cls, date_str: str) -> datetime | None:
        """Parse date string like 'January 11, 2026' in a locale-independent way.

        Args:
            date_str: Date string in "Month DD, YYYY" format.

        Returns:
            datetime object or None if parsing fails.
        """
        try:
            # Split "January 11, 2026" into parts
            parts = date_str.replace(",", "").split()
            if len(parts) != 3:
                return None

            month_name, day_str, year_str = parts
            month = cls._MONTHS.get(month_name.lower())
            if month is None:
                return None

            day = int(day_str)
            year = int(year_str)
            return datetime(year, month, day)
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _validate_listing_data(
        asking_price: int | None,
        annual_revenue: int | None,
        customers: int | None,
        launched_year: int | None,
    ) -> list[str]:
        """Validate scraped data and return list of warnings.

        Returns:
            List of warning strings for suspicious values.
        """
        warnings = []
        current_year = datetime.now().year

        # Price validation
        if asking_price is not None:
            if asking_price < 0:
                warnings.append(f"Negative asking_price: {asking_price}")
            elif asking_price == 0:
                warnings.append("Zero asking_price - possibly free/negotiable")
            elif asking_price > 100_000_000_00:  # > $100M in cents
                warnings.append(f"Unusually high asking_price: ${asking_price/100:,.0f}")

        # Revenue validation
        if annual_revenue is not None:
            if annual_revenue < 0:
                warnings.append(f"Negative annual_revenue: {annual_revenue}")
            elif annual_revenue > 100_000_000_00:  # > $100M in cents
                warnings.append(f"Unusually high annual_revenue: ${annual_revenue/100:,.0f}")

        # Customer count validation
        if customers is not None:
            if customers < 0:
                warnings.append(f"Negative customers: {customers}")
            elif customers > 10_000_000:  # > 10M customers
                warnings.append(f"Unusually high customers: {customers}")

        # Launch year validation
        if launched_year is not None:
            if launched_year < 1990:
                warnings.append(f"Suspiciously old launched_year: {launched_year}")
            elif launched_year > current_year + 1:
                warnings.append(f"Future launched_year: {launched_year}")

        return warnings

    async def _extract_cards_from_page(self) -> list[ListingCard]:
        """Extract listing cards from the current page.

        Returns:
            List of ListingCard objects from the current page.
        """
        cards = await self.page.query_selector_all(self.CARD_SELECTOR)
        results = []

        for card in cards:
            # Get URL from link
            link = await card.query_selector(self.CARD_LINK_SELECTOR)
            if not link:
                continue

            href = await link.get_attribute("href")
            if not href:
                continue

            # Make absolute URL
            if href.startswith("/"):
                url = f"{self.config.base_url}{href}"
            else:
                url = href

            slug = href.split("/")[-1]

            # Parse card text - use label detection instead of fragile indices
            text = await card.inner_text()
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            # Find category by matching against known categories (case-insensitive)
            category = None
            category_lower_map = {c.lower(): c for c in self.KNOWN_CATEGORIES}
            for line in lines:
                if line.lower() in category_lower_map:
                    category = category_lower_map[line.lower()]
                    break

            # Title is typically the first non-category line, or first line if no category found
            title = None
            description = None
            for i, line in enumerate(lines):
                # Skip if it's a category, label, or price
                if line.lower() in category_lower_map:
                    continue
                if line in ("Annual Revenue", "Asking Price"):
                    continue
                if line.startswith("$"):
                    continue
                # First qualifying line is title
                if title is None:
                    title = line
                elif description is None:
                    # Second qualifying line is description
                    description = line
                    break

            # Find revenue and price by looking for values BEFORE their labels
            annual_revenue = None
            asking_price = None
            for i, line in enumerate(lines):
                if line == "Annual Revenue" and i > 0:
                    annual_revenue = self._parse_price(lines[i - 1])
                elif line == "Asking Price" and i > 0:
                    asking_price = self._parse_price(lines[i - 1])

            # Calculate multiple
            revenue_multiple = None
            if annual_revenue and asking_price and annual_revenue > 0:
                revenue_multiple = (asking_price / annual_revenue)

            results.append(ListingCard(
                url=url,
                slug=slug,
                category=category,
                title=title,
                description=description,
                annual_revenue=annual_revenue,
                asking_price=asking_price,
                revenue_multiple=revenue_multiple,
            ))

        return results

    async def get_listing_cards(
        self, max_pages: int | None = None, verbose: bool = False
    ) -> list[ListingCard]:
        """Extract listing data from all pages of the listings index.

        This is fast and doesn't require clicking through to each listing.
        Use this data to filter before scraping full details.

        Args:
            max_pages: Optional limit on pages to scrape. None = all pages.
            verbose: If True, print progress messages.

        Returns:
            List of ListingCard objects with basic info.
        """
        listings_url = f"{self.config.base_url}{self.LISTINGS_PATH}"
        all_cards = []
        page_num = 1  # Pagination is 1-indexed
        seen_slugs = set()  # Track duplicates

        while True:
            # Build URL for current page (page 1 = no param or ?page=1, both work)
            if page_num == 1:
                url = listings_url
            else:
                url = f"{listings_url}?{self.PAGINATION_PARAM}={page_num}"

            await self.page.goto(url)
            await self.page.wait_for_load_state("domcontentloaded")

            # Check if cards exist on this page
            try:
                await self.page.wait_for_selector(self.CARD_SELECTOR, timeout=5000)
            except Exception:
                # No cards found - we've reached the end
                break

            # Extract cards from this page
            page_cards = await self._extract_cards_from_page()

            if not page_cards:
                # Empty page - we've reached the end
                break

            # Add new cards (avoid duplicates)
            new_count = 0
            for card in page_cards:
                if card.slug not in seen_slugs:
                    seen_slugs.add(card.slug)
                    all_cards.append(card)
                    new_count += 1

            if verbose:
                print(f"Page {page_num}: {len(page_cards)} cards ({new_count} new, {len(all_cards)} total)")

            # Check if we should stop due to max_pages
            if max_pages and page_num >= max_pages:
                break

            # Check if there's a next page
            next_page_selector = f"a[href*='{self.PAGINATION_PARAM}={page_num + 1}']"
            next_page_link = await self.page.query_selector(next_page_selector)
            if not next_page_link:
                break
            page_num += 1

        return all_cards

    async def get_listing_urls(self) -> list[str]:
        """Get all listing URLs from Microns.io.

        Returns:
            List of listing URLs.
        """
        cards = await self.get_listing_cards()
        return [card.url for card in cards]

    async def scrape_listing(self, url: str) -> ListingCreate:
        """Extract full data from a single Microns.io listing page.

        Args:
            url: URL of the listing.

        Returns:
            Extracted listing data.
        """
        await self.page.goto(url)
        await self.page.wait_for_load_state("domcontentloaded")
        # Wait for title to appear
        await self.page.wait_for_selector(self.DETAIL_TITLE_SELECTOR, timeout=10000)

        # Extract external ID from URL
        external_id = url.split("/")[-1]

        # Extract title
        title = None
        title_el = await self.page.query_selector(self.DETAIL_TITLE_SELECTOR)
        if title_el:
            title = await title_el.inner_text()

        # Extract asking price from sidebar
        asking_price = None
        price_container = await self.page.query_selector(self.DETAIL_PRICE_CONTAINER)
        if price_container:
            price_el = await price_container.query_selector(self.DETAIL_PRICE_SELECTOR)
            if price_el:
                price_text = await price_el.inner_text()
                asking_price = self._parse_price(price_text)

        # Extract category from tag holder
        category = None
        category_el = await self.page.query_selector(self.DETAIL_CATEGORY_SELECTOR)
        if category_el:
            category = await category_el.inner_text()
            category = category.strip() if category else None

        # Extract metrics from h5 headings (ARR, Customers, Launched)
        arr = None
        customers = None
        launched_year = None
        metric_elements = await self.page.query_selector_all(self.DETAIL_ARR_SELECTOR)
        for el in metric_elements:
            parent = await el.evaluate_handle("el => el.parentElement")
            parent_text = await parent.evaluate("el => el.innerText")
            el_text = await el.inner_text()

            if "ARR" in parent_text and arr is None:
                arr = self._parse_price(el_text)
            elif "Customers" in parent_text and customers is None:
                # Parse customer count (e.g., "74")
                try:
                    customers = int(re.sub(r"[^\d]", "", el_text))
                except ValueError:
                    pass
            elif "Launched" in parent_text and launched_year is None:
                # Parse launch year (e.g., "2024")
                try:
                    launched_year = int(re.sub(r"[^\d]", "", el_text))
                except ValueError:
                    pass

        # Extract posted date from "Published on" section
        posted_at = None
        date_holder = await self.page.query_selector(".listing_date-holder")
        if date_holder:
            date_text = await date_holder.inner_text()
            # Parse "Published on\nJanuary 11, 2026" format
            if "Published on" in date_text:
                date_str = date_text.replace("Published on", "").strip()
                posted_at = self._parse_date(date_str)

        # Extract description - p element after "Startup description" label
        description = None
        desc_label = await self.page.query_selector("p:has-text('Startup description')")
        if desc_label:
            desc_el = await desc_label.evaluate_handle("el => el.nextElementSibling")
            if desc_el:
                description = await desc_el.evaluate("el => el.innerText")
        # Fallback: try tagline below title
        if not description:
            tagline_el = await self.page.query_selector("div.body-text.opacity70")
            if tagline_el:
                description = await tagline_el.inner_text()

        # Validate extracted data
        validation_warnings = self._validate_listing_data(
            asking_price=asking_price,
            annual_revenue=arr,
            customers=customers,
            launched_year=launched_year,
        )

        # Collect raw data for debugging/analysis
        raw_data = {
            "url": url,
            "title": title,
            "category": category,
            "asking_price_cents": asking_price,
            "arr_cents": arr,
            "customers": customers,
            "launched_year": launched_year,
            "posted_at": posted_at.isoformat() if posted_at else None,
            "validation_warnings": validation_warnings if validation_warnings else None,
        }

        return ListingCreate(
            source_id=self.config.source_id,
            external_id=external_id,
            url=url,
            title=title,
            category=category,
            asking_price=asking_price,
            annual_revenue=arr,  # Store ARR directly (12-month figure)
            customers=customers,
            launched_year=launched_year,
            posted_at=posted_at,
            description=description,
            raw_data=raw_data,
        )

    async def scrape_with_filter(
        self,
        filters: FilterConfig | None = None,
        max_pages: int | None = None,
    ) -> tuple[ScrapeResult, list[ListingCard]]:
        """Scrape listings that pass filters, track skipped ones.

        Args:
            filters: Filter configuration (uses central config.filters if None)
            max_pages: Optional limit on pages to scan

        Returns:
            Tuple of (ScrapeResult with listings/errors, skipped cards).
        """
        # Use central config filters if none provided
        if filters is None:
            filters = config.filters

        await self.setup()
        try:
            # Phase 1: Get all cards
            cards = await self.get_listing_cards(max_pages=max_pages)

            # Phase 2: Filter
            to_scrape = []
            skipped = []
            for card in cards:
                if card.passes_filter(
                    min_revenue=filters.min_annual_revenue,
                    max_price=filters.max_asking_price,
                    category_blacklist=filters.category_blacklist,
                ):
                    to_scrape.append(card)
                else:
                    skipped.append(card)

            # Phase 3: Scrape passing listings with rate limiting
            result = ScrapeResult()
            for card in to_scrape:
                try:
                    listing = await self.scrape_listing(card.url)
                    result.listings.append(listing)
                except Exception as e:
                    result.errors.append(ScrapeError.from_exception(card.url, e))
                # Be polite to the server
                await asyncio.sleep(config.request_delay_seconds)

            return result, skipped
        finally:
            await self.teardown()
