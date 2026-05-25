# BitMart 做市商交易系统生产级开发文档

版本：v0.1  
日期：2026-05-25  
目标验收时间：2026-05-26 上午  
首要交易所：BitMart 现货  
系统定位：生产架构级、可运行、可模拟交易/小资金灰度、具备核心风控和可扩展策略插件的做市系统 MVP

## 1. 现实交付边界

明早可验收的目标不是“已经经过数周实盘压力测试、可承载大资金高频交易的最终系统”，而是：

- 可运行的做市交易系统主程序。
- BitMart API 网关骨架与真实接口对接设计。
- WebSocket 行情接入架构。
- 订单管理系统 OMS。
- 策略插件系统。
- 基础双边报价策略。
- 库存偏移策略。
- 风控系统。
- 模拟交易模式。
- 可切换真实下单模式，但默认关闭。
- 日志、事件记录、监控指标。
- 一键停机和全撤机制。
- 明确的生产上线前检查清单。

不应在未经充分测试、无专线/服务器调优、无交易所 API 限速确认、无小资金灰度的情况下直接大资金实盘。

## 2. 系统总体目标

系统需要支持：

- 高频行情接入。
- 多策略插件式调用。
- 多交易对扩展。
- BitMart 首发接入。
- 后续扩展 Binance、OKX、Bybit 等外部参考行情和对冲交易所。
- 稳定的订单生命周期管理。
- 实时风控。
- 库存管理。
- 断线恢复。
- 异常全撤。
- 策略回测和模拟交易。
- 生产环境配置隔离。

核心原则：

- 策略不能直接访问交易所。
- 所有订单必须经过 Quote Engine、Risk Engine、OMS。
- 风控不可被策略绕过。
- 真实下单必须显式启用。
- 所有关键事件必须可追溯。
- 任何网络异常、行情断流、订单状态不明，都优先保护资金。

## 3. 推荐技术栈

### 3.1 MVP 技术栈

- 语言：Python 3.11+
- 异步框架：asyncio
- WebSocket：websockets / aiohttp
- HTTP Client：httpx
- 数据校验：pydantic
- 配置：pydantic-settings / YAML
- 日志：structlog / logging JSON format
- 数据库：PostgreSQL
- 缓存：Redis
- 时间序列/分析：ClickHouse 可后置
- 测试：pytest / pytest-asyncio
- 容器：Docker / Docker Compose

### 3.2 后续生产增强

- 高频撮合/订单核心可迁移到 Go / Rust。
- 事件总线可使用 NATS / Redpanda / Kafka。
- 延迟敏感模块独立部署。
- 多机热备。
- Prometheus + Grafana 监控。
- Loki / ELK 日志检索。

## 4. 总体架构

```text
                 ┌─────────────────────────────┐
                 │ Admin API / CLI / Dashboard  │
                 └──────────────┬──────────────┘
                                │
                                ▼
┌───────────────┐      ┌─────────────────┐      ┌──────────────────┐
│ External Feeds │────▶│ Market Data Hub │────▶│ Strategy Engine   │
│ Binance/OKX等  │      │ OrderBook/Trade │      │ Plugin Strategies │
└───────────────┘      └────────┬────────┘      └────────┬─────────┘
                                │                        │
                                ▼                        ▼
                         ┌─────────────┐          ┌──────────────┐
                         │ Risk Engine │◀────────▶│ Quote Engine │
                         └──────┬──────┘          └──────┬───────┘
                                │                        │
                                ▼                        ▼
                         ┌─────────────────────────────────────┐
                         │ OMS Order Management System          │
                         │ State Machine / Reconcile / Recovery │
                         └─────────────────┬───────────────────┘
                                           │
                                           ▼
                         ┌─────────────────────────────────────┐
                         │ Exchange Gateway                     │
                         │ BitMart REST / WS / Sign / RateLimit │
                         └─────────────────┬───────────────────┘
                                           │
                                           ▼
                                      BitMart API
```

