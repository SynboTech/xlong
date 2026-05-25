# Market Maker Acceptance Report

Generated: 2026-05-25T18:10:59.356446+00:00

## Result

Status: **PASS**

## Unit Tests

Exit code: `0`

```text
..................................................................................
----------------------------------------------------------------------
Ran 82 tests in 3.114s

OK
```

## Config Audit

```json
{
  "enabled_strategies": [
    "basic_mm:BTC_USDT",
    "inventory_skew:BTC_USDT",
    "range-buy-btc-usdt",
    "range-sell-btc-usdt"
  ],
  "exchange": "paper",
  "path": "/Users/ck/Documents/Codex/xlong/config/paper.json",
  "risk_limits": {
    "max_daily_loss_usdt": "20",
    "max_open_orders": "10",
    "max_order_value_usdt": "10",
    "max_position_base": "0.02",
    "max_price_deviation_bps": "50",
    "max_total_open_value_usdt": "50",
    "per_strategy_max_open_orders": "{'basic_mm': 8}",
    "per_strategy_max_open_value_usdt": "{'basic_mm': '50'}",
    "per_strategy_max_order_value_usdt": "{'basic_mm': '10'}"
  },
  "sha256": "b6cc3603df9e3385aa52e0e45ae08c48045f76f1ff577978f1ae8b147166d37f",
  "symbols": [
    "BTC_USDT",
    "SYNBO_USDT"
  ],
  "trading_mode": "paper"
}
```

## Paper Run

```json
{
  "fills": 6,
  "open_orders": 0,
  "orders_total": 20,
  "rejected_intents": 0,
  "safe_mode": false,
  "ticks": 10
}
```

## Health

```json
{
  "checks": [
    "safe_mode",
    "unknown_orders",
    "market_data_stale",
    "orderbook_gaps"
  ],
  "failures": [],
  "ok": true
}
```

## Runtime Snapshot

```json
{
  "balances": {
    "BTC": {
      "available": "0.009750",
      "frozen": "0.000100",
      "total": "0.009850"
    },
    "USDT": {
      "available": "1003.42279800",
      "frozen": "6.76281750",
      "total": "1010.18561550"
    }
  },
  "health_ok": true,
  "market_data": {
    "depth_levels": {
      "BTC_USDT": {
        "asks": 0,
        "bids": 0
      },
      "SYNBO_USDT": {
        "asks": 0,
        "bids": 0
      }
    },
    "gap_count": 0,
    "orderbook_versions": {
      "BTC_USDT": null,
      "SYNBO_USDT": null
    },
    "stale_symbols": [],
    "symbols": [
      "BTC_USDT",
      "SYNBO_USDT"
    ]
  },
  "metrics": {
    "balance_available{'currency': 'BTC'}": "0.009750",
    "balance_available{'currency': 'USDT'}": "1003.42279800",
    "balance_frozen{'currency': 'BTC'}": "0.000100",
    "balance_frozen{'currency': 'USDT'}": "6.76281750",
    "cancel_request_count": "14",
    "daily_pnl": "0E-33",
    "fill_count{'side': 'sell', 'symbol': 'BTC_USDT'}": "6",
    "market_data_lag_ms{'exchange': 'paper', 'symbol': 'BTC_USDT'}": "0",
    "market_data_lag_ms{'exchange': 'paper', 'symbol': 'SYNBO_USDT'}": "0",
    "place_request_count": "20"
  },
  "open_orders": 0,
  "pnl": {
    "BTC_USDT": {
      "avg_cost": "0",
      "fees": "0E-8",
      "position": "0",
      "realized_pnl": "0.00",
      "total_pnl": "0E-33",
      "unrealized_pnl": "0E-33"
    }
  },
  "symbols": [
    "BTC_USDT",
    "SYNBO_USDT"
  ],
  "total_orders": 1720,
  "trading_mode": "paper"
}
```

## Preflight

