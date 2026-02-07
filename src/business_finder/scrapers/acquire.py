"""Acquire.com scraper.

Discovered via Claude Chrome exploration (2026-01-25):
- Authentication: Required (email/password login at app.acquire.com/signin)
- Backend: Firebase/Firestore (no REST API)
- Listings page: /all-listing (infinite scroll)
- Detail page: /startup/{user_id}/{listing_id}

Card structure on listing page:
- Category (SaaS, Mobile, Digital, AI, etc.)
- Description/title
- TTM Revenue, TTM Profit, Asking Price

Detail page contains rich data:
- Financials: Asking price, TTM revenue/profit, ARR, growth rate, churn, multiples
- Business: Team size, date founded, business model, tech stack, competitors
- Acquisition: Selling reasoning, financing, key assets, growth opportunities
- Meta: Location, badges (verified, M&A advisory), view count
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from dataclasses import dataclass

from playwright.async_api import TimeoutError as PlaywrightTimeout

from .base import BaseScraper, RateLimiter, ScraperConfig, ScrapeError, ScrapeResult
from ..models.listing import ListingCreate
from ..config import FilterConfig, config as app_config
from ..db.operations import get_known_external_ids, get_listings_to_refresh

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

class AcquireDelays:
    """Random delay ranges to avoid looking like a scraper."""

    # Range in seconds (min, max) for random delays
    BETWEEN_PAGES = (2.0, 5.0)
    BETWEEN_LISTINGS = (1.5, 4.0)
    AFTER_SCROLL = (1.0, 3.0)
    AFTER_LOGIN = (2.0, 4.0)
    AFTER_CLICK = (0.5, 1.5)


class AcquireTimeouts:
    """Timeout configuration in milliseconds."""
    PAGE_LOAD_MS = 60_000
    LOGIN_MS = 30_000
    SELECTOR_WAIT_MS = 15_000
    SCROLL_SETTLE_MS = 2_000


class AcquireLimits:
    """Safety limits."""
    MAX_SCROLL_ATTEMPTS = 10  # Max scrolls before stopping (each scroll loads ~18 listings)
    MAX_CONSECUTIVE_EMPTY_SCROLLS = 2  # Stop if no new listings after N scrolls
    MAX_LISTINGS_PER_RUN = 200  # Safety limit


# =============================================================================
# Helper Functions
# =============================================================================

async def random_delay(delay_range: tuple[float, float]) -> None:
    """Sleep for a random duration within the given range."""
    delay = random.uniform(delay_range[0], delay_range[1])
    await asyncio.sleep(delay)


def parse_money(text: str | None) -> int | None:
    """Parse a money string like '$910k' or '$1.2M' into cents.

    Returns None if parsing fails.
    """
    if not text:
        return None

    text = text.strip().replace(",", "").replace(" ", "")

    # Match patterns like $910k, $1.2M, $15000
    match = re.match(r"\$?([\d.]+)\s*([kKmMbB])?", text)
    if not match:
        return None

    try:
        value = float(match.group(1))
        multiplier = match.group(2)

        if multiplier:
            multiplier = multiplier.upper()
            if multiplier == "K":
                value *= 1_000
            elif multiplier == "M":
                value *= 1_000_000
            elif multiplier == "B":
                value *= 1_000_000_000

        return int(value * 100)  # Convert to cents
    except (ValueError, TypeError):
        return None


def parse_percentage(text: str | None) -> float | None:
    """Parse a percentage string like '10%' or '10%+ Stable' into a float."""
    if not text:
        return None

    match = re.search(r"([\d.]+)\s*%", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def extract_listing_id_from_url(url: str) -> str | None:
    """Extract the listing ID from an Acquire.com URL.

    URL format: /startup/{user_id}/{listing_id}
    """
    match = re.search(r"/startup/([^/]+)/([^/?]+)", url)
    if match:
        return match.group(2)
    return None


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class AcquireListingCard:
    """Data extracted from a listing card on the all-listing page."""

    url: str
    listing_id: str
    category: str | None = None
    title: str | None = None
    ttm_revenue_cents: int | None = None
    ttm_profit_cents: int | None = None
    asking_price_cents: int | None = None

    def passes_filter(self, filter_config: FilterConfig) -> tuple[bool, str | None]:
        """Check if this listing passes filters.

        Returns:
            Tuple of (passes, rejection_reason).
        """
        # Check category blacklist
        if self.category and filter_config.category_blacklist:
            cat_lower = self.category.lower()
            for blacklisted in filter_config.category_blacklist:
                if blacklisted.lower() in cat_lower:
                    return False, f"category:{self.category}"

        return True, None


# =============================================================================
# Main Scraper Class
# =============================================================================

class AcquireScraper(BaseScraper):
    """Scraper for Acquire.com marketplace.

    Requires authentication. Credentials should be in environment variables:
    - ACQUIRE_USERNAME
    - ACQUIRE_PASSWORD

    Implements random delays between actions to avoid detection.
    """

    BASE_URL = "https://app.acquire.com"
    LOGIN_URL = "https://app.acquire.com/signin"
    LISTINGS_URL = "https://app.acquire.com/all-listing"

    def __init__(
        self,
        headless: bool = True,
        filter_config: FilterConfig | None = None,
        skip_known: bool = True,
    ):
        """Initialize the Acquire scraper.

        Args:
            headless: Run browser in headless mode.
            filter_config: Filter configuration for excluding listings.
            skip_known: Skip listings already in the database.
        """
        super().__init__(
            ScraperConfig(
                source_id="acquire",
                base_url=self.BASE_URL,
                headless=headless,
                timeout_ms=AcquireTimeouts.PAGE_LOAD_MS,
            )
        )
        self.filter_config = filter_config or FilterConfig()
        self.skip_known = skip_known
        self._known_ids: set[str] = set()
        self._logged_in = False
        # Stats tracking
        self._total_seen = 0  # Total unique listings seen on page
        self._skipped_known = 0  # Skipped because already in DB
        self._filtered_out = 0  # Skipped by category/keyword filter

    async def setup(self) -> None:
        """Initialize browser and login."""
        await super().setup()

        if self.skip_known:
            self._known_ids = get_known_external_ids("acquire")
            logger.info(f"Loaded {len(self._known_ids)} known Acquire listing IDs")

    async def login(self) -> bool:
        """Login to Acquire.com using credentials from environment.

        Returns:
            True if login successful.
        """
        username = os.environ.get("ACQUIRE_USERNAME")
        password = os.environ.get("ACQUIRE_PASSWORD")

        if not username or not password:
            raise ValueError(
                "ACQUIRE_USERNAME and ACQUIRE_PASSWORD must be set in environment"
            )

        logger.info("Navigating to login page...")
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded")

        # Wait for the login form to be visible
        logger.info("Waiting for login form...")
        await self.page.wait_for_selector('input[type="password"]', timeout=AcquireTimeouts.SELECTOR_WAIT_MS)
        await random_delay(AcquireDelays.AFTER_CLICK)

        # Find and fill email field - try multiple selectors
        logger.info("Filling email...")
        email_input = self.page.locator('input[type="text"]').first
        await email_input.fill(username)
        await random_delay(AcquireDelays.AFTER_CLICK)

        # Find and fill password field
        logger.info("Filling password...")
        password_input = self.page.locator('input[type="password"]')
        await password_input.fill(password)
        await random_delay(AcquireDelays.AFTER_CLICK)

        # Click login button - look for button containing "Log in" text
        logger.info("Clicking login button...")
        # Try multiple strategies to find the login button
        login_button = self.page.get_by_role("button", name=re.compile(r"Log\s*in", re.I))
        if await login_button.count() == 0:
            login_button = self.page.locator('button:has-text("Log in")')
        if await login_button.count() == 0:
            # Fallback: find any button that's not LinkedIn/Google
            login_button = self.page.locator('button').filter(
                has_not_text=re.compile(r"LinkedIn|Google", re.I)
            ).last

        await login_button.click()

        # Wait for navigation to complete
        try:
            await self.page.wait_for_url(
                re.compile(r"/browse|/all-listing"),
                timeout=AcquireTimeouts.LOGIN_MS
            )
            logger.info("Login successful")
            self._logged_in = True
            await random_delay(AcquireDelays.AFTER_LOGIN)
            return True
        except PlaywrightTimeout:
            logger.error("Login failed - did not redirect to browse page")
            return False

    async def get_listing_urls(self) -> list[str]:
        """Get listing URLs by scrolling through the all-listing page.

        Uses infinite scroll to load all listings.
        """
        if not self._logged_in:
            if not await self.login():
                raise RuntimeError("Failed to login to Acquire.com")

        logger.info("Navigating to all listings page...")
        await self.page.goto(self.LISTINGS_URL, wait_until="domcontentloaded")
        await random_delay(AcquireDelays.AFTER_CLICK)

        listing_urls: list[str] = []
        seen_urls: set[str] = set()
        empty_scroll_count = 0
        scroll_count = 0

        while scroll_count < AcquireLimits.MAX_SCROLL_ATTEMPTS:
            # Extract listing links from current view
            links = await self.page.locator('a[href*="/startup/"]').all()

            new_count = 0
            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if href and href not in seen_urls and "/startup/" in href:
                        full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                        seen_urls.add(href)
                        listing_urls.append(full_url)
                        new_count += 1
                except Exception:
                    continue

            logger.info(f"Scroll {scroll_count + 1}: found {new_count} new listings (total: {len(listing_urls)})")

            if new_count == 0:
                empty_scroll_count += 1
                if empty_scroll_count >= AcquireLimits.MAX_CONSECUTIVE_EMPTY_SCROLLS:
                    logger.info("No new listings after multiple scrolls, stopping")
                    break
            else:
                empty_scroll_count = 0

            if len(listing_urls) >= AcquireLimits.MAX_LISTINGS_PER_RUN:
                logger.info(f"Reached max listings limit ({AcquireLimits.MAX_LISTINGS_PER_RUN})")
                break

            # Scroll down
            await self.page.keyboard.press("End")
            await random_delay(AcquireDelays.AFTER_SCROLL)
            scroll_count += 1

        logger.info(f"Found {len(listing_urls)} total listing URLs")
        return listing_urls

    async def get_listing_cards(
        self,
        early_stop: int | None = None,
        max_scrolls: int | None = None,
    ) -> list[AcquireListingCard]:
        """Get listing cards with basic info for filtering before detail scrape.

        Args:
            early_stop: Stop scrolling once we have this many cards.
            max_scrolls: Maximum number of scrolls (overrides AcquireLimits).
        """
        if not self._logged_in:
            if not await self.login():
                raise RuntimeError("Failed to login to Acquire.com")

        logger.info("Navigating to all listings page...")
        await self.page.goto(self.LISTINGS_URL, wait_until="domcontentloaded")

        # Wait for listing cards to appear (Firebase loads them async)
        logger.info("Waiting for listings to load...")
        try:
            await self.page.wait_for_selector('a[href*="/startup/"]', timeout=AcquireTimeouts.SELECTOR_WAIT_MS)
        except PlaywrightTimeout:
            logger.warning("Timeout waiting for listing cards - page may be empty or slow")

        await random_delay(AcquireDelays.AFTER_CLICK)

        cards: list[AcquireListingCard] = []
        seen_ids: set[str] = set()
        empty_scroll_count = 0
        scroll_count = 0
        scroll_limit = max_scrolls or AcquireLimits.MAX_SCROLL_ATTEMPTS
        skipped_known_this_scroll = 0

        while scroll_count < scroll_limit:
            # Find all listing card containers
            # Cards have a link to /startup/ and contain financial metrics
            card_links = await self.page.locator('a[href*="/startup/"]').all()

            new_count = 0
            skipped_known_this_scroll = 0
            new_seen_this_scroll = 0
            for link in card_links:
                try:
                    href = await link.get_attribute("href")
                    if not href or "/startup/" not in href:
                        continue

                    listing_id = extract_listing_id_from_url(href)
                    if not listing_id or listing_id in seen_ids:
                        continue

                    seen_ids.add(listing_id)
                    new_seen_this_scroll += 1

                    # Skip if already known
                    if self.skip_known and listing_id in self._known_ids:
                        skipped_known_this_scroll += 1
                        self._skipped_known += 1
                        continue

                    # Get the parent card element to extract data
                    # Try multiple ancestor strategies
                    try:
                        # Try finding parent with class containing 'group' or 'card'
                        card = link.locator("xpath=ancestor::div[contains(@class, 'rounded') or contains(@class, 'border')]").first
                        text = await card.inner_text(timeout=2000)
                    except Exception:
                        # Fallback: just use the link's text + nearby siblings
                        text = await link.inner_text(timeout=2000)
                    lines = [l.strip() for l in text.split("\n") if l.strip()]

                    # Parse card data
                    category = None
                    title = None
                    ttm_revenue = None
                    ttm_profit = None
                    asking_price = None

                    for i, line in enumerate(lines):
                        if line in ("SaaS", "Mobile", "Digital", "AI", "Ecommerce", "Agency", "Marketplace"):
                            category = line
                        elif "TTM REVENUE" in line.upper() and i + 1 < len(lines):
                            ttm_revenue = parse_money(lines[i + 1])
                        elif "TTM PROFIT" in line.upper() and i + 1 < len(lines):
                            ttm_profit = parse_money(lines[i + 1])
                        elif "ASKING PRICE" in line.upper() and i + 1 < len(lines):
                            asking_price = parse_money(lines[i + 1])
                        elif len(line) > 30 and not any(x in line.upper() for x in ["TTM", "ASKING", "REVENUE", "PROFIT"]):
                            if title is None:
                                title = line

                    full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

                    card_data = AcquireListingCard(
                        url=full_url,
                        listing_id=listing_id,
                        category=category,
                        title=title,
                        ttm_revenue_cents=ttm_revenue,
                        ttm_profit_cents=ttm_profit,
                        asking_price_cents=asking_price,
                    )
                    cards.append(card_data)
                    new_count += 1

                except Exception as e:
                    logger.debug(f"Error parsing card: {e}")
                    continue

            logger.info(
                f"Scroll {scroll_count + 1}: {len(card_links)} links on page, "
                f"{new_seen_this_scroll} unique, {skipped_known_this_scroll} already known, "
                f"{new_count} new (total: {len(cards)})"
            )

            # For scroll-stop logic, count any new unique listing (including known)
            # so we keep scrolling as long as the page is loading more content
            if new_seen_this_scroll == 0:
                empty_scroll_count += 1
                if empty_scroll_count >= AcquireLimits.MAX_CONSECUTIVE_EMPTY_SCROLLS:
                    logger.info("No new listings after multiple scrolls, stopping")
                    break
            else:
                empty_scroll_count = 0

            # Check early stop
            if early_stop and len(cards) >= early_stop:
                logger.info(f"Reached early stop limit ({early_stop} cards)")
                break

            if len(cards) >= AcquireLimits.MAX_LISTINGS_PER_RUN:
                logger.info(f"Reached max cards limit ({AcquireLimits.MAX_LISTINGS_PER_RUN})")
                break

            # Scroll down
            await self.page.keyboard.press("End")
            await random_delay(AcquireDelays.AFTER_SCROLL)
            scroll_count += 1

        self._total_seen = len(seen_ids)
        logger.info(
            f"Found {self._total_seen} total listings on page, "
            f"{self._skipped_known} already known, {len(cards)} new cards"
        )
        return cards

    async def scrape_listing(
        self,
        url: str,
        card_data: AcquireListingCard | None = None,
    ) -> ListingCreate:
        """Scrape full details from a listing detail page.

        Args:
            url: Listing detail page URL.
            card_data: Optional card data to use as fallback for missing fields.
        """
        await random_delay(AcquireDelays.BETWEEN_LISTINGS)

        logger.debug(f"Scraping listing: {url}")
        await self.page.goto(url, wait_until="domcontentloaded")

        # Wait for actual content to load (Firebase loads async)
        try:
            # Wait for the main content to appear - look for asking price text
            await self.page.wait_for_selector(
                'text=/ASKING PRICE|TTM REVENUE/i',
                timeout=AcquireTimeouts.SELECTOR_WAIT_MS
            )
        except PlaywrightTimeout:
            logger.warning(f"Timeout waiting for content to load: {url}")

        await random_delay(AcquireDelays.AFTER_CLICK)

        # Extract listing ID from URL
        listing_id = extract_listing_id_from_url(url)
        if not listing_id:
            raise ValueError(f"Could not extract listing ID from URL: {url}")

        # Get all page text for parsing
        page_text = await self.page.inner_text("body")
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]

        # Check for premium-locked listing
        is_premium_locked = "Upgrade to Platinum" in page_text or "upgrade to platinum" in page_text.lower()

        # Detect listing status
        status = "active"  # Default
        page_text_lower = page_text.lower()

        if "sold" in page_text_lower and ("this listing has been sold" in page_text_lower or "already sold" in page_text_lower):
            status = "sold"
        elif "under offer" in page_text_lower:
            status = "under_offer"
        elif is_premium_locked:
            # Premium-locked listings are still active, just with limited data
            status = "active"

        # Initialize data containers
        raw_data: dict = {
            "url": url,
            "external_id": listing_id,
            "is_premium_locked": is_premium_locked,
            "status": status,
        }

        # Parse title - try multiple approaches
        title = None

        # First, try to find h1/h2 elements that look like titles
        try:
            h1_elements = await self.page.locator("h1").all()
            for h1 in h1_elements:
                text = await h1.inner_text(timeout=2000)
                if text and len(text) > 20 and not any(x in text.upper() for x in ["ASKING", "TTM", "REVENUE", "PROFIT"]):
                    title = text.strip()
                    break
        except Exception:
            pass

        if not title:
            try:
                h2_elements = await self.page.locator("h2").all()
                for h2 in h2_elements:
                    text = await h2.inner_text(timeout=2000)
                    if text and len(text) > 20 and not any(x in text.upper() for x in ["ASKING", "TTM", "REVENUE", "PROFIT"]):
                        title = text.strip()
                        break
            except Exception:
                pass

        if not title:
            # Fallback: find first long line that looks like a title
            # Exclude common placeholder text from Platinum-locked listings
            exclusions = [
                "TTM REVENUE", "TTM PROFIT", "ASKING PRICE", "UPGRADE TO",
                "CHAT WITH THE FOUNDER", "ACCESS EXCLUSIVE DATA",
                "UNAVAILABLE TO THE PUBLIC", "REQUEST ACCESS",
                "SUPPORTING FILES", "ANNUAL GROWTH", "LAST MONTH",
                "MULTIPLES", "PROFIT MARGIN", "CHURN RATE",
            ]
            for line in lines:
                line_upper = line.upper()
                # Skip lines that match exclusion phrases
                if any(x in line_upper for x in exclusions):
                    continue
                # Skip lines that are just prices (e.g., "$98k", "$1.2M")
                if re.match(r"^\$[\d,.]+[kKmMbB]?$", line.strip()):
                    continue
                # Skip short lines or very long lines
                if not (30 < len(line) < 200):
                    continue
                title = line
                break

        # Use card data as fallback for title
        if not title and card_data and card_data.title:
            title = card_data.title
            raw_data["title_source"] = "card"

        # Parse financial metrics
        asking_price_cents = None
        ttm_revenue_cents = None
        ttm_profit_cents = None
        arr_cents = None
        growth_rate = None
        churn_rate = None
        profit_multiple = None
        revenue_multiple = None
        last_month_revenue_cents = None
        last_month_profit_cents = None

        for i, line in enumerate(lines):
            line_upper = line.upper()

            if "ASKING PRICE" in line_upper and i + 1 < len(lines):
                asking_price_cents = parse_money(lines[i + 1])
            elif "TTM REVENUE" in line_upper and i + 1 < len(lines):
                ttm_revenue_cents = parse_money(lines[i + 1])
            elif "TTM PROFIT" in line_upper and i + 1 < len(lines):
                ttm_profit_cents = parse_money(lines[i + 1])
            elif "ANNUAL RECURRING REVENUE" in line_upper and i + 1 < len(lines):
                arr_cents = parse_money(lines[i + 1])
            elif "ANNUAL GROWTH RATE" in line_upper and i + 1 < len(lines):
                growth_rate = parse_percentage(lines[i + 1])
            elif "CHURN RATE" in line_upper and i + 1 < len(lines):
                churn_rate = parse_percentage(lines[i + 1])
            elif "LAST MONTH" in line_upper and "REVENUE" in line_upper and i + 1 < len(lines):
                last_month_revenue_cents = parse_money(lines[i + 1])
            elif "LAST MONTH" in line_upper and "PROFIT" in line_upper and i + 1 < len(lines):
                last_month_profit_cents = parse_money(lines[i + 1])
            elif re.search(r"(\d+(?:\.\d+)?)\s*x\s*profit", line, re.I):
                match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*profit", line, re.I)
                if match:
                    profit_multiple = float(match.group(1))
            elif re.search(r"(\d+(?:\.\d+)?)\s*x\s*revenue", line, re.I):
                match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*revenue", line, re.I)
                if match:
                    revenue_multiple = float(match.group(1))

        raw_data["ttm_revenue_cents"] = ttm_revenue_cents
        raw_data["ttm_profit_cents"] = ttm_profit_cents
        raw_data["arr_cents"] = arr_cents
        raw_data["growth_rate"] = growth_rate
        raw_data["churn_rate"] = churn_rate
        raw_data["profit_multiple"] = profit_multiple
        raw_data["revenue_multiple"] = revenue_multiple
        raw_data["last_month_revenue_cents"] = last_month_revenue_cents
        raw_data["last_month_profit_cents"] = last_month_profit_cents

        # Parse category
        category = None
        for cat in ["SaaS", "Mobile", "Digital", "AI", "Ecommerce", "Agency", "Marketplace", "Chrome Extension"]:
            if cat.lower() in page_text.lower():
                # Look for it as a standalone category label
                for line in lines:
                    if line.lower() == cat.lower() or line.lower() == f"{cat.lower()} startup":
                        category = cat
                        break
                if category:
                    break

        raw_data["category"] = category

        # Use card data as fallback for category
        if not category and card_data and card_data.category:
            category = card_data.category
            raw_data["category_source"] = "card"

        # If still no title after all attempts, use category + ID as a descriptive placeholder
        if not title:
            cat_prefix = category or "Listing"
            title = f"{cat_prefix} ({listing_id[:8]}...)"
            raw_data["title_source"] = "generated"

        # Parse location
        location = None
        country = None
        location_match = re.search(r"United States\s*\(([^)]+)\)", page_text)
        if location_match:
            location = location_match.group(1)  # State like "Delaware"
            country = "United States"
        elif "United States" in page_text:
            country = "United States"

        raw_data["location"] = location
        raw_data["country"] = country

        # Parse business details
        team_size = None
        date_founded = None
        business_model = None
        tech_stack = None
        competitors = None
        selling_reason = None
        financing = None
        customers_range = None

        for i, line in enumerate(lines):
            line_upper = line.upper()

            if "TEAM SIZE" in line_upper and i + 1 < len(lines):
                team_size = lines[i + 1]
            elif "DATE FOUNDED" in line_upper and i + 1 < len(lines):
                date_founded = lines[i + 1]
            elif "BUSINESS MODEL" in line_upper and i + 1 < len(lines):
                business_model = lines[i + 1]
            elif "TECH STACK" in line_upper:
                # Tech stack might be multiple lines
                tech_items = []
                for j in range(i + 1, min(i + 10, len(lines))):
                    if any(x in lines[j].upper() for x in ["COMPETITORS", "GROWTH", "KEY ASSETS", "ACQUISITION"]):
                        break
                    if lines[j] and len(lines[j]) < 50:
                        tech_items.append(lines[j])
                if tech_items:
                    tech_stack = ", ".join(tech_items)
            elif "COMPETITORS" in line_upper:
                comp_items = []
                for j in range(i + 1, min(i + 10, len(lines))):
                    if any(x in lines[j].upper() for x in ["GROWTH OPPORTUNITIES", "KEY ASSETS", "ACQUISITION"]):
                        break
                    if lines[j] and len(lines[j]) < 50:
                        comp_items.append(lines[j])
                if comp_items:
                    competitors = ", ".join(comp_items)
            elif "SELLING REASON" in line_upper and i + 1 < len(lines):
                selling_reason = lines[i + 1]
            elif "FINANCING" in line_upper and i + 1 < len(lines):
                financing = lines[i + 1]
            elif "CUSTOMERS" in line_upper and i + 1 < len(lines):
                if re.match(r"[\d,]+-[\d,]+", lines[i + 1]) or re.match(r"[\d,]+\+?", lines[i + 1]):
                    customers_range = lines[i + 1]

        raw_data["team_size"] = team_size
        raw_data["date_founded"] = date_founded
        raw_data["business_model"] = business_model
        raw_data["tech_stack"] = tech_stack
        raw_data["competitors"] = competitors
        raw_data["selling_reason"] = selling_reason
        raw_data["financing"] = financing
        raw_data["customers_range"] = customers_range

        # Parse description
        description = None
        # Look for long text that looks like a description
        for line in lines:
            if len(line) > 100 and not any(x in line.upper() for x in ["TTM", "ASKING", "UPGRADE"]):
                description = line
                break

        raw_data["description"] = description

        # Check for badges/verification
        has_verified = "Verified business" in page_text or "verified" in page_text.lower()
        under_advisory = "Under M&A advisory" in page_text

        raw_data["has_verified"] = has_verified
        raw_data["under_advisory"] = under_advisory

        # Parse view count if available
        views_match = re.search(r"(\d+)\s*buyers have viewed", page_text)
        if views_match:
            raw_data["view_count"] = int(views_match.group(1))

        # Calculate launched year from date_founded
        launched_year = None
        if date_founded:
            year_match = re.search(r"(\d{4})", date_founded)
            if year_match:
                launched_year = int(year_match.group(1))

        # Parse customer count from range
        customers = None
        if customers_range:
            # Parse ranges like "101-250" or "1000+"
            range_match = re.match(r"(\d+)", customers_range.replace(",", ""))
            if range_match:
                customers = int(range_match.group(1))

        # Use card data as fallback for financial fields we couldn't parse from detail page
        if card_data:
            if not asking_price_cents and card_data.asking_price_cents:
                asking_price_cents = card_data.asking_price_cents
                raw_data["asking_price_source"] = "card"
            if not ttm_revenue_cents and card_data.ttm_revenue_cents:
                ttm_revenue_cents = card_data.ttm_revenue_cents
                raw_data["ttm_revenue_source"] = "card"
            if not ttm_profit_cents and card_data.ttm_profit_cents:
                ttm_profit_cents = card_data.ttm_profit_cents
                raw_data["ttm_profit_source"] = "card"

        # Log if this is a premium-locked listing with limited data
        if is_premium_locked:
            logger.info(f"Listing {listing_id} requires Platinum upgrade - data may be limited")

        return ListingCreate(
            source_id="acquire",
            external_id=listing_id,
            url=url,
            title=title,
            category=category,
            asking_price=asking_price_cents,
            annual_revenue=arr_cents or ttm_revenue_cents,  # Prefer ARR if available
            customers=customers,
            launched_year=launched_year,
            description=description,
            location=location,
            country=country,
            raw_data=raw_data,
        )

    async def run_with_filter(
        self,
        max_listings: int | None = None,
        max_scrolls: int | None = None,
        verbose: bool = False,
    ) -> ScrapeResult:
        """Run scrape with two-phase filtering.

        1. Get listing cards from index page
        2. Filter based on category/keywords
        3. Scrape details only for listings that pass filter
        """
        await self.setup()

        try:
            # Phase 1: Get cards (collect extra to account for filtering)
            early_stop = max_listings * 2 if max_listings else None
            logger.info("Phase 1: Collecting listing cards...")
            cards = await self.get_listing_cards(early_stop=early_stop, max_scrolls=max_scrolls)

            # Phase 2: Filter
            logger.info("Phase 2: Filtering listings...")
            to_scrape = []
            filtered_count = 0
            filter_reasons: dict[str, int] = {}

            for card in cards:
                passes, reason = card.passes_filter(self.filter_config)
                if passes:
                    to_scrape.append(card)
                else:
                    filtered_count += 1
                    if reason:
                        filter_reasons[reason] = filter_reasons.get(reason, 0) + 1

            self._filtered_out = filtered_count
            logger.info(f"Filtered {filtered_count} listings, {len(to_scrape)} to scrape")
            if filter_reasons and verbose:
                for reason, count in sorted(filter_reasons.items(), key=lambda x: -x[1]):
                    logger.info(f"  {reason}: {count}")

            # Apply max limit
            if max_listings and len(to_scrape) > max_listings:
                to_scrape = to_scrape[:max_listings]
                logger.info(f"Limited to {max_listings} listings")

            # Phase 3: Scrape details
            logger.info(f"Phase 3: Scraping {len(to_scrape)} listing details...")
            result = ScrapeResult()

            for i, card in enumerate(to_scrape):
                try:
                    if verbose:
                        logger.info(f"  [{i+1}/{len(to_scrape)}] {card.title or card.listing_id}")

                    # Pass card data as fallback for fields we can't parse from detail page
                    listing = await self.scrape_listing(card.url, card_data=card)
                    result.listings.append(listing)

                except Exception as e:
                    logger.error(f"Error scraping {card.url}: {e}")
                    result.errors.append(ScrapeError.from_exception(card.url, e))

            return result

        finally:
            await self.teardown()

    async def refresh_listings(
        self,
        older_than_days: int = 7,
        max_listings: int | None = None,
        verbose: bool = False,
    ) -> ScrapeResult:
        """Refresh existing listings to detect status changes and price updates.

        Uses exponential backoff on errors: if requests fail, the delay between
        requests doubles (up to 60s max). After 5 consecutive failures, the
        refresh operation aborts to avoid hammering a potentially down service.

        Args:
            older_than_days: Only refresh listings not refreshed in this many days.
            max_listings: Maximum number of listings to refresh (None = all).
            verbose: If True, print progress messages.

        Returns:
            ScrapeResult with refreshed listings.
        """
        await self.setup()

        try:
            if not self._logged_in:
                if not await self.login():
                    raise RuntimeError("Failed to login to Acquire.com")

            # Get listings to refresh
            listings = get_listings_to_refresh(
                source_id="acquire",
                older_than_days=older_than_days,
                status_filter=["active"],
            )

            if max_listings:
                listings = listings[:max_listings]

            if verbose:
                logger.info(f"Found {len(listings)} listings to refresh")

            # Initialize rate limiter with exponential backoff
            rate_limiter = RateLimiter(
                base_delay=AcquireDelays.BETWEEN_LISTINGS[0],  # Use min delay as base
                max_delay=60.0,
                backoff_factor=2.0,
                max_consecutive_failures=5,
            )

            result = ScrapeResult()

            for i, listing in enumerate(listings, 1):
                url = listing.get("url")
                if not url:
                    continue

                if verbose:
                    logger.info(f"Refreshing {i}/{len(listings)}: {listing.get('title', url)}")

                try:
                    refreshed = await self.scrape_listing(url)
                    result.listings.append(refreshed)
                    rate_limiter.record_success()
                except Exception as e:
                    logger.error(f"Error refreshing {url}: {e}")
                    result.errors.append(ScrapeError.from_exception(url, e))
                    if not rate_limiter.record_failure():
                        # Max consecutive failures reached, abort
                        logger.warning(f"Aborting refresh after {rate_limiter.consecutive_failures} consecutive failures")
                        break

                # Wait with exponential backoff
                await rate_limiter.wait()

            return result
        finally:
            await self.teardown()
