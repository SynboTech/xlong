# 2026-05-26 上午验收清单

## 一键验收

```bash
scripts/acceptance.sh 10
```

验收报告：

```text
docs/acceptance_report.md
```

## 必须看到的结果

- 单元测试全部通过。
- Config Audit 有 SHA-256 指纹。
- Runtime Snapshot 可生成。
- paper 主循环可启动。
- 策略生成双边报价。
- OMS 接收订单并管理状态。
- 风控不进入 SAFE_MODE。
- paper 运行结束后 `open_orders` 为 0。
- 风险演练通过：
  - SAFE_MODE 阻止新单。
  - post-only crossing 被拒绝。
  - stale market data 被拒绝。
  - UNKNOWN order 阻止新单。
- 健康检查通过。
- Preflight 通过。
- WebSocket smoke dry-run 通过。
- Backtest replay 有市场快照和策略输出。
- PnL report 可生成。
- Rate limit report 可生成。
- 策略级风险限额已启用。

## 当前可验收范围

- 生产级代码骨架。
- paper 交易闭环。
- OMS 持久化与对账。
- BitMart REST/WS 接入基础。
- 策略插件。
- 风控。
- PnL。
- 监控指标。
- 健康检查。
- 对冲接口。
- Binance dry-run 对冲 adapter。
- 事件回放。
- Docker 运行入口。
- live_read_only / live_dry_run / live 安全模式。
- Dry-run 交易所包装器。
- BitMart preflight 脚本。
- live read-only 只读验收脚本。
- Binance 外部行情 adapter。

## 附加验收命令

```bash
PYTHONPATH=src python3 scripts/backtest.py --config config/paper.json --events runtime/events.jsonl
PYTHONPATH=src python3 scripts/pnl_report.py --events runtime/events.jsonl
PYTHONPATH=src python3 scripts/live_read_only_check.py --config config/paper.json
PYTHONPATH=src python3 scripts/config_audit.py --config config/paper.json
PYTHONPATH=src python3 scripts/rate_limit_report.py
PYTHONPATH=src python3 scripts/runtime_snapshot.py --config config/paper.json --ticks 2
```

## 不允许直接大资金上线的剩余条件

- 尚未用真实 BitMart API Key 完成小额下单/撤单联调。
- 尚未接入真实 BitMart 公共 WebSocket 长时间运行。
- 尚未接入真实 BitMart 私有订单流长时间运行。
- 尚未完成外部对冲交易所真实接入。
- 尚未完成 7 天 paper 连续稳定运行。
- 尚未完成小资金 live 灰度。
- 尚未完成中资金 live 灰度。
- 尚未完成主备切换和故障演练。

大资金上线前必须继续执行 `docs/production_execution_roadmap.md`。