## 5. 模块设计

### 5.1 Exchange Gateway

交易所网关负责把不同交易所 API 抽象成统一接口。

BitMart Gateway 必须实现：

- 加载 API Key、Secret、Memo。
- REST 签名。
- 获取交易对规则。
- 获取账户余额。
- 获取当前未成交订单。
- 提交限价订单。
- 提交 post-only / maker-only 订单。
- 批量下单。
- 撤单。
- 批量撤单。
- 查询订单。
- 查询成交明细。
- 订阅公共 WebSocket 行情。
- 订阅私有 WebSocket 订单和成交回报。
- 订阅私有余额变化。
- 心跳和自动重连。
- 请求限速。
- 错误码标准化。

统一接口示例：

```python
class ExchangeGateway:
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def load_markets(self) -> dict[str, MarketRule]: ...
    async def get_balances(self) -> list[Balance]: ...
    async def get_open_orders(self, symbol: str) -> list[Order]: ...
    async def submit_order(self, request: OrderRequest) -> OrderAck: ...
    async def cancel_order(self, request: CancelRequest) -> CancelAck: ...
    async def cancel_all(self, symbol: str | None = None) -> list[CancelAck]: ...
    async def stream_market_data(self, symbols: list[str]) -> AsyncIterator[MarketEvent]: ...
    async def stream_private_events(self) -> AsyncIterator[PrivateEvent]: ...
```

### 5.2 Market Data Hub

行情中心负责接收、校验、归一化和分发行情。

功能：

- BitMart ticker。
- BitMart order book。
- BitMart trades。
- 外部交易所价格源。
- 本地 order book 重建。
- 快照和增量校验。
- 行情延迟测量。
- 异常行情过滤。
- fair price 计算。

输出数据：

```python
class MarketSnapshot:
    symbol: str
    exchange: str
    bid: Decimal
    bid_size: Decimal
    ask: Decimal
    ask_size: Decimal
    mid: Decimal
    last: Decimal | None
    timestamp_ms: int
    receive_time_ms: int
```

### 5.3 Strategy Engine

策略引擎加载多个策略插件。策略只输出报价意图，不直接下单。

策略插件接口：

```python
class StrategyPlugin:
    name: str

    async def on_start(self, ctx: StrategyContext) -> None: ...
    async def on_market(self, event: MarketEvent) -> None: ...
    async def on_order(self, event: OrderEvent) -> None: ...
    async def on_fill(self, event: FillEvent) -> None: ...
    async def on_balance(self, event: BalanceEvent) -> None: ...
    async def on_timer(self, now_ms: int) -> list[QuoteIntent]: ...
    async def on_stop(self) -> None: ...
```

策略上下文：

- 当前盘口。
- 外部指数价。
- 当前库存。
- 未成交订单。
- 风控状态。
- 手续费配置。
- 策略参数。

### 5.4 Quote Engine

报价引擎把策略意图转成订单意图。

职责：

- 价格精度对齐。
- 数量精度对齐。
- 最小订单量校验。
- 最小成交额校验。
- post-only 检查。
- 避免穿价。
- 报价去抖。
- 新旧报价差分。
- 批量下单和批量撤单计划。

QuoteIntent：

```python
class QuoteIntent:
    symbol: str
    side: Literal["buy", "sell"]
    price: Decimal
    size: Decimal
    level: int
    strategy: str
    reason: str
```

OrderIntent：

```python
class OrderIntent:
    action: Literal["place", "cancel", "replace"]
    symbol: str
    side: Literal["buy", "sell"] | None
    price: Decimal | None
    size: Decimal | None
    client_order_id: str | None
    old_client_order_id: str | None
    strategy: str
```

### 5.5 OMS 订单管理系统

OMS 是资金安全的核心模块。

订单状态：

