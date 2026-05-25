from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .decimal import D, ceil_to_increment, decimal_to_str, floor_to_increment
from .time import utc_ms


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"
    LIMIT_MAKER = "limit_maker"
    IOC = "ioc"


class OrderStatus(str, Enum):
    CREATED = "created"
    SUBMITTING = "submitting"
    ACKED = "acked"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELING = "canceling"
    CANCELED = "canceled"
    PARTIALLY_CANCELED = "partially_canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class Liquidity(str, Enum):
    MAKER = "maker"
    TAKER = "taker"
    UNKNOWN = "unknown"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE_READ_ONLY = "live_read_only"
    LIVE_DRY_RUN = "live_dry_run"
    LIVE = "live"


class RiskDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    SAFE_MODE = "safe_mode"


@dataclass(frozen=True)
class MarketRule:
    symbol: str
    base: str
    quote: str
    price_increment: Decimal
    size_increment: Decimal
    base_min_size: Decimal
    min_notional: Decimal

    @classmethod
    def from_config(cls, symbol: str, data: Dict[str, Any]) -> "MarketRule":
        return cls(
            symbol=symbol,
            base=str(data["base"]),
            quote=str(data["quote"]),
            price_increment=D(data["price_increment"]),
            size_increment=D(data["size_increment"]),
            base_min_size=D(data["base_min_size"]),
            min_notional=D(data.get("min_notional", "0")),
        )

    def align_price(self, side: Side, price: Decimal) -> Decimal:
        if side == Side.BUY:
            return floor_to_increment(price, self.price_increment)
        return ceil_to_increment(price, self.price_increment)

    def align_size(self, size: Decimal) -> Decimal:
        return floor_to_increment(size, self.size_increment)

    def valid_minimums(self, price: Decimal, size: Decimal) -> bool:
        return size >= self.base_min_size and (price * size) >= self.min_notional


@dataclass
class Balance:
    currency: str
    available: Decimal
    frozen: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.available + self.frozen


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    bid: Decimal
    bid_size: Decimal
    ask: Decimal
    ask_size: Decimal
    last: Optional[Decimal]
    exchange: str = "paper"
    timestamp_ms: int = field(default_factory=utc_ms)
    receive_time_ms: int = field(default_factory=utc_ms)
    bids: List[Tuple[Decimal, Decimal]] = field(default_factory=list)
    asks: List[Tuple[Decimal, Decimal]] = field(default_factory=list)

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def age_ms(self) -> int:
        return utc_ms() - self.receive_time_ms

    def bid_levels(self, levels: int = 1) -> List[Tuple[Decimal, Decimal]]:
        rows = self.bids or ([(self.bid, self.bid_size)] if self.bid > 0 and self.bid_size > 0 else [])
        return sorted(rows, key=lambda item: item[0], reverse=True)[: max(0, levels)]

    def ask_levels(self, levels: int = 1) -> List[Tuple[Decimal, Decimal]]:
        rows = self.asks or ([(self.ask, self.ask_size)] if self.ask > 0 and self.ask_size > 0 else [])
        return sorted(rows, key=lambda item: item[0])[: max(0, levels)]

    def depth_sizes(self, levels: int = 1) -> Tuple[Decimal, Decimal]:
        bid_size = sum((size for _, size in self.bid_levels(levels)), Decimal("0"))
        ask_size = sum((size for _, size in self.ask_levels(levels)), Decimal("0"))
        return bid_size, ask_size


@dataclass(frozen=True)
class QuoteIntent:
    symbol: str
    side: Side
    price: Decimal
    size: Decimal
    level: int
    strategy: str
    reason: str


@dataclass(frozen=True)
class OrderIntent:
    action: str
    symbol: str
    side: Optional[Side]
    price: Optional[Decimal]
    size: Optional[Decimal]
    client_order_id: Optional[str]
    old_client_order_id: Optional[str]
    strategy: str
    level: Optional[int] = None
    order_type: OrderType = OrderType.LIMIT_MAKER
    reason: str = ""


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Side
    order_type: OrderType
    size: Decimal
    price: Optional[Decimal]
    client_order_id: str
    strategy: str
    level: Optional[int] = None
    stp_mode: str = "cancel_both"


@dataclass(frozen=True)
class CancelRequest:
    symbol: str
    client_order_id: str
    exchange_order_id: Optional[str] = None
    reason: str = ""


@dataclass(frozen=True)
class OrderAck:
    accepted: bool
    client_order_id: str
    exchange_order_id: Optional[str]
    status: OrderStatus
    message: str = ""
    raw: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class CancelAck:
    accepted: bool
    client_order_id: str
    exchange_order_id: Optional[str]
    status: OrderStatus
    message: str = ""
    raw: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class FillEvent:
    symbol: str
    client_order_id: str
    exchange_order_id: Optional[str]
    side: Side
    price: Decimal
    size: Decimal
    fee: Decimal
    fee_currency: str
    liquidity: Liquidity
    trade_id: str
    timestamp_ms: int = field(default_factory=utc_ms)


@dataclass(frozen=True)
class OrderUpdate:
    symbol: str
    client_order_id: str
    exchange_order_id: Optional[str]
    status: OrderStatus
    filled_size: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    message: str = ""
    timestamp_ms: int = field(default_factory=utc_ms)
    side: Optional[Side] = None


@dataclass(frozen=True)
class RiskResult:
    decision: RiskDecision
    rule: str
    message: str
    intent: Optional[OrderIntent] = None

    @property
    def approved(self) -> bool:
        return self.decision == RiskDecision.APPROVED


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_to_str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {key: to_jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    return value