```json
{
  "checks": [
    {
      "message": "BitMart credentials missing",
      "name": "credentials_present",
      "passed": true
    },
    {
      "message": "live_confirm is false",
      "name": "live_confirm",
      "passed": true
    },
    {
      "message": "paper mode does not submit live orders",
      "name": "order_submission_guard",
      "passed": true
    },
    {
      "message": "all configured symbols have market rules",
      "name": "symbols_have_rules",
      "passed": true
    },
    {
      "message": "paper mode does not use live API key",
      "name": "api_key_no_withdraw_permission_ack",
      "passed": true
    },
    {
      "message": "paper mode does not use live API key",
      "name": "api_key_ip_whitelist_ack",
      "passed": true
    },
    {
      "message": "paper mode runbook not required",
      "name": "production_runbook_ack",
      "passed": true
    }
  ],
  "mode": "paper",
  "passed": true
}
```

## Risk Drills

```json
[
  {
    "message": "system is in SAFE_MODE",
    "name": "safe_mode_blocks_new_orders",
    "passed": true
  },
  {
    "message": "buy price would cross ask",
    "name": "post_only_cross_rejected",
    "passed": true
  },
  {
    "message": "market data is stale",
    "name": "stale_market_rejected",
    "passed": true
  },
  {
    "message": "OMS has UNKNOWN orders; reconciliation required",
    "name": "unknown_order_rejected",
    "passed": true
  }
]
```

## WebSocket Smoke

```json
[
  {
    "channels": [
      "spot/depth/increase100:BTC_USDT"
    ],
    "dry_run": true,
    "errors": [],
    "first_message": null,
    "login_payload": null,
    "passed": true,
    "received_count": 0,
    "subscription": {
      "args": [
        "spot/depth/increase100:BTC_USDT"
      ],
      "op": "subscribe"
    },
    "target": "public"
  },
  {
    "channels": [
      "spot/user/orders:ALL_SYMBOLS",
      "spot/user/balance:BALANCE_UPDATE"
    ],
    "dry_run": true,
    "errors": [],
    "first_message": null,
    "login_payload": {
      "args": [
        "dryrun_key",
        "1779732659216",
        "1f1f61230be59d113317dd2145d267d6f45b343e8dc75e2c5fbdf89c462cd1da"
      ],
      "op": "login"
    },
    "passed": true,
    "received_count": 0,
    "subscription": {
      "args": [
        "spot/user/orders:ALL_SYMBOLS",
        "spot/user/balance:BALANCE_UPDATE"
      ],
      "op": "subscribe"
    },
    "target": "private"
  }
]
```

## Backtest Replay

```json
{
  "event_log_path": "runtime/events.jsonl",
  "generated_order_intents": 4960,
  "generated_quotes": 4960,
  "market_snapshots": 1240,
  "symbols": [
    "BTC_USDT",
    "SYNBO_USDT"
  ]
}
```

## PnL Report

```json
{
  "event_log_path": "runtime/events.jsonl",
  "fills": 404,
  "symbols": {
    "BTC_USDT": {
      "avg_cost": "0",
      "fees": "0E-8",
      "position": "0",
      "realized_pnl": "0.00",
      "total_pnl": "0E-33",
      "unrealized_pnl": "0E-33"
    }
  },
  "total_fees": "0"
}
```

## Rate Limits

```json
{
  "cancel_all_1_per_3s": {
    "max_calls": 1,
    "remaining": 1,
    "reset_after_seconds": 0.0,
    "used": 0,
    "window_seconds": 3.0
  },
  "default_40_per_2s": {
    "max_calls": 40,
    "remaining": 40,
    "reset_after_seconds": 0.0,
    "used": 0,
    "window_seconds": 2.0
  },
  "open_orders_12_per_2s": {
    "max_calls": 12,
    "remaining": 12,
    "reset_after_seconds": 0.0,
    "used": 0,
    "window_seconds": 2.0
  },
  "query_order_50_per_2s": {
    "max_calls": 50,
    "remaining": 50,
    "reset_after_seconds": 0.0,
    "used": 0,
    "window_seconds": 2.0
  }
}
```
