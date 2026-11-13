#!/bin/sh
# Start the worker: make sure its pool exists, register what prefect.yaml
# declares, then take one flow run at a time.
set -e
mkdir -p "$HOME"
prefect work-pool inspect georing > /dev/null 2>&1 || prefect work-pool create georing --type process
# Backfills and rebuilds queue behind the Slot of the hour (see georing.flow).
prefect work-queue inspect catch-up --pool georing > /dev/null 2>&1 \
    || prefect work-queue create catch-up --pool georing --priority 2
prefect --no-prompt deploy --all
exec prefect worker start --pool georing --type process --limit 1
