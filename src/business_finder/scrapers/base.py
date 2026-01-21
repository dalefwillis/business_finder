"""Base scraper class."""

import asyncio
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from pydantic import BaseModel, Field

from ..config import config
from ..models.listing import Listing, ListingCreate


@dataclass
class ScrapeError:
    """Record of a scraping error."""

    url: str
    error_type: str
    error_message: str
    traceback: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_exception(cls, url: str, exc: Exception) -> "ScrapeError":
        """Create a ScrapeError from an exception."""
        return cls(
            url=url,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback=traceback.format_exc(),
        )


@dataclass
class ScrapeResult:
    """Result of a scrape operation containing successes and failures."""

    listings: list[ListingCreate] = field(default_factory=list)
    errors: list[ScrapeError] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.listings)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def total_count(self) -> int:
        return self.success_count + self.error_count

    def __repr__(self) -> str:
        return f"ScrapeResult({self.success_count} succeeded, {self.error_count} failed)"


class ScraperConfig(BaseModel):
    """Configuration for a scraper."""

    source_id: str = Field(..., description="Unique identifier for this source")
    base_url: str = Field(..., description="Base URL for the source")
    headless: bool = Field(default=True, description="Run browser in headless mode")
    slow_mo: int = Field(default=0, description="Slow down operations by ms")
    timeout_ms: int = Field(default=30000, description="Default timeout in ms")


class BaseScraper(ABC):
    """Base class for all scrapers."""

    def __init__(self, scraper_config: ScraperConfig):
        self.config = scraper_config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def setup(self) -> None:
        """Initialize Playwright browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
        )
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.config.timeout_ms)

    async def teardown(self) -> None:
        """Cleanup browser resources."""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @property
    def page(self) -> Page:
        """Get the current page, raising if not initialized."""
        if self._page is None:
            raise RuntimeError("Scraper not initialized. Call setup() first.")
        return self._page

    @abstractmethod
    async def get_listing_urls(self) -> list[str]:
        """Get all listing URLs from the source.

        Override in subclass to implement source-specific logic.

        Returns:
            List of listing URLs to scrape.
        """
        raise NotImplementedError

    @abstractmethod
    async def scrape_listing(self, url: str) -> ListingCreate:
        """Extract data from a single listing page.

        Override in subclass to implement source-specific extraction.

        Args:
            url: URL of the listing to scrape.

        Returns:
            Extracted listing data.
        """
        raise NotImplementedError

    async def run(self, max_listings: int | None = None) -> ScrapeResult:
        """Orchestrate full scrape.

        Args:
            max_listings: Optional limit on number of listings to scrape.

        Returns:
            ScrapeResult containing listings and any errors encountered.
        """
        await self.setup()
        try:
            urls = await self.get_listing_urls()
            if max_listings:
                urls = urls[:max_listings]

            result = ScrapeResult()
            for url in urls:
                try:
                    listing = await self.scrape_listing(url)
                    result.listings.append(listing)
                    # Be polite to the server
                    await asyncio.sleep(config.request_delay_seconds)
                except Exception as e:
                    result.errors.append(ScrapeError.from_exception(url, e))

            return result
        finally:
            await self.teardown()

    async def __aenter__(self):
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.teardown()
