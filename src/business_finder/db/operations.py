"""Database operations."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import config
from ..models.listing import ListingCreate
from .schema import init_db


_connection: sqlite3.Connection | None = None


def get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Get database connection, initializing if needed.

    Args:
        db_path: Optional path to database. Uses config default if not provided.

    Returns:
        Database connection.
    """
    global _connection
    if _connection is None:
        _connection = init_db(db_path)
    return _connection


def close_db() -> None:
    """Close the database connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def save_listing(
    source_id: str,
    external_id: str,
    url: str,
    title: str | None = None,
    category: str | None = None,
    asking_price: int | None = None,
    annual_revenue: int | None = None,
    customers: int | None = None,
    launched_year: int | None = None,
    posted_at: datetime | None = None,
    description: str | None = None,
    raw_data: dict[str, Any] | None = None,
) -> str:
    """Save or update a listing.

    Args:
        source_id: Source identifier (e.g., 'microns', 'bizbuysell')
        external_id: ID from the source platform
        url: Listing URL
        title: Listing title
        category: Business category
        asking_price: Asking price in cents
        annual_revenue: Annual revenue in cents (ARR or TTM)
        customers: Number of customers
        launched_year: Year business was launched
        posted_at: When listing was posted to platform
        description: Listing description
        raw_data: Raw scraped data as dict

    Returns:
        The listing ID.
    """
    conn = get_db()
    listing_id = str(uuid.uuid4())

    conn.execute(
        """
        INSERT INTO listings (
            id, source_id, external_id, url, title, category,
            asking_price, annual_revenue, customers, launched_year,
            posted_at, description, raw_data, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(source_id, external_id) DO UPDATE SET
            url = excluded.url,
            title = excluded.title,
            category = excluded.category,
            asking_price = excluded.asking_price,
            annual_revenue = excluded.annual_revenue,
            customers = excluded.customers,
            launched_year = excluded.launched_year,
            posted_at = excluded.posted_at,
            description = excluded.description,
            raw_data = excluded.raw_data,
            updated_at = CURRENT_TIMESTAMP,
            last_seen_at = CURRENT_TIMESTAMP
        """,
        (
            listing_id,
            source_id,
            external_id,
            url,
            title,
            category,
            asking_price,
            annual_revenue,
            customers,
            launched_year,
            posted_at.isoformat() if posted_at else None,
            description,
            json.dumps(raw_data) if raw_data else None,
        ),
    )
    conn.commit()
    return listing_id


def save_listing_from_model(listing: ListingCreate) -> tuple[str, bool]:
    """Save a listing from a ListingCreate model.

    Args:
        listing: The ListingCreate model to save.

    Returns:
        Tuple of (listing_id, is_new) where is_new is True if this was
        a new listing, False if it was an update to an existing one.
    """
    # Check if listing already exists
    existing = get_listing_by_external_id(listing.source_id, listing.external_id)
    is_new = existing is None

    listing_id = save_listing(
        source_id=listing.source_id,
        external_id=listing.external_id,
        url=listing.url,
        title=listing.title,
        category=listing.category,
        asking_price=listing.asking_price,
        annual_revenue=listing.annual_revenue,
        customers=listing.customers,
        launched_year=listing.launched_year,
        posted_at=listing.posted_at,
        description=listing.description,
        raw_data=listing.raw_data,
    )

    # If it was an update, return the existing ID
    if not is_new and existing:
        listing_id = existing["id"]

    return listing_id, is_new


def get_listing_by_external_id(source_id: str, external_id: str) -> dict[str, Any] | None:
    """Get a listing by source and external ID.

    Args:
        source_id: Source identifier (e.g., 'microns')
        external_id: ID from the source platform

    Returns:
        Listing data as dict, or None if not found.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM listings WHERE source_id = ? AND external_id = ?",
        (source_id, external_id),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_listing(listing_id: str) -> dict[str, Any] | None:
    """Get a listing by ID.

    Args:
        listing_id: The listing ID.

    Returns:
        Listing data as dict, or None if not found.
    """
    conn = get_db()
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if row is None:
        return None
    return dict(row)


def get_all_listings(source_id: str | None = None) -> list[dict[str, Any]]:
    """Get all listings, optionally filtered by source.

    Args:
        source_id: Optional source filter.

    Returns:
        List of listing dicts.
    """
    conn = get_db()
    if source_id:
        rows = conn.execute(
            "SELECT * FROM listings WHERE source_id = ? ORDER BY first_seen_at DESC",
            (source_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM listings ORDER BY first_seen_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def log_exploration(
    source_id: str,
    action_type: str,
    selector: str | None = None,
    description: str | None = None,
    example_value: str | None = None,
    screenshot_path: str | None = None,
) -> int:
    """Log an exploration action.

    Args:
        source_id: Source being explored
        action_type: Type of action ('navigation', 'click', 'extract', 'selector')
        selector: CSS/XPath selector if applicable
        description: Human description of what was discovered
        example_value: Example value extracted
        screenshot_path: Path to screenshot if taken

    Returns:
        The log entry ID.
    """
    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO exploration_logs (source_id, action_type, selector, description, example_value, screenshot_path)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_id, action_type, selector, description, example_value, screenshot_path),
    )
    conn.commit()
    return cursor.lastrowid or 0


def get_exploration_logs(source_id: str | None = None) -> list[dict[str, Any]]:
    """Get exploration logs, optionally filtered by source.

    Args:
        source_id: Optional source filter.

    Returns:
        List of log entry dicts.
    """
    conn = get_db()
    if source_id:
        rows = conn.execute(
            "SELECT * FROM exploration_logs WHERE source_id = ? ORDER BY created_at DESC",
            (source_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM exploration_logs ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]
