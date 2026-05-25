# 大资金高频做市交易系统最终生产路线图

版本：v0.1  
日期：2026-05-25  
首要交易所：BitMart Spot  
目标：可承载大资金、可长期运行、可审计、可风控、可灰度、可灾备的生产级做市系统

## 1. 结论先行

可以做成最终生产系统，但不能把“写完代码”视为“可以大资金上线”。大资金高频做市系统的交付标准必须包含：

- 架构正确。
- 订单系统正确。
- 风控不可绕过。
- 真实 API 限速和交易所行为验证完成。
- 连续 paper trading 稳定运行。
- 小资金 live 灰度稳定运行。
- 故障演练通过。
- PnL、库存、订单、成交全部可追踪。
- kill switch 和全撤通过实测。
- 监控告警接入。
- 运维和值班流程明确。

最终生产系统不是单个程序，而是一套交易、风控、数据、运维、审计、灰度和灾备体系。

## 2. BitMart 当前关键约束

根据 BitMart 官方现货 API 文档和 FAQ，生产设计必须考虑：

- REST 基础地址：`https://api-cloud.bitmart.com`
- 签名接口需要 `X-BM-KEY`、`X-BM-SIGN`、`X-BM-TIMESTAMP`。
- 现货新订单 `/spot/v2/submit_order` 当前限速为 UID 维度 `40 times / 2 sec`。
- 现货批量下单 `/spot/v4/batch_orders` 当前限速为 UID 维度 `40 times / 2 sec`。
- 撤单 `/spot/v3/cancel_order` 当前限速为 UID 维度 `40 times / 2 sec`。
- 批量撤单 `/spot/v4/cancel_orders` 当前限速为 UID 维度 `40 times / 2 sec`。
- 全撤 `/spot/v4/cancel_all` 当前限速为 UID 维度 `1 time / 3 sec`。
- 当前 open orders 查询 `/spot/v4/query/open-orders` 当前限速为 API Key 维度 `12 times / 2 sec`。
- public market REST 深度不是实时数据，实时行情应使用 WebSocket。
- 现货订单类型包含 `limit`、`market`、`limit_maker`、`ioc`。
- `limit_maker` 是 PostOnly 订单，做市默认使用它。
- 支持 STP 自成交保护：`none`、`cancel_maker`、`cancel_taker`、`cancel_both`。
- 订单状态包含 `new`、`partially_filled`、`filled`、`canceled`、`partially_canceled`。
- 私有订单 WebSocket 可订阅 `spot/user/order:<symbol>` 或 `spot/user/orders:ALL_SYMBOLS`。
- 私有余额 WebSocket 可订阅 `spot/user/balance:BALANCE_UPDATE`。
- FAQ 显示现货公共 WebSocket 单 IP 最多 20 条连接，私有 WebSocket 单 IP 最多 10 条连接。
- FAQ 显示现货深度增量最快推送速度为 100ms。

设计含义：

- 不允许策略无限撤挂。
- 必须做限速预算。
- 必须优先使用 WebSocket，而不是 REST 轮询行情。
- 必须维护本地订单状态，不能依赖高频 REST 查单。
- 全撤不能被当作高频常规动作，只能作为熔断动作。
- 报价频率必须受交易所限速、盘口变化和风险预算共同约束。

## 3. 最终生产架构

```text
                        ┌──────────────────────────────┐
                        │ Operator Console / Admin API  │
                        │ 参数 / 暂停 / 全撤 / 审计       │
                        └───────────────┬──────────────┘
                                        │
┌──────────────────┐      ┌─────────────▼─────────────┐
│ External Markets  │────▶│ Market Data Service        │
│ Binance/OKX/CB等  │      │ BitMart WS / External WS    │
└──────────────────┘      │ OrderBook / Fair Price      │
                          └─────────────┬─────────────┘
                                        │
                          ┌─────────────▼─────────────┐
                          │ Strategy Service           │
                          │ Plugin Sandbox / Signals   │
                          └─────────────┬─────────────┘
                                        │ QuoteIntent
                          ┌─────────────▼─────────────┐
                          │ Quote & Throttle Service   │
                          │ Diff / Tick Align / Budget │
                          └─────────────┬─────────────┘
                                        │ OrderIntent
                          ┌─────────────▼─────────────┐
                          │ Pre-Trade Risk Service     │
                          │ Position / Price / Loss    │
                          └─────────────┬─────────────┘
                                        │ ApprovedIntent
                          ┌─────────────▼─────────────┐
                          │ OMS Service                │
                          │ State / Idempotency / WAL  │
                          └─────────────┬─────────────┘
                                        │
                          ┌─────────────▼─────────────┐
                          │ Exchange Gateway           │
                          │ BitMart REST / Private WS  │
                          └─────────────┬─────────────┘
                                        │
                                      BitMart

              ┌────────────────────────────────────────────────┐
              │ Event Bus / Database / Metrics / Alert / Replay │
              └────────────────────────────────────────────────┘
```

