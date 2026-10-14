#!/bin/sh
set -e

# Run database migrations if AUTO_MIGRATE is true
if [ "${AUTO_MIGRATE:-false}" = "true" ]; then
    echo "AUTO_MIGRATE is set to true. Applying database migrations..."
    alembic upgrade head
    echo "Database migrations applied successfully."
fi

# Execute the main container command
exec "$@"

