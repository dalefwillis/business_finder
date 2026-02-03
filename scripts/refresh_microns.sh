#!/bin/bash
export RANDOM_DELAY=1
exec /app/scripts/entrypoint.sh python scripts/run_microns_scrape.py --refresh