## 4. 服务拆分

### 4.1 Market Data Service

职责：

- BitMart 公共 WebSocket 行情。
- BitMart order book 重建。
- 外部交易所行情接入。
- 聚合 fair price。
- 行情断流检测。
- 市场异常检测。
- 数据质量评分。

生产要求：

- 每个交易所连接独立进程。
- 断线自动重连。
- 订阅恢复。
- order book gap 检测。
- 快照和增量一致性校验。
- 延迟指标上报。
- 行情事件持久化采样。

### 4.2 Strategy Service

职责：

- 加载策略插件。
- 接收标准化行情。
- 接收库存和订单状态。
- 输出 QuoteIntent。

生产要求：

- 策略沙箱化。
- 策略无权直接下单。
- 单策略 CPU/内存限制。
- 策略异常自动降级或禁用。
- 策略参数版本化。
- 策略输出必须可回放。

### 4.3 Quote & Throttle Service

职责：

- 报价差分。
- 防止无意义撤挂。
- 交易所 tick/step 对齐。
- post-only 保护。
- 限速预算分配。
- 多策略订单合并。

生产要求：

- 每个 UID 下单预算、撤单预算独立维护。
- 每个 symbol 分配最小和最大预算。
- 优先撤高风险订单，再挂新订单。
- 撤单请求和下单请求分队列。
- 全撤使用独立熔断通道。

### 4.4 Pre-Trade Risk Service

职责：

- 所有订单进入交易所前的最后检查。

必须拦截：

- 非白名单交易对。
- live 模式未确认。
- API Key 权限异常。
- 价格偏离 fair price。
- 价格穿越对手盘导致 taker。
- 单笔金额超限。
- 总挂单金额超限。
- 单边挂单超限。
- 库存超限。
- 亏损超限。
- 行情陈旧。
- 外部指数价不可用。
- 私有订单流断开。
- OMS 未完成对账。
- 系统处于 SAFE_MODE。

### 4.5 OMS Service

职责：

- 订单写前日志。
- clientOrderId 生成。
- 下单幂等。
- 撤单幂等。
- 订单状态机。
- 交易所 ack 处理。
- 私有 WS 回报处理。
- REST 对账。
- 重启恢复。
- orphan order 处理。

生产要求：

- 下单前先写 WAL。
- 任何订单请求都有全局唯一 trace id。
- 订单状态只能按合法路径迁移。
- 终态订单不可回退。
- 状态不明必须进入 UNKNOWN 并触发风控。
- 重启后先对账，后报价。
- 对账未完成禁止新单。

### 4.6 Exchange Gateway

职责：

- BitMart API 适配。
- REST 签名。
- HTTP 连接池。
- WebSocket 登录。
- 统一错误码。
- 限速 headers 解析。
- 429/418 退避。
- 5xx 重试。
- API 时间同步。

生产要求：

- 所有请求设置 recvWindow。
- 系统时间 NTP 同步。
- 签名 body 必须稳定序列化。
- 请求 timeout 分级。
- 网络错误不盲目重试下单。
- submit_order 超时后必须查单确认。
- cancel_order 超时后必须查单确认。

### 4.7 Inventory & Hedging Service

职责：

- 实时库存。
- 目标库存。
- 库存偏移。
- 跨所对冲。
- 对冲失败处理。

生产要求：

