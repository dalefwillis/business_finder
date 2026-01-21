"""Tests for database operations."""

import tempfile
from pathlib import Path

import pytest

from business_finder.db.schema import init_db
from business_finder.db.operations import (
    save_listing,
    get_listing,
    get_all_listings,
    log_exploration,
    get_exploration_logs,
    close_db,
)
import business_finder.db.operations as db_ops


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database."""
    db_path = tmp_path / "test.db"
    # Reset module-level connection
    db_ops._connection = None
    conn = init_db(db_path)
    db_ops._connection = conn
    yield conn
    close_db()


class TestListingOperations:
    """Tests for listing CRUD operations."""

    def test_save_and_get_listing(self, test_db):
        """Test saving and retrieving a listing."""
        listing_id = save_listing(
            source_id="microns",
            external_id="test123",
            url="https://microns.io/startup/test123",
            title="Test Business",
            asking_price=5000000,
        )

        listing = get_listing(listing_id)
        assert listing is not None
        assert listing["source_id"] == "microns"
        assert listing["external_id"] == "test123"
        assert listing["title"] == "Test Business"
        assert listing["asking_price"] == 5000000

    def test_upsert_listing(self, test_db):
        """Test that saving same listing updates it."""
        # First save
        save_listing(
            source_id="microns",
            external_id="test123",
            url="https://microns.io/startup/test123",
            title="Original Title",
        )

        # Update with same source_id + external_id
        save_listing(
            source_id="microns",
            external_id="test123",
            url="https://microns.io/startup/test123",
            title="Updated Title",
        )

        # Should have only one listing
        listings = get_all_listings(source_id="microns")
        assert len(listings) == 1
        assert listings[0]["title"] == "Updated Title"

    def test_get_all_listings(self, test_db):
        """Test getting all listings."""
        save_listing(
            source_id="microns",
            external_id="test1",
            url="https://microns.io/startup/test1",
        )
        save_listing(
            source_id="microns",
            external_id="test2",
            url="https://microns.io/startup/test2",
        )
        save_listing(
            source_id="bizbuysell",
            external_id="test3",
            url="https://bizbuysell.com/listing/test3",
        )

        # All listings
        all_listings = get_all_listings()
        assert len(all_listings) == 3

        # Filtered by source
        microns_listings = get_all_listings(source_id="microns")
        assert len(microns_listings) == 2


class TestExplorationLogs:
    """Tests for exploration logging."""

    def test_log_exploration(self, test_db):
        """Test logging an exploration action."""
        log_id = log_exploration(
            source_id="microns",
            action_type="selector",
            selector="a.listing-link",
            description="Listing link selector",
            example_value="https://microns.io/startup/abc",
        )

        assert log_id > 0

        logs = get_exploration_logs(source_id="microns")
        assert len(logs) == 1
        assert logs[0]["selector"] == "a.listing-link"
        assert logs[0]["action_type"] == "selector"

    def test_get_exploration_logs_filtered(self, test_db):
        """Test filtering exploration logs by source."""
        log_exploration(source_id="microns", action_type="navigation")
        log_exploration(source_id="bizbuysell", action_type="navigation")

        microns_logs = get_exploration_logs(source_id="microns")
        assert len(microns_logs) == 1

        all_logs = get_exploration_logs()
        assert len(all_logs) == 2
