# 当前实现状态

日期：2026-05-26  
工程状态：生产级架构骨架 + paper 交易闭环 + BitMart read-only/shadow 生产硬化  

## 已完成

- Python 项目骨架。
- `paper` 默认安全运行模式。
- JSON 配置系统。
- 配置 SHA-256 指纹审计。
- 配置热加载检测基础。
- 参数变更 diff 审计。
- live 模式安全校验。
- 核心领域类型：订单、成交、余额、行情、报价意图、订单意图。
- Decimal 精度处理。
- client order id 和 trace id 生成。
- JSONL 事件日志。
- JSON 订单状态持久化。
- SQLite 订单库，`order_store_path` 使用 `.db/.sqlite/.sqlite3` 自动启用。
- SQLite/Postgres 订单状态支持单订单增量 upsert，避免高频状态变化时全量重写订单库。
- Postgres 订单库适配器，生产环境安装 `psycopg` 或 `psycopg2` 后可用。
- OMS：
  - 订单状态机。
  - 下单前本地记录。
  - 下单 ack 处理。
  - 撤单 ack 处理。
  - 成交处理。
  - open orders 查询。
  - UNKNOWN 状态保护。
  - 批量下单。
  - 批量撤单。
  - 重启恢复本地订单。
  - open orders 对账服务。
  - 按交易对 scoped 对账，不会因为单交易对 REST 对账误伤其他交易对本地挂单。
  - live dry-run shadow 本地挂单不会被远端 open orders 空列表误判为 UNKNOWN。
  - 私有流订单回报可进入 OMS。
  - 远端 orphan order 自动进入 UNKNOWN。
- Risk Engine：
  - stale market data。
  - post-only crossing。
  - 最大单笔金额。
  - 最大总挂单金额。
  - 最大挂单数量。
  - 最大库存。
  - 日内亏损阈值。
  - SAFE_MODE。
  - 策略级最大订单金额。
  - 策略级最大挂单数量。
  - 策略级最大挂单金额。
- Quote Governance：
  - 策略级订单预算分配器。
- Strategy Engine：
  - 插件注册。
  - `basic_mm` 双边多层报价。
  - `inventory_skew` 库存偏移。
- Quote Engine：
  - tick/step 对齐。
  - post-only 价格保护。
  - 报价差分。
  - 最小重挂间隔。
- Paper Exchange：
  - 模拟行情。
  - 冻结余额。
  - 撤单释放余额。
  - maker 成交模拟。
  - 余额更新。
- Accounting：
- PnL tracker。
- 已实现/未实现 PnL。
- 手续费统计。
- Monitoring：
  - Metrics registry。
  - Prometheus text exporter。
  - Health checker。
  - 风险演练套件。
  - Runtime snapshot。
- Hedging：
  - 对冲意图生成。
  - 模拟对冲执行。
  - Hedge adapter 抽象。
  - Binance dry-run hedge adapter。
- BitMart 基础：
  - REST 签名。
  - REST HTTP 封装。
  - REST 请求在线程池中执行，避免同步 `urllib` 阻塞 asyncio 主交易循环。
  - 下单/撤单/open orders/balance/单笔查单接口骨架。
  - 公共 REST 盘口快照用于 live dry-run shadow 行情。
  - 批量下单/批量撤单接口骨架。
  - 官方限速预算器。
  - 限速预算快照和报告。
  - WebSocket channel builder。
  - 私有订单/余额事件解析。
  - 私有订单/余额事件处理器闭环。
- Market Data：
  - BitMart depth increase100 消息解析。
  - 本地 order book snapshot/update。
  - version gap 检测。
  - MarketDataHub。
  - 外部行情源快照接入。
  - 加权 fair price。
- WebSocket：
  - 可选 `websockets` 依赖的真实 client。
  - public/private client factory。
  - 非 paper 模式可默认启动 BitMart private WS 并将订单/余额回报持续喂给 OMS/Inventory。
  - public/private smoke dry-run。
- Live Controls：
  - `live_read_only`。
  - `live_dry_run`。
  - `live`。
  - `enable_order_submission` 硬开关。
  - DryRunExchange。
  - `live_read_only` / `live_dry_run` 下订单请求只进入本地影子账，不发送交易所。
  - Admin 写入的策略暂停/恢复和 SAFE_MODE 会被主循环读取。
  - 启动对账发现 UNKNOWN 订单时进入 SAFE_MODE；私有流产生 UNKNOWN 订单状态时进入 SAFE_MODE。
  - BitMart preflight。
  - API Key 无提现权限/IP 白名单/运行手册确认项。