```text
CREATED
SUBMITTING
ACKED
OPEN
PARTIALLY_FILLED
FILLED
CANCELING
CANCELED
REJECTED
EXPIRED
UNKNOWN
```

OMS 职责：

- 生成 clientOrderId。
- 记录订单请求。
- 处理交易所 ack。
- 维护本地 open orders。
- 处理成交回报。
- 处理撤单回报。
- REST 对账。
- WebSocket 断线恢复。
- 避免重复下单。
- 避免重复撤单。
- 识别 unknown 状态订单。
- 系统重启后恢复订单状态。

对账规则：

- WebSocket 回报优先。
- REST 查询定时校正。
- 重启后必须查询 open orders。
- 本地有、交易所无的订单进入终态或异常检查。
- 交易所有、本地无的订单标记为 orphan order，并进入风控处理。

### 5.6 Risk Engine

风控分为前置风控、运行中风控、后置风控。

前置风控：

- 交易对是否允许交易。
- 系统是否处于 LIVE 模式。
- API Key 是否允许真实下单。
- 订单价格是否偏离 fair price。
- 订单数量是否超过单笔限制。
- 订单金额是否超过单笔限制。
- 买卖方向是否导致库存超限。
- 当前挂单总额是否超限。
- 当前订单数量是否超限。
- 当前撤单频率是否超限。
- 行情是否新鲜。
- 外部参考价是否可用。

运行中风控：

- 行情断流。
- 私有 WebSocket 断线。
- REST 错误率过高。
- 延迟过高。
- 成交频率异常。
- 单边成交过多。
- 库存偏离过大。
- PnL 跌破阈值。
- 订单状态 UNKNOWN 过多。

后置风控：

- 成交后库存检查。
- 成交后 PnL 更新。
- 对冲检查。
- 异常成交告警。

熔断动作：

- 仅暂停新单。
- 撤销当前交易对全部订单。
- 撤销全账户全部订单。
- 禁用某策略。
- 系统进入 SAFE_MODE。
- 系统进程退出。

### 5.7 Inventory Manager

库存模块负责实时资产和目标库存管理。

功能：

- 读取账户余额。
- 计算可用余额。
- 计算冻结余额。
- 按交易对计算 base/quote 暴露。
- 计算目标库存偏离。
- 输出库存惩罚因子。
- 提供给策略调整报价。

库存偏移示例：

```text
inventory_skew = current_base_value / target_base_value - 1
quote_center = fair_price * (1 - skew_coefficient * inventory_skew)
```

### 5.8 Hedging Engine

MVP 可先只设计接口，真实对冲作为第二阶段。

功能：

- 监听 BitMart 成交。
- 判断是否需要外部对冲。
- 选择对冲交易所。
- 计算对冲数量。
- 以限价或市价对冲。
- 对冲失败重试。
- 记录对冲成本。
- 对冲结果反馈给 PnL。

### 5.9 Persistence

必须记录：

- market_events
- strategy_signals
- quote_intents
- order_intents
- orders
- fills
- balances
- risk_events
- system_events
- pnl_snapshots

核心表：

```text
orders
- id
- exchange
- symbol
- side
- type
- price
- size
- filled_size
- status
- client_order_id
- exchange_order_id
- strategy
- created_at
- updated_at

fills
- id
- order_id
- exchange
- symbol
- side
- price
- size
- fee
- fee_currency
- liquidity
- trade_id
- strategy
- created_at

risk_events
- id
- level
- symbol
- source
- rule
- action
- detail
- created_at
```

### 5.10 Config Center

配置必须支持环境隔离：

```text
config/
  default.yaml
  paper.yaml
  live.yaml
  symbols/BTC_USDT.yaml
  strategies/basic_mm.yaml
```

关键配置：

- trading_mode: paper/live
- exchange: bitmart
- symbols
- max_position
- max_order_value
- max_open_order_count
- max_daily_loss
- max_price_deviation_bps
- quote_interval_ms
- min_requote_interval_ms
- stale_market_data_ms
- cancel_on_disconnect
- kill_switch_enabled

