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


class WebSocketAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebSocketConfig:
    url: str
    channels: Iterable[str]
    credentials: Optional[BitMartCredentials] = None
    ping_interval_sec: int = 15
    reconnect_delay_sec: int = 3
    login_timeout_sec: float = 5.0


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
                        await self._login_private(ws)
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

    async def _login_private(self, ws) -> Dict[str, Any]:
        if self.config.credentials is None:
            return {}
        await ws.send(json.dumps(login(self.config.credentials).as_dict()))
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.config.login_timeout_sec)
            except asyncio.TimeoutError as exc:
                raise WebSocketAuthError("BitMart private WebSocket login ack timed out") from exc
            message = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            payload = json.loads(message)
            if self._is_login_ack(payload):
                if self._is_failed_ack(payload):
                    raise WebSocketAuthError("BitMart private WebSocket login failed: {0}".format(payload))
                return payload
            if self._is_error_ack(payload):
                raise WebSocketAuthError("BitMart private WebSocket error before login ack: {0}".format(payload))

    @staticmethod
    def _is_login_ack(payload: Dict[str, Any]) -> bool:
        op = str(payload.get("op") or payload.get("event") or payload.get("action") or "").lower()
        return op == "login" or str(payload.get("type") or "").lower() == "login"

    @staticmethod
    def _is_error_ack(payload: Dict[str, Any]) -> bool:
        event = str(payload.get("event") or payload.get("op") or "").lower()
        code = payload.get("code")
        return event == "error" or (code is not None and str(code) not in {"0", "1000"})

    @staticmethod
    def _is_failed_ack(payload: Dict[str, Any]) -> bool:
        if payload.get("success") is False:
            return True
        if payload.get("errorCode") or payload.get("error_code"):
            return True
        code = payload.get("code")
        return code is not None and str(code) not in {"0", "1000"}


def public_client(channels: Iterable[str]) -> BitMartWebSocketClient:
    return BitMartWebSocketClient(WebSocketConfig(url=PUBLIC_WS_URL, channels=channels))


def private_client(channels: Iterable[str], credentials: BitMartCredentials) -> BitMartWebSocketClient:
    return BitMartWebSocketClient(
        WebSocketConfig(url=PRIVATE_WS_URL, channels=channels, credentials=credentials)
    )
