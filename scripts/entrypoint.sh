#!/bin/bash
# Entrypoint script for scheduled scraper jobs
# Adds a random delay before running the actual command

set -e

# Load environment from .env file if it exists
if [ -f /app/.env ]; then
    set -a
    source /app/.env
    set +a
fi

# Random delay between 10-300 seconds (if RANDOM_DELAY is set)
if [ -n "$RANDOM_DELAY" ]; then
    delay=$((RANDOM % 290 + 10))
    echo "Waiting ${delay}s before starting (random delay)..."
    sleep "$delay"
fi

# Execute the command passed as arguments
exec "$@"