API Key 不进入 Git 仓库，使用环境变量或密钥管理。

## 6. 做市策略清单

### 6.1 基础双边报价策略

目的：围绕 fair price 挂买卖双边订单。

参数：

- spread_bps
- order_size
- quote_interval_ms
- max_levels

输出：

```text
bid = fair_price * (1 - spread_bps / 20000)
ask = fair_price * (1 + spread_bps / 20000)
```

### 6.2 多层盘口策略

目的：提供盘口深度。

参数：

- levels
- level_spread_bps
- level_size_multiplier

示例：

```text
bid1: fair - 10 bps, size 1x
bid2: fair - 20 bps, size 1.5x
bid3: fair - 35 bps, size 2x
```

### 6.3 库存偏移策略

目的：降低单边库存风险。

规则：

- base 库存过多：报价中心下移，卖侧更激进，买侧更保守。
- base 库存过少：报价中心上移，买侧更激进，卖侧更保守。

### 6.4 波动率自适应策略

目的：市场波动大时自动扩大价差。

输入：

- 最近 N 秒 mid price。
- 外部指数价变动。
- 成交流强度。

输出：

```text
dynamic_spread = base_spread + volatility_factor * realized_volatility
```

### 6.5 盘口不平衡策略

目的：根据 order book imbalance 调整报价中心。

```text
imbalance = bid_depth / (bid_depth + ask_depth)
```

若买盘明显强于卖盘，报价中心上移；反之下移。

### 6.6 外部指数价策略

目的：避免 BitMart 本地盘口被操纵。

fair price 来源：

- BitMart mid price。
- Binance mid price。
- OKX mid price。
- Coinbase mid price。

加权方式：

```text
fair = 0.2 * bitmart_mid + 0.5 * binance_mid + 0.3 * okx_mid
```

### 6.7 防御撤退策略

触发条件：

- 行情超过 stale_market_data_ms 未更新。
- 外部指数价缺失。
- BitMart mid price 偏离外部指数价超过阈值。
- 订单回报延迟过高。
- 成交速度异常。
- 库存超限。

动作：

- 停止新单。
- 撤销本策略订单。
- 撤销全部订单。
- 系统进入 SAFE_MODE。

## 7. 开发目录结构

```text
market-maker/
  README.md
  pyproject.toml
  docker-compose.yml
  .env.example
  config/
    default.yaml
    paper.yaml
    live.yaml
    symbols/
      BTC_USDT.yaml
    strategies/
      basic_mm.yaml
  src/
    mm/
      main.py
      app.py
      config/
      common/
        types.py
        decimal.py
        time.py
        ids.py
      exchange/
        base.py
        bitmart/
          gateway.py
          rest.py
          websocket.py
          signer.py
          models.py
          errors.py
          rate_limit.py
      market_data/
        hub.py
        orderbook.py
        fair_price.py
      strategy/
        base.py
        engine.py
        plugins/
          basic_mm.py
          inventory_skew.py
      quote/
        engine.py
        diff.py
      oms/
        manager.py
        state.py
        reconcile.py
      risk/
        engine.py
        rules.py
        kill_switch.py
      inventory/
        manager.py
      hedging/
        engine.py
      persistence/
        db.py
        repository.py
        migrations/
      monitoring/
        metrics.py
        health.py
      cli/
        commands.py
  tests/
    unit/
    integration/
    fixtures/
```

## 8. 开发步骤

### 阶段 0：初始化项目

目标：建立可运行工程。

任务：

- 创建 Python 项目。
- 配置 pyproject。
- 配置 lint/test。
- 创建配置目录。
- 创建 .env.example。
- 创建 Docker Compose。
- 创建基础 README。

验收：

- 能运行 `python -m mm.main --mode paper`。
- 能运行单元测试。

### 阶段 1：公共类型和配置系统

任务：

