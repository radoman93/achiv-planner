#!/bin/bash

# Only run migrations from the backend (uvicorn) container
if echo "$@" | grep -q "uvicorn"; then
    echo "Running Alembic migrations..."
    alembic upgrade head
    echo "Migrations complete."
fi

exec "$@"