- 大资金上线必须有外部深度交易所对冲通道。
- 对冲交易所与 BitMart API Key 隔离。
- 对冲策略单独风控。
- 对冲失败会降低做市规模或停止报价。
- 对冲成本进入报价模型。

### 4.8 Monitoring & Ops

职责：

- 指标。
- 日志。
- 告警。
- 审计。
- 运维操作。

生产要求：

- Prometheus 指标。
- Grafana 看板。
- 结构化日志。
- 风控事件实时告警。
- 关键操作审计。
- 全撤操作双确认。
- 值班手册。

## 5. 部署架构

### 5.1 单机生产最小形态

适合小资金灰度：

```text
1 台交易服务器
- market-data
- strategy
- quote-risk-oms
- exchange-gateway
- postgres
- redis
- prometheus
- grafana
```

### 5.2 大资金推荐形态

```text
Primary Trading Node
- market-data
- strategy
- quote
- risk
- oms
- exchange-gateway

Standby Trading Node
- warm standby
- read-only market-data
- no live order unless promoted

Data Node
- postgres primary/replica
- redis
- clickhouse
- prometheus
- grafana
- log storage

Ops Node
- admin console
- alert manager
- deployment controller
```

### 5.3 高可用原则

- active/passive，不建议两个 active 同时控制同一 UID 同一交易对。
- 主备切换前必须全撤或完成订单 ownership 转移。
- 策略服务可多实例，OMS 对同一账户必须单主。
- API Key 分账户、分交易对、分环境管理。

## 6. 开发阶段和验收门槛

### 阶段 1：生产骨架

周期：1-2 周

交付：

- 工程脚手架。
- 配置系统。
- 事件模型。
- 日志系统。
- 单元测试框架。
- Docker Compose。
- paper 模式主循环。

验收：

- 系统可启动、停止、重启。
- 无 API Key 可运行 paper。
- 配置错误会 fail fast。

### 阶段 2：BitMart 接入

周期：1-2 周

交付：

- REST signer。
- market rules。
- fee query。
- balance query。
- submit order。
- cancel order。
- batch orders。
- cancel all。
- open orders。
- private order WS。
- private balance WS。
- public market WS。

验收：

- mock 测试覆盖所有接口。
- 小额真实查询通过。
- 下单超时查单流程通过。
- 撤单超时查单流程通过。

### 阶段 3：OMS 和对账

周期：2 周

交付：

- WAL。
- 状态机。
- 幂等。
- 本地 open order book。
- 私有 WS 回报处理。
- REST 定期对账。
- 重启恢复。
- orphan order 处理。

验收：

- 订单生命周期测试 100% 通过。
- 模拟乱序回报测试通过。
- 模拟重复回报测试通过。
- 模拟下单超时测试通过。
- 模拟撤单超时测试通过。
- 重启恢复测试通过。

### 阶段 4：风控系统

周期：2 周

交付：

- 前置风控。
- 运行中风控。
- 后置风控。
- kill switch。
- 全撤流程。
- SAFE_MODE。
- 风控事件审计。

验收：

- 所有订单不可绕过风控。
- 价格偏离、库存超限、亏损超限、行情断流都能停止新单。
- kill switch 到达交易所并完成撤单确认。
- 全撤失败时有升级处理。

### 阶段 5：做市策略

周期：2-4 周

交付：

- 基础双边报价。
- 多层盘口报价。
- 库存偏移。
- 波动率自适应 spread。
- 外部指数价 fair price。
- 盘口不平衡调整。
- 防御撤退策略。

验收：

- 策略输出可回放。
- 策略参数可版本化。
- 策略异常不影响 OMS。
- 策略在 paper 模式连续运行 7 天。

### 阶段 6：对冲系统

周期：2-4 周

交付：

- Binance/OKX 至少一个对冲交易所接入。
- 对冲订单管理。
- 对冲失败处理。
- 净敞口计算。
- 对冲成本入账。

验收：

- BitMart 成交后可触发对冲。
- 对冲失败会自动降级或停止做市。
- 净敞口在限制内。

### 阶段 7：数据和回测

周期：2-3 周

交付：

- 行情录制。
- 订单事件录制。
- 成交事件录制。
- 策略回放。
- paper matching engine。
- PnL 分析。

