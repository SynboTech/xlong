#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.common.types import to_jsonable
from mm.config.audit import build_config_audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Produce a config audit fingerprint")
    parser.add_argument("--config", default="config/paper.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_config_audit(args.config)
    print(json.dumps(to_jsonable(asdict(report)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

