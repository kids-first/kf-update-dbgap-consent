#!/bin/bash

# Dataservice Health Check 

set -e

START_TIME=$SECONDS
DATASERVICE_ENDPOINT=${DATASERVICE_ENDPOINT:-http://localhost:5000}

echo "⛑️ Waiting for service to become healthy ..."
until $(curl --output /dev/null --head --silent --fail $DATASERVICE_ENDPOINT/status)
do
    echo -n "."
    sleep 2
done

ELAPSED=$((( SECONDS - START_TIME ) / 60 ))
FORMATTED_ELAPSED=$(printf "%.2f" $ELAPSED)
echo ""
echo "Elapsed time $FORMATTED_ELAPSED minutes"

echo "✅ --- Development environment setup complete! ---"