验收：

- 任意生产交易日可回放。
- 任意订单可追踪完整链路。
- 策略变更可用历史行情回测。

### 阶段 8：压测和故障演练

周期：2-3 周

交付：

- 行情压力测试。
- 订单压力测试。
- REST 限速测试。
- WebSocket 断线测试。
- 数据库故障测试。
- 交易所 5xx 测试。
- 网络抖动测试。
- 进程崩溃恢复测试。

验收：

- 24 小时 paper 稳定。
- 7 天 paper 稳定。
- 小资金 live 运行稳定。
- 所有 P0 故障都有自动安全动作。

### 阶段 9：小资金灰度

周期：1-4 周

灰度阶梯：

```text
Level 0: paper only
Level 1: live 查询 + 不下单
Level 2: 单交易对，单笔 <= 10 USDT
Level 3: 单交易对，单笔 <= 100 USDT
Level 4: 多交易对，小总资金
Level 5: 中等资金，开启对冲
Level 6: 大资金，正式值班
```

每一级必须满足：

- 无 unknown order。
- 无不可解释 PnL。
- 无连续 429。
- 无未处理 5xx。
- 无 stale order。
- 全撤测试通过。
- 日终对账通过。

### 阶段 10：大资金上线

上线前硬条件：

- paper 连续 7 天无 P0。
- 小资金 live 连续 7 天无 P0。
- 中资金 live 连续 14 天无 P0。
- 对冲通道稳定。
- 全撤演练通过。
- 主备切换演练通过。
- 日终对账准确。
- PnL 与交易所账单一致。
- 运维值班就绪。
- API Key 权限最小化。

## 7. 高频设计原则

### 7.1 不是越快撤挂越好

BitMart 的 UID 级下单/撤单限速决定了系统必须珍惜订单预算。报价引擎应避免：

- 每个 tick 都撤挂。
- 因为 1 个 tick 变化撤掉所有层。
- 多策略重复挂同价订单。
- 正常行情下频繁全撤。

### 7.2 高频应该体现在内部决策

可以高频计算：

- fair price。
- order book imbalance。
- volatility。
- inventory skew。
- adverse selection risk。

但实际发往交易所的订单必须经过：

- 最小重挂间隔。
- 价格变化阈值。
- 风险收益判断。
- 限速预算。

### 7.3 报价优先级

从高到低：

1. 撤掉危险订单。
2. 撤掉穿价订单。
3. 撤掉库存风险方向订单。
4. 更新最靠近盘口的订单。
5. 补充深度层订单。
6. 低优先级远端订单。

## 8. 大资金风控标准

### 8.1 资金风险

- 单账户资金上限。
- 单 API Key 资金上限。
- 单交易对资金上限。
- 单策略资金上限。
- 单方向库存上限。
- 单日亏损上限。
- 单小时亏损上限。
- 单分钟亏损上限。

### 8.2 市场风险

- 外部指数价缺失。
- 本地价格偏离指数价。
- spread 异常收窄。
- order book 深度骤降。
- 成交量异常。
- 价格跳变。
- 交易所维护状态。

### 8.3 技术风险

- WebSocket 断线。
- 私有订单流断线。
- REST 连续失败。
- 429 或 418。
- 服务器时间漂移。
- 数据库写入失败。
- 事件队列积压。
- 进程内存异常。
- CPU 延迟异常。

### 8.4 操作风险

- 参数误配置。
- 错误交易对。
- 错误小数精度。
- API Key 权限过大。
- 未经审批切 live。
- 多实例重复控制同一账户。

## 9. 必须实现的熔断矩阵

```text
触发事件                         动作
行情断流                         暂停新单 + 撤本交易对
私有订单流断线                   暂停新单 + 查询 open orders
REST 429 连续出现                降低频率 + 暂停非必要请求
REST 418                         立即 SAFE_MODE
订单 UNKNOWN 超阈值              暂停新单 + 对账
库存超限                         停止增加库存方向订单
亏损超限                         全撤 + SAFE_MODE
价格偏离指数价                   全撤该交易对
对冲失败                         降低规模或停止报价
数据库不可写                     停止新单
主备同时 active                  双方停止新单 + 人工介入
```