- Admin Console：
  - 交易所账号、交易对、策略、订单、库存、风控、审计页面。
  - Token 认证，支持 `ADMIN_TOKEN` / `ADMIN_OPERATOR_TOKEN` / `ADMIN_VIEWER_TOKEN` 三类角色。
  - RBAC 权限：viewer 只读，operator 可运行控制，admin 可配置、删除和执行高危操作。
  - 敏感操作后端强制二次确认短语：启动策略、停止并撤单、删除策略、删除交易对、暂停/恢复新单。
  - Admin 操作审计写入 `runtime/admin_audit.jsonl`，使用 HMAC 链式签名防篡改。
  - 策略详情页。
  - 策略级 PnL cashflow、open notional、风险限额、运行指标。
  - 停止并撤单计划。
  - 本地/远端订单、对账差异、UNKNOWN 熔断提示。
- Runtime：
  - 默认常驻运行，`--ticks` 可用于验收/调试短跑。
  - `SIGINT/SIGTERM` 优雅停止并执行 shutdown cancel。
  - 多交易对 batch 下单/撤单按 symbol 分组。
- External Feeds：
  - Binance bookTicker adapter。
- Replay：
  - JSONL 事件日志回放。
  - 事件类型统计。
  - 事件日志策略回测 runner。
- Reporting：
  - PnL 日终报表。
  - live read-only 只读验收脚本。
  - 小额 canary 检查脚本和上线 runbook。
- Docker：
  - Dockerfile。
  - docker-compose paper 服务。
- Versioning / CI：
  - 当前目录已初始化为 git 仓库。
  - origin 指向 `git@github.com:SynboTech/xlong.git`。
  - GitHub Actions CI 运行单元测试和 paper smoke run。
- Fair Price：
  - 多交易所加权 fair price。
  - stale source 剔除。
- 脚本：
  - `scripts/run_paper.sh`
  - `scripts/acceptance.sh`
- 测试：
  - 配置。
  - BitMart 签名。
  - OMS。
  - 策略。
  - 报价。
  - 风控。
  - 限速。
  - WebSocket 解析。
  - PnL。
  - fair price。
  - paper app 主循环。

## 当前验收命令

```bash
scripts/acceptance.sh 10
```

或：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m mm.main --config config/paper.json --ticks 10
```

## 最近一次验收结果

- 单元测试：82 个通过。
- paper 主循环：可启动、可报价、可发单、可撤单。
- 验收报告：`docs/acceptance_report.md`
- 风险演练覆盖 SAFE_MODE、post-only crossing、stale market、UNKNOWN order。
- 验收报告包含 Backtest Replay 和 PnL Report。
- 验收报告包含 Config Audit 和 Rate Limits。
- 验收报告包含 Runtime Snapshot。
- P1 回归覆盖：REST 非阻塞、private stream 喂 OMS/Inventory、SQLite 增量保存、dry-run shadow 对账、按交易对对账隔离。
- P2 回归覆盖：Admin token 认证、RBAC 拒绝、敏感操作确认、签名审计链校验。
- 10 tick 运行曾产生模拟 maker 成交。
- 退出后 open orders 为 0。

## 仍需完成后才能大资金上线

以下项目不是可选项：

- BitMart 公共 WebSocket 真实长连接压测和 order book 重建长稳验证。
- BitMart 私有 WebSocket 登录、订单回报、余额回报真实账号长稳验证。
- BitMart REST 真实小额查询、下单、撤单联调。
- Admin 控制面到运行中进程的文件轮询已完成，仍建议升级为持久控制总线或 RPC ack。
- REST 超时后的查单确认流程实盘验证。
- WebSocket 断线恢复和订阅恢复实盘验证。
- PostgreSQL 驱动安装、迁移脚本和备份恢复演练。
- Redis/队列化事件总线。
- Prometheus/Grafana 监控。
- 外部交易所行情源。
- 外部交易所对冲通道。
- 压测。
- 故障演练。
- 小资金灰度。
- 中资金灰度。
- 主备切换。
- 运维值班和人工全撤演练。

## 安全状态

当前默认配置不会真实下单。  
`config/live.example.json` 中 `live_confirm` 默认为 `false`。  
live 模式缺少 API Key 或未显式确认会启动失败。  

这符合大资金系统的基本原则：默认安全，显式授权，逐级灰度。
