#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export COMPOSE_FILE="$ROOT/infrastructure/docker/compose.yaml"
mkdir -p input output models
docker compose run --rm --build --user "$(id -u):$(id -g)" ocr