## 10. 数据和审计标准

每个订单必须能回答：

- 哪个策略生成？
- 哪个 fair price？
- 当时盘口是什么？
- 为什么挂这个价格？
- 经过哪些风控规则？
- 是否被修改？
- 何时发送交易所？
- 交易所何时 ack？
- 何时成交？
- maker 还是 taker？
- 手续费多少？
- 成交后库存如何变化？
- 是否触发对冲？
- 这笔交易对 PnL 贡献是多少？

所有关键事件必须有：

- trace_id
- strategy_id
- symbol
- exchange
- monotonic_time
- wall_clock_time
- config_version
- code_version

## 11. 监控指标

### 11.1 行情

- market_data_lag_ms
- orderbook_gap_count
- ws_reconnect_count
- fair_price_age_ms
- external_price_age_ms

### 11.2 订单

- order_submit_latency_ms
- order_ack_latency_ms
- cancel_latency_ms
- order_unknown_count
- open_order_count
- maker_fill_ratio
- taker_fill_ratio
- reject_count

### 11.3 限速

- rest_rate_limit_remaining
- rest_429_count
- rest_418_count
- order_budget_used
- cancel_budget_used

### 11.4 资金和 PnL

- inventory_base
- inventory_quote
- gross_exposure
- net_exposure
- realized_pnl
- unrealized_pnl
- fee_paid
- hedge_cost

### 11.5 系统

- event_loop_lag_ms
- queue_depth
- db_write_latency_ms
- process_memory_mb
- cpu_percent
- safe_mode_state

## 12. 团队分工建议

最少配置：

- 交易系统工程师：OMS、交易所网关。
- 策略工程师：做市策略、回测、参数。
- 风控工程师：风控规则、PnL、库存。
- 后端工程师：API、配置、数据库。
- DevOps/SRE：部署、监控、告警、主备。
- QA/测试工程师：模拟交易、异常测试、压测。

如果只有一个开发者，也可以做，但周期要拉长，且上线规模必须保守。

## 13. 预计周期

### 13.1 可用于小资金实盘

预计：4-8 周

条件：

- BitMart 接入完整。
- OMS 和风控完整。
- paper 连续稳定。
- 小资金灰度通过。

### 13.2 可用于中等资金稳定运行

预计：8-12 周

条件：

- 对冲接入。
- 监控完善。
- 故障演练通过。
- 多日 live 稳定。

### 13.3 可用于大资金高频生产

预计：12-20 周

条件：

- 主备。
- 完整审计。
- 策略回放。
- 严格风控。
- 多交易所对冲。
- 长期稳定数据。
- 运维流程。

## 14. 下一步执行顺序

第一步，建立正式工程：

- Python MVP 骨架。
- 配置系统。
- 类型模型。
- 事件日志。
- paper trading。

第二步，先做 OMS 和风控：

- 不先追求策略收益。
- 先保证订单不会乱。
- 先保证危险订单发不出去。

第三步，接 BitMart：

- REST 签名。
- 行情 WebSocket。
- 私有订单 WebSocket。
- 下单撤单。
- 对账。

第四步，策略插件：

- basic_mm。
- inventory_skew。
- volatility_spread。
- external_fair_price。

第五步，连续测试：

- mock。
- paper。
- live read-only。
- live tiny capital。
- live small capital。

第六步，大资金前置：

- 对冲。
- 主备。
- 监控。
- 灾备。
- 值班。
- 审计。

## 15. 不可接受的上线方式

以下任何一种都不允许大资金上线：

- 没有私有订单 WebSocket。
- 没有订单对账。
- 没有 kill switch。
- 没有全撤实测。
- 没有 API 限速保护。
- 没有库存上限。
- 没有亏损上限。
- 没有外部指数价。
- 没有异常行情撤退。
- 没有小资金灰度。
- 没有日志审计。
- API Key 有提现权限。
- 多个实例同时控制同一账户。

## 16. 官方资料来源

- BitMart Spot API Reference: https://developer-pro.bitmart.com/en/spot/
- BitMart Spot API FAQ: https://developer-pro.bitmart.com/en/faq/
