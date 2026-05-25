# XLong Market Maker

BitMart-first 做市商交易系统。当前工程优先实现安全交易闭环：

- `paper` 模式默认启用，不会真实下单。
- 所有订单必须经过策略、报价引擎、风控、OMS。
- BitMart REST 签名和接口适配已预留。
- OMS 支持订单状态机、幂等 client order id、事件日志和重启恢复基础。
- 风控默认保守，live 模式需要显式确认。

## 快速运行

```bash
python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m mm.main --config config/paper.json --ticks 5
```

省略 `--ticks` 时按生产常驻服务运行，收到 `SIGINT/SIGTERM` 后会走 shutdown cancel 流程。

一键验收：

```bash
scripts/acceptance.sh 10
```

验收报告会写入：

```text
docs/acceptance_report.md
```

事件回放摘要：

```bash
PYTHONPATH=src python3 scripts/replay_summary.py runtime/events.jsonl
```

BitMart preflight：

```bash
PYTHONPATH=src python3 scripts/preflight.py --config config/paper.json
```

BitMart WebSocket smoke dry-run：

```bash
PYTHONPATH=src python3 scripts/ws_smoke.py --symbol BTC_USDT
PYTHONPATH=src python3 scripts/ws_smoke.py --private
```

回测和报表：

```bash
PYTHONPATH=src python3 scripts/backtest.py --config config/paper.json --events runtime/events.jsonl
PYTHONPATH=src python3 scripts/pnl_report.py --events runtime/events.jsonl
PYTHONPATH=src python3 scripts/live_read_only_check.py --config config/paper.json
```

配置审计和限速预算：

```bash
PYTHONPATH=src python3 scripts/config_audit.py --config config/paper.json
PYTHONPATH=src python3 scripts/rate_limit_report.py
PYTHONPATH=src python3 scripts/runtime_snapshot.py --config config/paper.json --ticks 2
```

Docker paper daemon run：

```bash
docker compose up --build market-maker-paper
```

Admin 控制台：

```bash
ADMIN_TOKEN='change-me' PYTHONPATH=src python3 scripts/admin_server.py
```

如果未设置 `ADMIN_TOKEN`，本地开发 token 会生成到 `runtime/admin_token.json`。生产环境必须显式设置 `ADMIN_TOKEN`，可选设置 `ADMIN_OPERATOR_TOKEN` 和 `ADMIN_VIEWER_TOKEN` 做 RBAC 分权。所有敏感操作需要输入确认短语，并写入带 HMAC 链式签名的 `runtime/admin_audit.jsonl`。

## 目录

```text
src/mm/
  app.py                 系统主循环
  main.py                CLI
  common/                领域类型、时间、ID、decimal 工具
  config/                配置加载和校验
  exchange/              交易所抽象、paper、BitMart REST
  market_data/           fair price 和行情结构
  strategy/              策略插件系统
  quote/                 报价差分和订单意图生成
  oms/                   订单管理系统
  risk/                  风控系统
  inventory/             库存管理
  persistence/           JSONL 事件日志
```

## 安全说明

默认配置为 `paper`。真实下单必须同时满足：

- `trading_mode` 为 `live`
- `live_confirm` 为 `true`
- 环境变量提供 BitMart API Key / Secret / Memo
- 风控限额显式配置
- 交易对在 allowlist 中

大资金上线前必须通过 `docs/production_execution_roadmap.md` 中的全部灰度和演练门槛。
