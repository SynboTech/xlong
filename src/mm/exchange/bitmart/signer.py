from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def stable_json(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def sign(timestamp_ms: int, memo: str, body: Any, secret: str) -> str:
    payload = "{0}#{1}#{2}".format(timestamp_ms, memo, stable_json(body))
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

