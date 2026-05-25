from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterable, Optional

from mm.config.settings import BitMartCredentials
from mm.exchange.bitmart.websocket import (
    PUBLIC_WS_URL,
    PRIVATE_WS_URL,
    BitMartWsSubscription,
    login,
    subscribe,
)


class WebSocketDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebSocketConfig:
    url: str
    channels: Iterable[str]
    credentials: Optional[BitMartCredentials] = None
    ping_interval_sec: int = 15
    reconnect_delay_sec: int = 3


class BitMartWebSocketClient:
    def __init__(self, config: WebSocketConfig) -> None:
        self.config = config
        self.connected = False
        self.reconnect_count = 0

    async def stream(self) -> AsyncIterator[Dict[str, Any]]:
        websockets = await self._load_websockets()
        while True:
            try:
                async with websockets.connect(self.config.url, ping_interval=self.config.ping_interval_sec) as ws:
                    self.connected = True
                    if self.config.credentials is not None:
                        await ws.send(json.dumps(login(self.config.credentials).as_dict()))
                    await ws.send(json.dumps(subscribe(self.config.channels).as_dict()))
                    async for message in ws:
                        if isinstance(message, bytes):
                            message = message.decode("utf-8")
                        yield json.loads(message)
            finally:
                self.connected = False
                self.reconnect_count += 1
                await asyncio.sleep(self.config.reconnect_delay_sec)

    @staticmethod
    async def _load_websockets():
        try:
            import websockets  # type: ignore
        except ImportError as exc:
            raise WebSocketDependencyError(
                "Install optional dependency with `pip install websockets` to use live WebSocket streaming"
            ) from exc
        return websockets


def public_client(channels: Iterable[str]) -> BitMartWebSocketClient:
    return BitMartWebSocketClient(WebSocketConfig(url=PUBLIC_WS_URL, channels=channels))


def private_client(channels: Iterable[str], credentials: BitMartCredentials) -> BitMartWebSocketClient:
    return BitMartWebSocketClient(
        WebSocketConfig(url=PRIVATE_WS_URL, channels=channels, credentials=credentials)
    )