- 定义 Symbol、Order、Fill、Balance、MarketSnapshot。
- 定义 Decimal 精度工具。
- 定义 clientOrderId 生成器。
- 加载 YAML 配置。
- 校验 live 模式必须显式确认。

验收：

- 配置加载测试通过。
- 金额和价格精度测试通过。

### 阶段 2：BitMart Gateway

任务：

- 实现 BitMart REST signer。
- 实现交易对规则加载。
- 实现余额查询。
- 实现下单接口。
- 实现撤单接口。
- 实现 open orders 查询。
- 实现基础错误码映射。
- 实现限速器。

验收：

- 在 mock 模式下通过所有 REST 测试。
- 在无 API Key 时系统只能进入 paper 模式。
- live 模式不允许空风控配置。

### 阶段 3：WebSocket 行情

任务：

- 实现公共行情连接。
- 订阅 ticker/order book/trades。
- 心跳。
- 自动重连。
- 行情时间戳和接收时间戳。
- 行情断流事件。

验收：

- 能持续接收目标交易对行情。
- 断线后能重连。
- stale data 能触发 risk event。

### 阶段 4：OMS

任务：

- 实现订单状态机。
- 实现下单请求记录。
- 实现 ack 处理。
- 实现撤单处理。
- 实现成交处理。
- 实现本地 open orders。
- 实现启动对账。
- 实现 orphan order 检测。

验收：

- mock exchange 测试覆盖完整订单生命周期。
- 重复 ack 不改变终态。
- 重复撤单不产生错误状态。
- unknown 订单触发风控。

### 阶段 5：Risk Engine

任务：

- 实现价格偏离检查。
- 实现最大订单金额检查。
- 实现最大挂单数量检查。
- 实现库存上限检查。
- 实现行情断流检查。
- 实现最大亏损检查接口。
- 实现 kill switch。

验收：

- 所有订单必须经过风控。
- 风控拒绝订单时记录 risk_event。
- kill switch 触发后禁止新单并撤单。

### 阶段 6：Strategy Engine 与插件

任务：

- 实现策略插件基类。
- 实现策略引擎调度。
- 实现 basic_mm。
- 实现 inventory_skew。
- 实现策略参数热加载或重启加载。

验收：

- 策略输出 QuoteIntent。
- 策略不直接依赖 ExchangeGateway。
- 同一交易对可运行多个策略实例。

### 阶段 7：Quote Engine

任务：

- 实现价格和数量精度对齐。
- 实现最小金额检查。
- 实现报价差分。
- 实现撤旧挂新计划。
- 实现 post-only 防穿价。
- 实现最小重挂间隔。

验收：

- 小价格变化不会疯狂撤挂。
- 价格偏离会触发 replace。
- 不生成违反交易对规则的订单。

### 阶段 8：Paper Trading

任务：

- 实现模拟撮合。
- 模拟订单状态。
- 模拟成交。
- 模拟手续费。
- 模拟余额。
- 输出 PnL。

验收：

- 不需要 API Key 也能运行完整交易循环。
- 可看到策略报价、订单、成交、库存、PnL。

### 阶段 9：监控和运维

任务：

- JSON 日志。
- metrics 指标。
- health check。
- 风控事件日志。
- 订单事件日志。
- 启动参数打印。

核心指标：

- market_data_lag_ms
- order_submit_latency_ms
- order_ack_latency_ms
- cancel_latency_ms
- open_order_count
- inventory_base
- inventory_quote
- realized_pnl
- unrealized_pnl
- risk_event_count
- ws_reconnect_count

验收：

- 日志可追踪单个订单完整链路。
- 关键异常有明确告警事件。

### 阶段 10：真实小资金灰度

默认不在明早前开启大资金实盘。

灰度步骤：

- 设置 live_confirm=true。
- 使用低权限 API Key。
- 限制单笔订单金额。
- 限制总挂单金额。
- 限制交易对。
- 限制运行时间。
- 开启成交后自动暂停。
- 验证全撤。
- 验证重启恢复。
- 验证订单对账。

