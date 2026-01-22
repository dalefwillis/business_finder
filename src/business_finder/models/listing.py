"""Listing data models."""

from datetime import datetime, UTC
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


class ListingCreate(BaseModel):
    """Data for creating a new listing."""

    source_id: str = Field(..., description="Source identifier (e.g., 'microns')")
    external_id: str = Field(..., description="ID from the source platform")
    url: str = Field(..., description="Listing URL")
    title: str | None = Field(None, description="Listing title")
    category: str | None = Field(None, description="Business category (e.g., 'Micro-SaaS')")
    asking_price: int | None = Field(None, description="Asking price in cents")
    annual_revenue: int | None = Field(None, description="Annual revenue in cents (ARR or TTM)")
    customers: int | None = Field(None, description="Number of customers")
    launched_year: int | None = Field(None, description="Year the business was launched")
    posted_at: datetime | None = Field(None, description="When listing was posted to platform")
    description: str | None = Field(None, description="Listing description")
    location: str | None = Field(None, description="Location (city, state, etc.)")
    country: str | None = Field(None, description="Country code or name (e.g., 'US', 'United States')")
    raw_data: dict[str, Any] | None = Field(None, description="Raw scraped data")


class Listing(ListingCreate):
    """Full listing model with database fields."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique listing ID")
    first_seen_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime | None = Field(None)
    last_seen_at: datetime = Field(default_factory=_utc_now, description="Last time listing was seen during scrape")
