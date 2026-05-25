#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m mm.main --config config/paper.json --ticks "${1:-10}"
PYTHONPATH=src python3 scripts/generate_acceptance_report.py