验收：

- 小资金实盘可提交 maker-only 订单。
- 能撤单。
- 能收到订单回报。
- 能对账。
- 异常时能全撤。

## 9. 明早验收标准

P0 必须完成：

- 项目可启动。
- 配置系统可用。
- paper 模式可运行。
- 策略插件可加载。
- basic_mm 策略可生成报价。
- inventory_skew 策略可调整报价。
- Quote Engine 可生成订单计划。
- OMS 状态机完整。
- Risk Engine 可拦截危险订单。
- kill switch 可停止新单。
- 全撤接口存在。
- BitMart Gateway 具备真实接口封装或 mock 验证。
- 单元测试覆盖核心风控和 OMS。
- README 写明启动方式。

P1 尽量完成：

- BitMart 公共 WebSocket 行情真实接入。
- BitMart 余额查询真实接入。
- BitMart 下单/撤单 sandbox 或小资金测试。
- Prometheus 指标。
- PostgreSQL 持久化。

P2 后续完成：

- 外部交易所指数价。
- 自动对冲。
- Web 管理后台。
- 多机热备。
- 延迟压测。
- ClickHouse 高频行情分析。

## 10. 安全默认值

系统默认配置必须保守：

```yaml
trading_mode: paper
live_confirm: false
cancel_on_start: false
cancel_on_shutdown: true
max_order_value_usdt: 10
max_total_open_value_usdt: 50
max_open_orders: 10
max_position_base: 100
max_price_deviation_bps: 50
stale_market_data_ms: 3000
min_requote_interval_ms: 1000
kill_switch_enabled: true
```

live 模式必须满足：

- 环境变量提供 API Key。
- 配置中 live_confirm=true。
- 配置中 max_order_value_usdt 明确设置。
- 配置中 allowed_symbols 明确设置。
- 风控全部启用。

## 11. 生产上线前检查清单

交易所：

- 确认 BitMart API Key 权限。
- 禁止提现权限。
- 确认 API 限速。
- 确认交易对最小数量和精度。
- 确认手续费等级。
- 确认是否支持 maker-only / post-only。

服务器：

- NTP 时间同步。
- 网络延迟测试。
- 进程守护。
- 日志轮转。
- 密钥管理。
- 监控告警。

系统：

- paper 模式连续运行 2 小时。
- 小资金 live 模式运行 30 分钟。
- 测试 kill switch。
- 测试断网。
- 测试 WebSocket 重连。
- 测试重启恢复。
- 测试订单对账。
- 测试全撤。

资金：

- API Key 无提现权限。
- 单交易对小资金。
- 单笔订单限额。
- 总挂单限额。
- 单日亏损限额。

## 12. 明早可演示流程

演示顺序：

1. 启动系统 paper 模式。
2. 加载 BitMart 交易对配置。
3. 启动行情模块。
4. 展示 fair price。
5. 启动 basic_mm 策略。
6. 展示策略生成双边报价。
7. 展示 Quote Engine 生成订单计划。
8. 展示 OMS 接收订单并进入 OPEN。
9. 模拟成交。
10. 展示库存变化。
11. 展示 inventory_skew 调整下一轮报价。
12. 触发行情断流。
13. 展示 Risk Engine 暂停报价。
14. 触发 kill switch。
15. 展示系统停止新单并撤单。
16. 展示日志和测试结果。

## 13. 结论

明早可以交付一个架构正确、模块完整、默认安全、可运行可演示的生产级做市系统 MVP。

真正的大资金生产上线还需要：

- 至少数天 paper 运行。
- 小资金灰度。
- 交易所限速和订单行为确认。
- 真实网络延迟测试。
- 订单状态异常演练。
- 日志和监控接入。
- 风控参数审查。

开发优先级必须是：OMS 和风控先于策略收益，资金安全先于交易频率。
