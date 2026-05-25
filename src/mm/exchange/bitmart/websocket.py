from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List

from mm.common.decimal import D
from mm.common.time import utc_ms
from mm.common.types import Balance, Liquidity, OrderStatus, OrderUpdate, Side
from mm.config.settings import BitMartCredentials
from mm.exchange.bitmart.signer import sign


PUBLIC_WS_URL = "wss://ws-manager-compress.bitmart.com/api?protocol=1.1"
PRIVATE_WS_URL = "wss://ws-manager-compress.bitmart.com/user?protocol=1.1"


@dataclass(frozen=True)
class BitMartWsSubscription:
    op: str
    args: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {"op": self.op, "args": self.args}


def ticker_channel(symbol: str) -> str:
    return "spot/ticker:{0}".format(symbol)


def depth_channel(symbol: str, depth: int = 20) -> str:
    return "spot/depth{0}:{1}".format(depth, symbol)


def depth_increase_channel(symbol: str) -> str:
    return "spot/depth/increase100:{0}".format(symbol)


def trade_channel(symbol: str) -> str:
    return "spot/trade:{0}".format(symbol)


def private_order_channel(symbol: str) -> str:
    return "spot/user/order:{0}".format(symbol)


def private_all_orders_channel() -> str:
    return "spot/user/orders:ALL_SYMBOLS"


def private_balance_channel() -> str:
    return "spot/user/balance:BALANCE_UPDATE"


def subscribe(channels: Iterable[str]) -> BitMartWsSubscription:
    return BitMartWsSubscription(op="subscribe", args=list(channels))


def login(credentials: BitMartCredentials) -> BitMartWsSubscription:
    ts = utc_ms()
    digest = sign(ts, credentials.api_memo, "bitmart.WebSocket", credentials.api_secret)
    return BitMartWsSubscription(op="login", args=[credentials.api_key, str(ts), digest])


def parse_private_order_update(row: Dict[str, Any]) -> OrderUpdate:
    state = str(row.get("order_state") or row.get("state") or "")
    state_map = {
        "new": OrderStatus.OPEN,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELED,
        "partially_canceled": OrderStatus.PARTIALLY_CANCELED,
        "4": OrderStatus.OPEN,
        "5": OrderStatus.PARTIALLY_FILLED,
        "6": OrderStatus.FILLED,
        "8": OrderStatus.CANCELED,
        "12": OrderStatus.PARTIALLY_CANCELED,
    }
    return OrderUpdate(
        symbol=str(row.get("symbol", "")),
        client_order_id=str(row.get("client_order_id") or row.get("clientOrderId") or ""),
        exchange_order_id=str(row.get("order_id") or row.get("orderId") or ""),
        status=state_map.get(state, OrderStatus.UNKNOWN),
        filled_size=D(row.get("filled_size", row.get("filledSize", "0"))),
        avg_fill_price=D(row.get("last_fill_price", row.get("price", "0"))) if row.get("price") or row.get("last_fill_price") else None,
        message="bitmart private order update",
        side=Side(str(row.get("side", "buy"))) if row.get("side") in {"buy", "sell"} else None,
    )


def parse_balance_update(row: Dict[str, Any]) -> List[Balance]:
    balances: List[Balance] = []
    for item in row.get("balance_details", []):
        balances.append(
            Balance(
                currency=str(item.get("ccy", "")),
                available=D(item.get("av_bal", "0")),
                frozen=D(item.get("fz_bal", "0")),
            )
        )
    return balances


def parse_trade_liquidity(exec_type: str) -> Liquidity:
    if exec_type == "M":
        return Liquidity.MAKER
    if exec_type == "T":
        return Liquidity.TAKER
    return Liquidity.UNKNOWN


def parse_side(value: str) -> Side:
    return Side.BUY if value == "buy" else Side.SELL


def parse_depth_messages(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    if message.get("table") != "spot/depth/increase100":
        return []
    return [row for row in message.get("data", []) if isinstance(row, dict)]
