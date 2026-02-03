#!/bin/bash
export RANDOM_DELAY=1
exec /app/scripts/entrypoint.sh python scripts/run_flippa_scrape.py --refresh
