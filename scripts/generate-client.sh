#! /usr/bin/env bash

set -euo pipefail

uv run --no-active --directory backend --locked --no-sync \
  python scripts/export_openapi.py --output ../frontend/openapi.json "$@"
bun run --filter frontend generate-client --no-log-file
