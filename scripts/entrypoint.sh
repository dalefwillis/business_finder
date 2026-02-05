#!/bin/bash
# Entrypoint script for scheduled scraper jobs
# Loads .env and adds a random 10-300s delay before running the command

set -e

# Load environment from .env file if it exists
if [ -f /app/.env ]; then
    set -a
    source /app/.env
    set +a
fi

# Random delay between 10-300 seconds
delay=$((RANDOM % 290 + 10))
echo "Waiting ${delay}s before starting (random delay)..."
sleep "$delay"

# Execute the command passed as arguments
exec "$@"
