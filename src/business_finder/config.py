"""Configuration management."""

from pathlib import Path
from pydantic import BaseModel, Field


class FilterConfig(BaseModel):
    """Filtering criteria for listings."""

    # Revenue filter (in cents)
    min_annual_revenue: int | None = Field(
        default=None,
        description="Minimum annual revenue in cents (e.g., 100000 = $1,000)"
    )

    # Price filter (in cents)
    max_asking_price: int | None = Field(
        default=None,
        description="Maximum asking price in cents (e.g., 10000000 = $100,000)"
    )

    # Category blacklist - business types we don't want
    # These are content/product businesses, not software
    category_blacklist: list[str] = Field(
        default=[
            "Newsletter",
            "E-commerce",
            "Marketplace",
            "Directory",
            "Agency",
            "Content",
            "Community",
        ],
        description="Categories to exclude (case-insensitive matching)"
    )

    # Location filter - US only for now
    # Don't want to deal with international acquisitions at this price point
    allowed_countries: list[str] = Field(
        default=["US", "USA", "United States"],
        description="Allowed country codes/names (case-insensitive). Empty list = no filter."
    )

    def with_overrides(
        self,
        min_annual_revenue: int | None = None,
        max_asking_price: int | None = None,
        category_blacklist: list[str] | None = None,
        allowed_countries: list[str] | None = None,
    ) -> "FilterConfig":
        """Create a new FilterConfig with optional overrides.

        Only non-None values override the defaults.
        """
        return FilterConfig(
            min_annual_revenue=min_annual_revenue if min_annual_revenue is not None else self.min_annual_revenue,
            max_asking_price=max_asking_price if max_asking_price is not None else self.max_asking_price,
            category_blacklist=category_blacklist if category_blacklist is not None else self.category_blacklist,
            allowed_countries=allowed_countries if allowed_countries is not None else self.allowed_countries,
        )


class Config(BaseModel):
    """Application configuration."""

    # Project paths - config.py is at src/business_finder/config.py, so 3 parents up
    project_root: Path = Path(__file__).parent.parent.parent
    data_dir: Path = project_root / "data"
    db_path: Path = data_dir / "business_finder.db"

    # Scraping settings
    request_delay_seconds: float = 1.0
    max_retries: int = 3
    timeout_seconds: int = 30

    # Browser settings
    headless: bool = True
    slow_mo: int = 0  # milliseconds between actions

    # Default filter settings
    filters: FilterConfig = Field(default_factory=FilterConfig)

    def ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Global config instance
config = Config()
