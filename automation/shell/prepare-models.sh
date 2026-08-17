#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export COMPOSE_FILE="$ROOT/infrastructure/docker/compose.yaml"
mkdir -p models
docker compose --profile setup run --rm --user "$(id -u):$(id -g)" model-prep
