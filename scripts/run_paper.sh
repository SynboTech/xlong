#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m mm.main --config config/paper.json --ticks "${1:-10}"

