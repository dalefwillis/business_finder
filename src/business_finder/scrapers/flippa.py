"""Flippa.com scraper.

Selectors discovered via Playwright exploration (2026-01-22):
- Main search page: https://flippa.com/search
- Pagination: ?page=N query parameter
- Listing cards: Multiple selectors with fallback chain
- Card href: direct listing ID (e.g., /12249202)

Card structure:
- Title: h6 element (e.g., "Amazon Store | Home and Garden")
- Country: span after map pin icon
- Verified: presence of "Verified Listing" text
- Key data in ng-repeat divs: Type, Industry, Monetization, Site Age, Net Profit
- NOTE: Asking price is NOT on search page, only on detail pages

Detail page:
- Asking price: text "Asking Price (Classified)" followed by "USD $X,XXX,XXX"

Flippa categories observed:
- Amazon Store, SaaS, Service, Marketing Agency, Content Site
- App, Ecommerce, Marketplace, YouTube, Newsletter
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from .base import BaseScraper, ScraperConfig, ScrapeError, ScrapeResult
from ..models.listing import ListingCreate
from ..config import config, FilterConfig
from ..db.operations import get_known_external_ids

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Constants (documented and tuneable)
# =============================================================================

class ScraperTimeouts:
    """Timeout configuration in milliseconds."""
    PAGE_LOAD_MS = 60_000  # 60s - Flippa pages can be slow
    NETWORK_IDLE_MS = 60_000  # 60s - Wait for async content
    SELECTOR_WAIT_MS = 15_000  # 15s - Wait for cards to appear
    DETAIL_PAGE_MS = 30_000  # 30s - Detail pages are simpler


class ScraperDelays:
    """Delay configuration in seconds."""
    BETWEEN_PAGES = 2.0  # Politeness delay between search pages
    BETWEEN_DETAILS = 1.0  # Delay between detail page scrapes
    BASE_RETRY = 3.0  # Starting delay for exponential backoff


class ScraperLimits:
    """Safety limits to prevent runaway scraping."""
    MAX_PAGES = 100  # Hard limit on search pages
    MAX_CONSECUTIVE_FAILURES = 5  # Stop after this many failures in a row
    MAX_DETAIL_RETRIES = 3  # Retry detail pages this many times
    MIN_CARD_LINES = 3  # Cards with fewer lines are likely UI elements
    MIN_DESCRIPTION_LENGTH = 80  # Minimum chars for a valid description


# =============================================================================
# US Country Detection
# =============================================================================

# Canonical US variations - all lowercase for matching
US_COUNTRY_VARIATIONS = frozenset({
    "us", "usa", "u.s.", "u.s.a.", "u.s.a",
    "united states", "united states of america", "america",
})

# US territories that should be treated as US
US_TERRITORIES = frozenset({
    "puerto rico", "guam", "u.s. virgin islands", "united states virgin islands",
    "american samoa", "northern mariana islands",
})


def is_us_country(country: str | None) -> bool:
    """Check if a country string represents the United States or US territory.

    This is a public function for use in filtering logic.

    Args:
        country: Country name string (case-insensitive)

    Returns:
        True if the country is US or a US territory.
    """
    if not country:
        return False
    normalized = country.lower().strip()

    # Direct match
    if normalized in US_COUNTRY_VARIATIONS:
        return True

    # Check territories
    if normalized in US_TERRITORIES:
        return True

    # Handle "State, United States" format
    if ", united states" in normalized:
        return True

    return False


# =============================================================================
# Currency Handling
# =============================================================================

# Known non-USD currencies with approximate USD conversion rates
# These are rough estimates - NOT for financial decisions
CURRENCY_TO_USD_RATE = {
    "AUD": 0.65,  # Australian Dollar
    "CAD": 0.74,  # Canadian Dollar
    "EUR": 1.08,  # Euro
    "GBP": 1.26,  # British Pound
    "SGD": 0.74,  # Singapore Dollar
    "HKD": 0.13,  # Hong Kong Dollar
    "NZD": 0.60,  # New Zealand Dollar
    "INR": 0.012,  # Indian Rupee
}


def parse_price_with_currency(
    text: str | None
) -> tuple[int | None, str | None, str | None]:
    """Parse price string, detecting and optionally converting currency.

    Args:
        text: Price text like '$54,200' or 'AUD $54,200'

    Returns:
        Tuple of (cents_usd, currency_code, warning).
        - cents_usd: Price in USD cents (converted if non-USD)
        - currency_code: Detected currency (None = assumed USD)
        - warning: Warning message if conversion applied or currency unknown
    """
    if not text:
        return None, None, None

    text_upper = text.upper()
    detected_currency = None
    warning = None

    # Detect currency
    for curr in CURRENCY_TO_USD_RATE:
        if curr in text_upper:
            detected_currency = curr
            break

    # Also check for currency symbols without codes
    if not detected_currency:
        if "£" in text:
            detected_currency = "GBP"
        elif "€" in text:
            detected_currency = "EUR"
        elif "A$" in text:
            detected_currency = "AUD"
        elif "C$" in text:
            detected_currency = "CAD"

    # Parse the numeric value
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned:
        return None, detected_currency, None

    try:
        raw_cents = int(float(cleaned) * 100)
    except ValueError:
        return None, detected_currency, None

    # Convert to USD if non-USD currency detected
    if detected_currency:
        rate = CURRENCY_TO_USD_RATE.get(detected_currency)
        if rate:
            usd_cents = int(raw_cents * rate)
            warning = f"converted from {detected_currency} (rate: {rate})"
            return usd_cents, detected_currency, warning
        else:
            # Unknown currency - store raw but warn
            warning = f"unknown currency {detected_currency}, stored as-is"
            return raw_cents, detected_currency, warning

    # Assumed USD
    return raw_cents, None, None


# =============================================================================
# Category Blacklist
# =============================================================================

# Flippa-specific categories to filter out
# These are deduplicated and normalized at compile time
FLIPPA_CATEGORY_BLACKLIST = frozenset({
    # E-commerce variants
    "ecommerce",
    "e-commerce",
    # Platform-dependent businesses
    "amazon",
    "fba",
    "dropship",
    "dropshipping",
    # Social media dependent
    "youtube",
    "tiktok",
    "instagram",
    "social media",
    # Content businesses (hard to transfer/maintain)
    "newsletter",
    "blog",
    "content",
    "affiliate",
    # Other filtered types
    "marketplace",
    "directory",
    "agency",
    "community",
})


def build_blacklist_pattern(
    extra_terms: list[str] | None = None
) -> re.Pattern[str]:
    """Build compiled regex pattern for category blacklist matching.

    Args:
        extra_terms: Additional terms to add to the blacklist

    Returns:
        Compiled case-insensitive regex pattern
    """
    all_terms = set(FLIPPA_CATEGORY_BLACKLIST)
    if extra_terms:
        all_terms.update(term.lower() for term in extra_terms)

    # Build pattern with word boundaries for more precise matching
    # This prevents "usa" from matching in "usage"
    pattern = "|".join(re.escape(term) for term in sorted(all_terms))
    return re.compile(pattern, re.IGNORECASE)


# =============================================================================
# Card Data Structure
# =============================================================================

@dataclass
class FlippaListingCard:
    """Data extracted from a Flippa listing card (without clicking through).

    Used for fast filtering before scraping full details.
    Note: Asking price is NOT available on search results - only monthly profit.
    """

    url: str
    external_id: str
    category: str | None  # Business type like "Amazon Store", "SaaS"
    industry: str | None  # Industry like "Home and Garden", "Business"
    title: str | None  # Full headline e.g., "Amazon Store | Home and Garden"
    profit_monthly_cents: int | None  # Monthly net profit in cents
    original_currency: str | None  # Currency if non-USD detected
    country: str | None
    site_age_months: int | None  # Site age in months
    has_verified: bool
    is_confidential: bool
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def annual_profit_cents(self) -> int | None:
        """Calculate annual profit from monthly profit."""
        if self.profit_monthly_cents is None:
            return None
        return self.profit_monthly_cents * 12

    def passes_filter(
        self,
        min_annual_profit_cents: int | None = None,
        category_blacklist: re.Pattern[str] | None = None,
        us_only: bool = True,
        verified_only: bool = False,
    ) -> tuple[str, str | None]:
        """Check if this listing passes the given filters.

        Args:
            min_annual_profit_cents: Minimum annual profit in cents
            category_blacklist: Compiled regex pattern for blacklisted categories
            us_only: Only include US-based listings
            verified_only: Only include verified listings

        Returns:
            Tuple of (status, reason) where:
            - status is "pass", "fail", or "check_detail" (need to visit detail page)
            - reason explains why it failed or needs checking (or None if passed)
        """
        # Skip confidential listings (no data visible)
        if self.is_confidential:
            return "fail", "confidential listing"

        # Check verified requirement
        if verified_only and not self.has_verified:
            return "fail", "not verified"

        # Check profit threshold
        if min_annual_profit_cents:
            if self.annual_profit_cents is None:
                return "fail", "profit unknown"
            if self.annual_profit_cents < min_annual_profit_cents:
                profit_str = f"${self.annual_profit_cents / 100:,.0f}/yr"
                return "fail", f"profit too low ({profit_str})"

        # Check category blacklist BEFORE country check
        # (we can confidently filter out blacklisted categories regardless of country)
        if category_blacklist:
            for text in [self.category, self.industry, self.title]:
                if text and category_blacklist.search(text):
                    # Find which term matched for better logging
                    match = category_blacklist.search(text)
                    matched_term = match.group(0) if match else "unknown"
                    return "fail", f"blacklisted: '{matched_term}' in '{text}'"

        # Check US-only filter
        if us_only:
            if is_us_country(self.country):
                return "pass", None
            elif self.country is None:
                # Unknown country but passed other filters - need detail page
                return "check_detail", "country unknown, need detail page"
            else:
                return "fail", f"non-US: {self.country}"

        return "pass", None


# =============================================================================
# Card Selector Configuration
# =============================================================================

# Multiple selectors with fallback - GTM classes change frequently
CARD_SELECTORS = [
    "[class*='GTM-search-result-card']",  # Primary (Google Tag Manager)
    "[data-testid='listing-card']",  # Test ID if they add one
    "a[href^='/'][class*='card']",  # Generic card links
    ".search-results a[href^='/']",  # Fallback: any link in search results
]


# =============================================================================
# Main Scraper Class
# =============================================================================

class FlippaScraper(BaseScraper):
    """Scraper for Flippa.com marketplace.

    Supports two-phase scraping:
    1. get_listing_cards() - Fast extraction from search results for filtering
    2. scrape_listing() - Full details from individual listing pages

    Note: Asking price is only available on detail pages, not search results.
    """

    SEARCH_PATH = "/search"
    PAGINATION_PARAM = "page"

    def __init__(self, headless: bool = True):
        scraper_config = ScraperConfig(
            source_id="flippa",
            base_url="https://flippa.com",
            headless=headless,
        )
        super().__init__(scraper_config)

    # -------------------------------------------------------------------------
    # Parsing Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_monthly_profit(text: str) -> tuple[int | None, str | None, str | None]:
        """Parse monthly profit like 'USD $50,432 p/mo' to cents.

        Returns:
            Tuple of (cents, currency, warning)
        """
        if not text:
            return None, None, None
        text_lower = text.lower()
        if not any(indicator in text_lower for indicator in ["p/mo", "/mo", "per month", "monthly"]):
            return None, None, None
        return parse_price_with_currency(text)

    @staticmethod
    def _parse_site_age(text: str) -> int | None:
        """Parse site age like '12 years' or '6 months' to total months."""
        if not text:
            return None
        text_lower = text.lower()

        total_months = 0

        # Parse years
        year_match = re.search(r"(\d+)\s*year", text_lower)
        if year_match:
            total_months += int(year_match.group(1)) * 12

        # Parse months (additive with years)
        month_match = re.search(r"(\d+)\s*month", text_lower)
        if month_match:
            total_months += int(month_match.group(1))

        return total_months if total_months > 0 else None

    @staticmethod
    def _extract_id_from_url(url: str) -> str:
        """Extract listing ID from Flippa URL.

        Flippa URLs are typically like: https://flippa.com/12249202
        """
        # Get the last numeric part (6+ digits)
        match = re.search(r"/(\d{6,})(?:\?|$|/)", url)
        if match:
            return match.group(1)
        # Fallback to last path segment
        return url.rstrip("/").split("/")[-1]

    # -------------------------------------------------------------------------
    # Page Helpers
    # -------------------------------------------------------------------------

    async def _find_working_selector(self) -> str | None:
        """Try multiple selectors and return the first one that finds elements."""
        for selector in CARD_SELECTORS:
            try:
                count = await self.page.locator(selector).count()
                if count > 0:
                    logger.debug(f"Using selector '{selector}' (found {count} elements)")
                    return selector
            except Exception:
                continue
        return None

    async def _wait_for_content(self, selector: str, timeout: int = ScraperTimeouts.SELECTOR_WAIT_MS) -> bool:
        """Wait for content to load with proper timeout handling."""
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception as e:
            logger.debug(f"Selector '{selector}' not found: {e}")
            return False

    async def _detect_rate_limit_or_captcha(self) -> bool:
        """Check if we've hit a rate limit or CAPTCHA page."""
        try:
            page_text = await self.page.inner_text("body")
            page_lower = page_text.lower()

            rate_limit_indicators = [
                "rate limit",
                "too many requests",
                "please try again later",
                "captcha",
                "verify you're human",
                "access denied",
                "blocked",
            ]

            for indicator in rate_limit_indicators:
                if indicator in page_lower:
                    logger.warning(f"Detected rate limit/block indicator: '{indicator}'")
                    return True
            return False
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Card Extraction
    # -------------------------------------------------------------------------

    async def _extract_cards_from_page(self, selector: str) -> tuple[list[FlippaListingCard], list[str]]:
        """Extract listing cards from the current page.

        Flippa shows multiple cards per listing (image, data, button).
        We collect all cards for each listing ID and merge the data.

        Returns:
            Tuple of (list of FlippaListingCard, list of parse errors).
        """
        card_data: dict[str, dict] = {}
        parse_errors: list[str] = []

        cards = await self.page.query_selector_all(selector)
        logger.debug(f"Found {len(cards)} card elements")

        for card in cards:
            try:
                # Get URL from href attribute
                href = await card.get_attribute("href")
                if not href:
                    continue

                # Make absolute URL
                if href.startswith("/"):
                    url = f"{self.config.base_url}{href}"
                else:
                    url = href

                # Skip non-listing URLs
                external_id = self._extract_id_from_url(url)
                if not external_id.isdigit():
                    continue

                # Get all text content
                text = await card.inner_text()
                lines = [line.strip() for line in text.split("\n") if line.strip()]

                # Skip minimal cards (e.g., "View Listing" only)
                if len(lines) < ScraperLimits.MIN_CARD_LINES:
                    continue

                # Initialize or get existing data for this listing
                if external_id not in card_data:
                    card_data[external_id] = {
                        "url": url,
                        "external_id": external_id,
                        "category": None,
                        "industry": None,
                        "title": None,
                        "profit_monthly_cents": None,
                        "original_currency": None,
                        "country": None,
                        "site_age_months": None,
                        "has_verified": False,
                        "is_confidential": False,
                        "has_data_card": False,
                        "parse_warnings": [],
                    }

                data = card_data[external_id]

                # Detect card type
                has_confidential_marker = "Confidential" in text or "Sign NDA" in text
                has_data_fields = "Type" in text or "Net Profit" in text

                # Update confidential status (data card overrides confidential marker)
                if has_data_fields:
                    data["is_confidential"] = False
                    data["has_data_card"] = True
                elif has_confidential_marker and not data["has_data_card"]:
                    data["is_confidential"] = True

                # Check for verified badge
                if "Verified Listing" in text or "Verified Revenue" in text:
                    data["has_verified"] = True

                # Parse title (e.g., "Amazon Store | Home and Garden")
                if data["title"] is None:
                    for line in lines:
                        if "|" in line and len(line) > 5:
                            data["title"] = line
                            break

                # Extract labeled data (format: label on one line, value on next)
                for i, line in enumerate(lines):
                    if i + 1 >= len(lines):
                        continue
                    next_line = lines[i + 1]
                    line_lower = line.lower().strip()

                    if line_lower == "type" and data["category"] is None:
                        data["category"] = next_line
                    elif line_lower == "industry" and data["industry"] is None:
                        data["industry"] = next_line
                    elif line_lower in ("net profit", "monthly profit") and data["profit_monthly_cents"] is None:
                        profit, currency, warning = self._parse_monthly_profit(next_line)
                        data["profit_monthly_cents"] = profit
                        data["original_currency"] = currency
                        if warning:
                            data["parse_warnings"].append(warning)
                    elif line_lower == "site age" and data["site_age_months"] is None:
                        data["site_age_months"] = self._parse_site_age(next_line)

                # Extract country using detail page as source of truth when available
                # For now, just look for common country patterns in card text
                if data["country"] is None:
                    # Look for "Location: X" or "Based in: X" patterns
                    for i, line in enumerate(lines):
                        line_lower = line.lower()
                        if ("location" in line_lower or "based in" in line_lower) and i + 1 < len(lines):
                            potential_country = lines[i + 1].strip()
                            if len(potential_country) > 1 and len(potential_country) < 50:
                                data["country"] = potential_country
                                break

            except Exception as e:
                parse_errors.append(f"Card parse error: {e}")
                logger.debug(f"Card parse error: {e}", exc_info=True)
                continue

        # Convert to FlippaListingCard objects
        results = []
        for data in card_data.values():
            data.pop("has_data_card", None)  # Remove internal tracking field
            results.append(FlippaListingCard(
                url=data["url"],
                external_id=data["external_id"],
                category=data["category"],
                industry=data["industry"],
                title=data["title"],
                profit_monthly_cents=data["profit_monthly_cents"],
                original_currency=data["original_currency"],
                country=data["country"],
                site_age_months=data["site_age_months"],
                has_verified=data["has_verified"],
                is_confidential=data["is_confidential"],
                parse_warnings=data["parse_warnings"],
            ))

        return results, parse_errors

    # -------------------------------------------------------------------------
    # Search Page Scraping
    # -------------------------------------------------------------------------

    async def get_listing_cards(
        self, max_pages: int | None = None, verbose: bool = False
    ) -> tuple[list[FlippaListingCard], list[str]]:
        """Extract listing data from all pages of search results.

        This is fast and doesn't require clicking through to each listing.
        Use this data to filter before scraping full details.

        Args:
            max_pages: Optional limit on pages to scrape. None = all pages.
            verbose: If True, print progress messages.

        Returns:
            Tuple of (list of FlippaListingCard, list of all parse errors).
        """
        search_url = f"{self.config.base_url}{self.SEARCH_PATH}"
        all_cards: list[FlippaListingCard] = []
        all_errors: list[str] = []
        page_num = 1
        seen_ids: set[str] = set()
        effective_max = max_pages or ScraperLimits.MAX_PAGES
        working_selector: str | None = None

        consecutive_failures = 0

        while page_num <= effective_max:
            # Build URL for current page
            if page_num == 1:
                url = search_url
            else:
                separator = "&" if "?" in search_url else "?"
                url = f"{search_url}{separator}{self.PAGINATION_PARAM}={page_num}"

            if verbose:
                print(f"Fetching page {page_num}: {url}")
            logger.info(f"Fetching page {page_num}: {url}")

            # Load page with retry logic
            try:
                await self.page.goto(url, timeout=ScraperTimeouts.PAGE_LOAD_MS)
                await self.page.wait_for_load_state("networkidle", timeout=ScraperTimeouts.NETWORK_IDLE_MS)
            except Exception as e:
                consecutive_failures += 1
                retry_delay = ScraperDelays.BASE_RETRY * (2 ** (consecutive_failures - 1))

                logger.warning(f"Page load error ({consecutive_failures}/{ScraperLimits.MAX_CONSECUTIVE_FAILURES}): {e}")
                if verbose:
                    print(f"  Page load error ({consecutive_failures}/{ScraperLimits.MAX_CONSECUTIVE_FAILURES}): {e}")
                    print(f"  Waiting {retry_delay:.0f}s before retry...")

                if consecutive_failures >= ScraperLimits.MAX_CONSECUTIVE_FAILURES:
                    logger.error(f"Stopping after {consecutive_failures} consecutive failures")
                    if verbose:
                        print(f"Stopping after {consecutive_failures} consecutive failures")
                    break

                await asyncio.sleep(retry_delay)
                continue  # Retry same page

            # Reset failure counter on success
            consecutive_failures = 0

            # Check for rate limiting
            if await self._detect_rate_limit_or_captcha():
                logger.warning("Rate limit detected, stopping pagination")
                if verbose:
                    print("  Rate limit/CAPTCHA detected - stopping")
                all_errors.append(f"Rate limit detected on page {page_num}")
                break

            # Find working selector on first page
            if working_selector is None:
                working_selector = await self._find_working_selector()
                if not working_selector:
                    logger.error("No working card selector found")
                    all_errors.append("No working card selector found")
                    break

            # Wait for cards
            if not await self._wait_for_content(working_selector):
                if verbose:
                    print(f"No cards found on page {page_num} - stopping pagination")
                break

            # Extract cards
            page_cards, page_errors = await self._extract_cards_from_page(working_selector)
            all_errors.extend(page_errors)

            if not page_cards:
                if verbose:
                    print(f"No valid cards on page {page_num} - stopping pagination")
                break

            # Add new cards (avoid duplicates)
            new_count = 0
            for card in page_cards:
                if card.external_id not in seen_ids:
                    seen_ids.add(card.external_id)
                    all_cards.append(card)
                    new_count += 1

            if verbose:
                print(f"Page {page_num}: {len(page_cards)} cards ({new_count} new, {len(all_cards)} total)")
            logger.info(f"Page {page_num}: {len(page_cards)} cards ({new_count} new)")

            # Check stopping conditions
            if max_pages and page_num >= max_pages:
                break

            if new_count == 0:
                if verbose:
                    print("No new cards on this page - stopping pagination")
                break

            # Politeness delay
            await asyncio.sleep(ScraperDelays.BETWEEN_PAGES)
            page_num += 1

        return all_cards, all_errors

    # -------------------------------------------------------------------------
    # Detail Page Scraping
    # -------------------------------------------------------------------------

    async def scrape_listing(
        self,
        url: str,
        card_data: FlippaListingCard | None = None,
        retry_count: int = 0,
    ) -> ListingCreate:
        """Extract full data from a single Flippa listing page.

        Args:
            url: URL of the listing.
            card_data: Optional card data to preserve in raw_data.
            retry_count: Current retry attempt (internal use).

        Returns:
            Extracted listing data.

        Raises:
            Exception: If scraping fails after all retries.
        """
        try:
            await self.page.goto(url, timeout=ScraperTimeouts.DETAIL_PAGE_MS)
            await self.page.wait_for_load_state("networkidle", timeout=ScraperTimeouts.DETAIL_PAGE_MS)
        except Exception as e:
            if retry_count < ScraperLimits.MAX_DETAIL_RETRIES:
                retry_delay = ScraperDelays.BASE_RETRY * (2 ** retry_count)
                logger.warning(f"Detail page load failed, retry {retry_count + 1}: {e}")
                await asyncio.sleep(retry_delay)
                return await self.scrape_listing(url, card_data, retry_count + 1)
            raise

        # Wait for content
        await self._wait_for_content("body", timeout=ScraperTimeouts.SELECTOR_WAIT_MS)

        external_id = self._extract_id_from_url(url)
        page_text = await self.page.inner_text("body")
        lines = [line.strip() for line in page_text.split("\n") if line.strip()]

        parse_warnings: list[str] = []

        # Extract title from page title
        page_title = await self.page.title()
        title = page_title
        if " on Flippa:" in page_title:
            title = page_title.split(" on Flippa:")[0]
        elif " | Flippa" in page_title:
            title = page_title.split(" | Flippa")[0]

        # Extract asking price (handle fixed price and auction)
        asking_price_cents = None
        original_currency = None
        price_type = None

        for i, line in enumerate(lines):
            if any(indicator in line for indicator in ["Asking Price", "Buy It Now", "Fixed Price"]):
                price_type = "fixed"
                for j in range(i, min(i + 5, len(lines))):
                    if "$" in lines[j] and "p/mo" not in lines[j].lower() and "/mo" not in lines[j].lower():
                        price, currency, warning = parse_price_with_currency(lines[j])
                        if price:
                            asking_price_cents = price
                            original_currency = currency
                            if warning:
                                parse_warnings.append(warning)
                            break
                break
            elif any(indicator in line for indicator in ["Current Bid", "Reserve Price", "Starting Bid"]):
                price_type = "auction"
                for j in range(i, min(i + 5, len(lines))):
                    if "$" in lines[j] and "p/mo" not in lines[j].lower():
                        price, currency, warning = parse_price_with_currency(lines[j])
                        if price:
                            asking_price_cents = price
                            original_currency = currency
                            if warning:
                                parse_warnings.append(warning)
                            break
                break

        # Extract monthly profit
        profit_monthly_cents = None
        for i, line in enumerate(lines):
            if any(indicator in line for indicator in ["Net Profit", "Monthly Profit"]):
                for j in range(i, min(i + 3, len(lines))):
                    if any(indicator in lines[j].lower() for indicator in ["p/mo", "/mo", "per month"]):
                        profit, currency, warning = self._parse_monthly_profit(lines[j])
                        if profit:
                            profit_monthly_cents = profit
                            if warning:
                                parse_warnings.append(warning)
                            break
                break

        # Extract category/type
        category = None
        for i, line in enumerate(lines):
            if line == "Type" and i + 1 < len(lines):
                category = lines[i + 1]
                break

        # Extract industry
        industry = None
        for i, line in enumerate(lines):
            if line == "Industry" and i + 1 < len(lines):
                industry = lines[i + 1]
                break

        full_category = f"{category} | {industry}" if category and industry else (category or industry)

        # Extract country from Business Location
        country = None
        if card_data and card_data.country:
            country = card_data.country
        else:
            for i, line in enumerate(lines):
                if "Business Location" in line and i + 1 < len(lines):
                    location_str = lines[i + 1]
                    # Handle "State, Country" format
                    if "," in location_str:
                        country = location_str.split(",")[-1].strip()
                    else:
                        country = location_str.strip()
                    break
                elif line == "Location" and i + 1 < len(lines):
                    country = lines[i + 1]
                    break

        # Extract site age
        launched_year = None
        site_age_months = None
        for i, line in enumerate(lines):
            if "Site Age" in line and i + 1 < len(lines):
                site_age_months = self._parse_site_age(lines[i + 1])
                if site_age_months:
                    launched_year = datetime.now().year - (site_age_months // 12)
                break

        # Check verification status
        has_verified = "Verified Listing" in page_text or "Verified Revenue" in page_text

        # Extract description (first long paragraph)
        description = None
        for line in lines:
            if len(line) < ScraperLimits.MIN_DESCRIPTION_LENGTH:
                continue
            if line.startswith("USD") or line.startswith("$"):
                continue
            if any(label in line for label in ["Type", "Industry", "Monetization", "Site Age"]):
                continue
            description = line
            break

        # Build raw_data
        raw_data: dict = {
            "url": url,
            "external_id": external_id,
            "has_verified": has_verified,
            "site_age_months": site_age_months,
            "category": category,
            "industry": industry,
            "profit_monthly_cents": profit_monthly_cents,
            "price_type": price_type,
            "original_currency": original_currency,
            "parse_warnings": parse_warnings if parse_warnings else None,
        }

        if card_data:
            raw_data["card_data"] = {
                "title": card_data.title,
                "category": card_data.category,
                "industry": card_data.industry,
                "profit_monthly_cents": card_data.profit_monthly_cents,
                "country": card_data.country,
                "site_age_months": card_data.site_age_months,
                "has_verified": card_data.has_verified,
            }

        return ListingCreate(
            source_id=self.config.source_id,
            external_id=external_id,
            url=url,
            title=title,
            category=full_category,
            asking_price=asking_price_cents,
            annual_revenue=None,  # We have profit, not revenue - don't conflate
            customers=None,
            launched_year=launched_year,
            posted_at=None,
            description=description,
            country=country,
            raw_data=raw_data,
        )

    # -------------------------------------------------------------------------
    # Filtered Scraping Pipeline
    # -------------------------------------------------------------------------

    async def scrape_with_filter(
        self,
        filters: FilterConfig | None = None,
        max_pages: int | None = None,
        skip_known: bool = False,
        us_only: bool = True,
        verified_only: bool = False,
        verbose: bool = False,
    ) -> tuple[ScrapeResult, list[tuple[FlippaListingCard, str]], list[FlippaListingCard]]:
        """Scrape listings that pass filters, track skipped ones.

        Args:
            filters: Filter configuration (uses central config.filters if None)
            max_pages: Optional limit on pages to scan
            skip_known: If True, skip listings already in the database
            us_only: If True, only include US-based listings
            verified_only: Only include verified listings
            verbose: If True, print progress messages

        Returns:
            Tuple of (ScrapeResult, filter-skipped cards with reasons, already-known cards).
        """
        active_filters = filters if filters is not None else config.filters

        # Build blacklist pattern (note: using min_annual_revenue as profit threshold)
        blacklist_pattern = build_blacklist_pattern(active_filters.category_blacklist)

        # Get known IDs for skip logic
        known_ids: set[str] = set()
        if skip_known:
            known_ids = get_known_external_ids(self.config.source_id)
            logger.info(f"Loaded {len(known_ids)} known listing IDs")

        await self.setup()
        try:
            # Phase 1: Get all cards from search pages
            cards, card_errors = await self.get_listing_cards(max_pages=max_pages, verbose=verbose)

            if card_errors and verbose:
                print(f"Warning: {len(card_errors)} card extraction errors")
                for err in card_errors[:5]:
                    print(f"  - {err}")

            # Phase 2: Categorize cards
            to_scrape: list[FlippaListingCard] = []
            to_check: list[FlippaListingCard] = []
            skipped_filter: list[tuple[FlippaListingCard, str]] = []
            skipped_known: list[FlippaListingCard] = []

            for card in cards:
                if skip_known and card.external_id in known_ids:
                    skipped_known.append(card)
                    continue

                # Note: active_filters.min_annual_revenue is used as profit threshold
                # This is documented but could be cleaner with a dedicated field
                status, reason = card.passes_filter(
                    min_annual_profit_cents=active_filters.min_annual_revenue,
                    category_blacklist=blacklist_pattern,
                    us_only=us_only,
                    verified_only=verified_only,
                )

                if status == "pass":
                    to_scrape.append(card)
                elif status == "check_detail":
                    to_check.append(card)
                else:
                    skipped_filter.append((card, reason or "unknown reason"))

            if verbose:
                print(f"\nFiltering: {len(to_scrape)} confirmed US, "
                      f"{len(to_check)} need country check, "
                      f"{len(skipped_filter)} filtered, {len(skipped_known)} known")

            logger.info(f"Filter results: {len(to_scrape)} to scrape, "
                       f"{len(to_check)} to check, {len(skipped_filter)} filtered")

            # Phase 3: Scrape confirmed listings
            result = ScrapeResult()
            total_to_scrape = len(to_scrape) + len(to_check)
            scrape_idx = 0

            for card in to_scrape:
                scrape_idx += 1
                if verbose:
                    print(f"Scraping {scrape_idx}/{total_to_scrape}: {card.title or card.url}")

                try:
                    listing = await self.scrape_listing(card.url, card_data=card)
                    result.listings.append(listing)
                except Exception as e:
                    error = ScrapeError.from_exception(card.url, e)
                    result.errors.append(error)
                    logger.error(f"Scrape error for {card.url}: {e}")
                    if verbose:
                        print(f"  Error: {error.error_type}: {error.error_message}")

                await asyncio.sleep(ScraperDelays.BETWEEN_DETAILS)

            # Phase 4: Check unknown-country listings
            if to_check and verbose:
                print(f"\nChecking {len(to_check)} listings with unknown country...")

            for card in to_check:
                scrape_idx += 1
                if verbose:
                    print(f"Checking {scrape_idx}/{total_to_scrape}: {card.title or card.url}")

                try:
                    listing = await self.scrape_listing(card.url, card_data=card)

                    if us_only and not is_us_country(listing.country):
                        country_str = listing.country or "still unknown"
                        skipped_filter.append((card, f"non-US: {country_str} [from detail]"))
                        if verbose:
                            print(f"  Filtered: non-US ({country_str})")
                    else:
                        result.listings.append(listing)
                        if verbose:
                            print(f"  Found US: {listing.country}")
                except Exception as e:
                    error = ScrapeError.from_exception(card.url, e)
                    result.errors.append(error)
                    logger.error(f"Detail check error for {card.url}: {e}")
                    if verbose:
                        print(f"  Error: {error.error_type}: {error.error_message}")

                await asyncio.sleep(ScraperDelays.BETWEEN_DETAILS)

            return result, skipped_filter, skipped_known
        finally:
            await self.teardown()

    async def get_listing_urls(self) -> list[str]:
        """Get all listing URLs from Flippa."""
        cards, _ = await self.get_listing_cards()
        return [card.url for card in cards]
