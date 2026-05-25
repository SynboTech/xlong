from __future__ import annotations

from typing import Dict, Set

from mm.common.types import OrderStatus


TERMINAL_STATES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.PARTIALLY_CANCELED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
}


VALID_TRANSITIONS: Dict[OrderStatus, Set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.SUBMITTING, OrderStatus.REJECTED, OrderStatus.UNKNOWN},
    OrderStatus.SUBMITTING: {
        OrderStatus.ACKED,
        OrderStatus.OPEN,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.PARTIALLY_CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.ACKED: {
        OrderStatus.OPEN,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELING,
        OrderStatus.CANCELED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.OPEN: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELING,
        OrderStatus.CANCELED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.FILLED,
        OrderStatus.CANCELING,
        OrderStatus.PARTIALLY_CANCELED,
        OrderStatus.CANCELED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.CANCELING: {
        OrderStatus.CANCELED,
        OrderStatus.PARTIALLY_CANCELED,
        OrderStatus.FILLED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.UNKNOWN: {
        OrderStatus.OPEN,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.PARTIALLY_CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    },
}


def is_terminal(status: OrderStatus) -> bool:
    return status in TERMINAL_STATES


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    if current == new:
        return True
    if is_terminal(current):
        return False
    return new in VALID_TRANSITIONS.get(current, set())
