"""Database schema definitions."""

import sqlite3
from pathlib import Path

from ..config import config


SCHEMA = """
-- listings table
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    category TEXT,
    asking_price INTEGER,
    annual_revenue INTEGER,
    customers INTEGER,
    launched_year INTEGER,
    posted_at TIMESTAMP,
    description TEXT,
    location TEXT,
    country TEXT,
    raw_data JSON,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, external_id)
);

-- exploration_logs table (track what Claude Chrome discovered)
CREATE TABLE IF NOT EXISTS exploration_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    action_type TEXT NOT NULL,
    selector TEXT,
    description TEXT,
    example_value TEXT,
    screenshot_path TEXT
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source_id);
CREATE INDEX IF NOT EXISTS idx_listings_first_seen ON listings(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_exploration_source ON exploration_logs(source_id);
"""


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Initialize the database with schema.

    Args:
        db_path: Optional path to database. Uses config default if not provided.

    Returns:
        Connection to the initialized database.
    """
    if db_path is None:
        db_path = config.db_path

    config.ensure_dirs()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
