# Business Finder

Business listing aggregator and scorer for micro-SaaS acquisitions.

## Setup

```bash
poetry install
poetry run playwright install chromium
```

## Usage

### Exploration Script

Use alongside Claude Chrome to discover selectors:

```bash
poetry run python scripts/explore_microns.py
```

### Running Tests

```bash
poetry run pytest
```
