from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

from mm.common.decimal import D, decimal_to_str
from mm.common.time import utc_ms
from mm.common.types import OrderRequest, OrderStatus, Side


@dataclass
class OrderRecord:
    symbol: str
    side: Side
    price: Optional[Decimal]
    size: Decimal
    order_type: str
    client_order_id: str
    strategy: str
    level: Optional[int]
    status: OrderStatus = OrderStatus.CREATED
    exchange_order_id: Optional[str] = None
    filled_size: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    created_at_ms: int = 0
    updated_at_ms: int = 0
    last_message: str = ""

    @classmethod
    def from_request(cls, request: OrderRequest) -> "OrderRecord":
        now = utc_ms()
        return cls(
            symbol=request.symbol,
            side=request.side,
            price=request.price,
            size=request.size,
            order_type=request.order_type.value,
            client_order_id=request.client_order_id,
            strategy=request.strategy,
            level=request.level,
            created_at_ms=now,
            updated_at_ms=now,
        )

    @property
    def remaining_size(self) -> Decimal:
        remaining = self.size - self.filled_size
        if remaining < 0:
            return Decimal("0")
        return remaining

    @property
    def notional(self) -> Decimal:
        if self.price is None:
            return Decimal("0")
        return self.price * self.size

    @property
    def open_notional(self) -> Decimal:
        if self.price is None:
            return Decimal("0")
        return self.price * self.remaining_size

    def to_dict(self) -> Dict[str, object]:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "price": decimal_to_str(self.price) if self.price is not None else None,
            "size": decimal_to_str(self.size),
            "order_type": self.order_type,
            "client_order_id": self.client_order_id,
            "strategy": self.strategy,
            "level": self.level,
            "status": self.status.value,
            "exchange_order_id": self.exchange_order_id,
            "filled_size": decimal_to_str(self.filled_size),
            "avg_fill_price": decimal_to_str(self.avg_fill_price) if self.avg_fill_price is not None else None,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "last_message": self.last_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "OrderRecord":
        return cls(
            symbol=str(data["symbol"]),
            side=Side(str(data["side"])),
            price=D(data["price"]) if data.get("price") is not None else None,
            size=D(data["size"]),
            order_type=str(data["order_type"]),
            client_order_id=str(data["client_order_id"]),
            strategy=str(data["strategy"]),
            level=int(data["level"]) if data.get("level") is not None else None,
            status=OrderStatus(str(data["status"])),
            exchange_order_id=str(data["exchange_order_id"]) if data.get("exchange_order_id") else None,
            filled_size=D(data.get("filled_size", "0")),
            avg_fill_price=D(data["avg_fill_price"]) if data.get("avg_fill_price") is not None else None,
            created_at_ms=int(data.get("created_at_ms", 0)),
            updated_at_ms=int(data.get("updated_at_ms", 0)),
            last_message=str(data.get("last_message", "")),
        )
