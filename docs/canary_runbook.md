# 小额 Canary 上线流程

## 目标

Canary 只验证真实 BitMart 账号、真实行情、真实订单生命周期是否闭环，不追求收益。默认顺序是 `live_read_only` -> `live_dry_run` -> 小额 `live`。

## 0. 硬性门禁

- API Key 必须无提现权限。
- API Key 必须配置 IP 白名单。
- `live_confirm=true` 必须人工确认。
- `runtime` 订单库不得存在 `UNKNOWN`。
- Canary 前先跑 read-only 和 shadow，任何失败都不能进入 live。

## 1. Live Read-only

只读连接真实账户，验证 REST、公共 WS、私有 WS、余额流、订单流解析，不发送订单。

```bash
export BITMART_API_KEY=...
export BITMART_API_SECRET=...
export BITMART_API_MEMO=...
PYTHONPATH=src python3 scripts/live_read_only_check.py --config config/live_read_only.example.json --network
```

验收标准：

- `passed=true`。
- `order_submission_enabled=false`。
- `private_stream_closed_loop.passed=true`。
- 远端订单对账无 `critical` 差异。

## 2. Live Dry-run Shadow

使用真实行情和真实账户只读数据，策略照常计算订单，但下单/撤单只写本地影子账，不发送 BitMart。

```bash
PYTHONPATH=src python3 scripts/canary_checklist.py --config config/live_dry_run.example.json --stage shadow --max-order-usdt 10
PYTHONPATH=src python3 -m mm.main --config config/live_dry_run.example.json --ticks 50
```

验收标准：

- 本地订单库有策略订单。
- BitMart 远端订单没有新增。
- Admin 订单中心的对账差异没有 `local_open_missing_remote` 以外的真实远端异常。
- 策略级指标、PnL、open notional 可在策略详情页查看。

## 3. 小额 Live Canary

把配置切换到 `live`，只启用一个策略、一个交易对、极小订单额度。

建议初始限额：

- `max_order_value_usdt <= 10`。
- `max_total_open_value_usdt <= 50`。
- `max_open_orders <= 4`。
- `quote_interval_ms >= 1000`。
- `cancel_on_shutdown=true`。

```bash
PYTHONPATH=src python3 scripts/canary_checklist.py --config config/live.example.json --stage canary --max-order-usdt 10
PYTHONPATH=src python3 scripts/preflight.py --config config/live.example.json --network
PYTHONPATH=src python3 -m mm.main --config config/live.example.json --ticks 20
```

验收标准：

- BitMart 远端订单能被 Admin 远端订单页读到。
- 本地订单与远端订单对账无 `critical`。
- 停止并撤单后，策略状态为 paused，远端挂单清空。
- 任一订单进入 `UNKNOWN` 时，风控页显示 blocked，系统拒绝新单。

## 回滚

1. Admin 点击“停止并撤单”。
2. 风控后台点击“暂停新单”。
3. 运行只读对账确认远端挂单为 0。
4. 保留 `runtime/events*.jsonl`、订单库和 Admin 截图，用于复盘。
