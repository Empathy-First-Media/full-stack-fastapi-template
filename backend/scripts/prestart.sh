#! /usr/bin/env bash

set -e
set -x

# API namespace only. This refuses to run without a reviewed API branch and
# distinct API_MIGRATION_DATABASE_URL; never replay the legacy public history.
alembic -c alembic-api.ini upgrade api@head
