from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from mm.config.settings import BitMartCredentials
from mm.exchange.bitmart.websocket import (
    depth_increase_channel,
    login,
    private_all_orders_channel,
    private_balance_channel,
    subscribe,
)
from mm.exchange.bitmart.ws_client import private_client, public_client


@dataclass(frozen=True)
class SmokeError:
    category: str
    message: str


@dataclass(frozen=True)
class WsSmokeReport:
    target: str
    dry_run: bool
    channels: List[str]
    subscription: Dict[str, object]
    login_payload: Optional[Dict[str, object]] = None
    received_count: int = 0
    first_message: Optional[Dict[str, object]] = None
    errors: List[SmokeError] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


async def public_ws_smoke(symbol: str, dry_run: bool = True, timeout_sec: float = 5.0) -> WsSmokeReport:
    channels = [depth_increase_channel(symbol)]
    subscription = subscribe(channels).as_dict()
    if dry_run:
        return WsSmokeReport("public", True, channels, subscription)
    return await _network_smoke("public", public_client(channels), channels, subscription, None, timeout_sec)


async def private_ws_smoke(
    credentials: BitMartCredentials,
    dry_run: bool = True,
    timeout_sec: float = 5.0,
) -> WsSmokeReport:
    channels = [private_all_orders_channel(), private_balance_channel()]
    subscription = subscribe(channels).as_dict()
    login_payload = login(credentials).as_dict()
    if dry_run:
        return WsSmokeReport("private", True, channels, subscription, login_payload)
    if not credentials.present:
        return WsSmokeReport(
            "private",
            False,
            channels,
            subscription,
            login_payload,
            errors=[SmokeError("credentials", "missing BitMart credentials")],
        )
    return await _network_smoke(
        "private",
        private_client(channels, credentials),
        channels,
        subscription,
        login_payload,
        timeout_sec,
    )


async def _network_smoke(
    target: str,
    client: object,
    channels: Iterable[str],
    subscription: Dict[str, object],
    login_payload: Optional[Dict[str, object]],
    timeout_sec: float,
) -> WsSmokeReport:
    received: List[Dict[str, object]] = []
    errors: List[SmokeError] = []
    try:
        stream = client.stream()
        while True:
            try:
                message = await asyncio.wait_for(stream.__anext__(), timeout=timeout_sec)
            except asyncio.TimeoutError:
                errors.append(SmokeError("timeout", "no WebSocket message received within {0}s".format(timeout_sec)))
                break
            except StopAsyncIteration:
                break
            received.append(message)
            if received:
                break
    except Exception as exc:
        errors.append(classify_ws_exception(exc))
    return WsSmokeReport(
        target=target,
        dry_run=False,
        channels=list(channels),
        subscription=subscription,
        login_payload=login_payload,
        received_count=len(received),
        first_message=received[0] if received else None,
        errors=errors,
    )


def classify_ws_exception(exc: Exception) -> SmokeError:
    name = exc.__class__.__name__
    message = str(exc) or name
    lowered = message.lower()
    if "websockets" in lowered or "install optional dependency" in lowered:
        return SmokeError("dependency", message)
    if "handshake" in lowered or "invalidstatus" in lowered or "protocol" in lowered:
        return SmokeError("protocol", message)
    if "timed out" in lowered or "timeout" in lowered:
        return SmokeError("timeout", message)
    return SmokeError("network", message)
