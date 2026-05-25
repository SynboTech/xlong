import json
import os
import tempfile
import unittest
import asyncio

from mm.config.settings import BitMartCredentials
from mm.exchange.bitmart.ws_client import BitMartWebSocketClient, WebSocketAuthError, WebSocketConfig, private_client, public_client
from mm.exchange.bitmart.websocket import depth_increase_channel, private_all_orders_channel
from mm.persistence.replay import EventLogReplay


class WsClientAndReplayTest(unittest.TestCase):
    def test_ws_client_factories(self):
        pub = public_client([depth_increase_channel("BTC_USDT")])
        self.assertIn("api?protocol=1.1", pub.config.url)
        priv = private_client([private_all_orders_channel()], BitMartCredentials("k", "s", "m"))
        self.assertIn("user?protocol=1.1", priv.config.url)
        self.assertEqual(priv.config.credentials.api_key, "k")

    def test_private_ws_login_ack_is_required(self):
        async def scenario():
            client = BitMartWebSocketClient(
                WebSocketConfig(
                    url="wss://example.test",
                    channels=[private_all_orders_channel()],
                    credentials=BitMartCredentials("k", "s", "m"),
                    login_timeout_sec=0.1,
                )
            )
            ack = await client._login_private(FakeWs([json.dumps({"event": "login", "success": True})]))
            self.assertTrue(ack["success"])
            with self.assertRaises(WebSocketAuthError):
                await client._login_private(FakeWs([json.dumps({"event": "login", "success": False})]))

        asyncio.run(scenario())

    def test_replay_counts_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": 1, "type": "a", "payload": {"x": 1}}) + "\n")
                fh.write(json.dumps({"ts": 2, "type": "b", "payload": {"x": 2}}) + "\n")
                fh.write(json.dumps({"ts": 3, "type": "a", "payload": {"x": 3}}) + "\n")
            replay = EventLogReplay(path)
            self.assertEqual(replay.count_by_type(), {"a": 2, "b": 1})
            self.assertEqual(len(list(replay.events("a"))), 2)

class FakeWs:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    async def recv(self):
        if not self.messages:
            await asyncio.sleep(0.2)
            return "{}"
        return self.messages.pop(0)


if __name__ == "__main__":
    unittest.main()
