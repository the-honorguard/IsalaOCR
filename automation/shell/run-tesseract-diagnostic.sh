#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export COMPOSE_FILE="$ROOT/infrastructure/docker/compose.yaml"
mkdir -p input output
docker compose run --rm --user "$(id -u):$(id -g)" ocr process \
  --input /input \
  --output /output \
  --config /app/config/app.yaml \
  --engine tesseract
