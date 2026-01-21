"""Tests for data models."""

import pytest
from pydantic import ValidationError

from business_finder.models.listing import Listing, ListingCreate


class TestListingCreate:
    """Tests for ListingCreate model."""

    def test_minimal_listing(self):
        """Test creating a listing with minimal required fields."""
        listing = ListingCreate(
            source_id="microns",
            external_id="abc123",
            url="https://microns.io/startup/abc123",
        )
        assert listing.source_id == "microns"
        assert listing.external_id == "abc123"
        assert listing.url == "https://microns.io/startup/abc123"
        assert listing.title is None
        assert listing.asking_price is None

    def test_full_listing(self):
        """Test creating a listing with all fields."""
        listing = ListingCreate(
            source_id="microns",
            external_id="abc123",
            url="https://microns.io/startup/abc123",
            title="Test SaaS Business",
            asking_price=5000000,  # $50,000 in cents
            mrr=100000,  # $1,000 MRR in cents
            description="A great business",
            raw_data={"extra": "data"},
        )
        assert listing.title == "Test SaaS Business"
        assert listing.asking_price == 5000000
        assert listing.mrr == 100000
        assert listing.raw_data == {"extra": "data"}

    def test_missing_required_fields(self):
        """Test that missing required fields raise validation error."""
        with pytest.raises(ValidationError):
            ListingCreate(source_id="microns")  # Missing external_id and url

    def test_listing_dict_export(self):
        """Test exporting listing to dict."""
        listing = ListingCreate(
            source_id="microns",
            external_id="abc123",
            url="https://example.com",
            title="Test",
        )
        data = listing.model_dump()
        assert data["source_id"] == "microns"
        assert data["external_id"] == "abc123"
        assert data["title"] == "Test"


class TestListing:
    """Tests for full Listing model."""

    def test_listing_with_id(self):
        """Test creating a full listing with ID."""
        listing = Listing(
            id="uuid-123",
            source_id="microns",
            external_id="abc123",
            url="https://microns.io/startup/abc123",
            title="Test Business",
        )
        assert listing.id == "uuid-123"
        assert listing.first_seen_at is not None
