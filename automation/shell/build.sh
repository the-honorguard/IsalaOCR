#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export COMPOSE_FILE="$ROOT/infrastructure/docker/compose.yaml"
docker compose build --pull
