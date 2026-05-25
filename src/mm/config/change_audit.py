from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from mm.config.settings import AppSettings


@dataclass(frozen=True)
class ConfigChange:
    path: str
    old_value: Optional[str]
    new_value: Optional[str]


@dataclass(frozen=True)
class ConfigChangeReport:
    changed: bool
    changes: List[ConfigChange]


def diff_settings(old: AppSettings, new: AppSettings) -> ConfigChangeReport:
    changes: List[ConfigChange] = []
    _compare(changes, "trading_mode", old.trading_mode.value, new.trading_mode.value)
    _compare(changes, "enable_order_submission", str(old.enable_order_submission), str(new.enable_order_submission))
    _compare(changes, "quote_interval_ms", str(old.quote_interval_ms), str(new.quote_interval_ms))
    _compare(changes, "min_requote_interval_ms", str(old.min_requote_interval_ms), str(new.min_requote_interval_ms))
    for key, old_value, new_value in [
        ("risk.max_order_value_usdt", old.risk.max_order_value_usdt, new.risk.max_order_value_usdt),
        ("risk.max_total_open_value_usdt", old.risk.max_total_open_value_usdt, new.risk.max_total_open_value_usdt),
        ("risk.max_open_orders", old.risk.max_open_orders, new.risk.max_open_orders),
        ("risk.max_position_base", old.risk.max_position_base, new.risk.max_position_base),
        ("risk.max_daily_loss_usdt", old.risk.max_daily_loss_usdt, new.risk.max_daily_loss_usdt),
        ("risk.max_price_deviation_bps", old.risk.max_price_deviation_bps, new.risk.max_price_deviation_bps),
    ]:
        _compare(changes, key, str(old_value), str(new_value))
    old_strategies = _strategy_map(old)
    new_strategies = _strategy_map(new)
    for key in sorted(set(old_strategies) | set(new_strategies)):
        _compare(changes, "strategies.{0}".format(key), old_strategies.get(key), new_strategies.get(key))
    return ConfigChangeReport(changed=bool(changes), changes=changes)


def _compare(changes: List[ConfigChange], path: str, old_value: Optional[str], new_value: Optional[str]) -> None:
    if old_value != new_value:
        changes.append(ConfigChange(path=path, old_value=old_value, new_value=new_value))


def _strategy_map(settings: AppSettings) -> Dict[str, str]:
    result = {}
    for strategy in settings.strategies:
        key = strategy.key
        result[key] = "enabled={0};params={1}".format(strategy.enabled, sorted(strategy.params.items()))
    return result
