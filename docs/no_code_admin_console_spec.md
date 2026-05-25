# 无代码做市量化交易控制台产品规格

版本：v0.1  
目标用户：做市运营、量化策略运营、风控、技术管理员  
目标：用户不写代码，也能完成交易所接入、交易对配置、策略配置、启动/暂停、订单管理、成交监控、风控处理和报表查看。

## 1. 产品定位

这个控制台不是简单 Dashboard，而是做市系统的操作中枢：

- 交易所账号接入中心。
- 交易对和行情配置中心。
- 策略实例管理中心。
- 风控后台。
- 订单和成交管理中心。
- 运行监控和报表中心。
- 审计和权限中心。

控制台必须让用户通过表单、向导、开关、模板和图表完成操作，不要求用户编辑 JSON、命令行或代码。

## 2. 顶层布局

### 2.1 全局布局

```text
┌────────────────────────────────────────────────────────────┐
│ 顶部状态栏：环境 / 交易所连接 / 风控状态 / PnL / Kill Switch │
├───────────────┬────────────────────────────────────────────┤
│ 左侧导航       │ 主工作区                                     │
│               │                                            │
│ 总览           │ 页面标题 / 筛选器 / 操作按钮                   │
│ 交易所账号      │ 表格 / 表单 / 图表 / 详情抽屉 / 确认弹窗         │
│ 交易对市场      │                                            │
│ 策略中心        │                                            │
│ 订单中心        │                                            │
│ 成交与库存      │                                            │
│ 风控后台        │                                            │
│ 数据报表        │                                            │
│ 审计日志        │                                            │
│ 系统设置        │                                            │
└───────────────┴────────────────────────────────────────────┘
```

### 2.2 顶部状态栏

必须一直可见：

- 当前环境：`paper` / `live_read_only` / `live_dry_run` / `live`。
- 交易所连接状态：REST、Public WS、Private WS。
- 当前风控状态：正常、降级、SAFE_MODE。
- 今日 PnL。
- 当前库存敞口。
- 未完成订单数。
- 一键暂停新单。
- 一键全撤入口。
- Kill Switch。

重要原则：危险动作必须二次确认，并显示影响范围。

## 3. 页面模块

## 3.1 系统总览

用户进入后台第一眼看到：

- 系统运行状态。
- 所有交易所连接状态。
- 所有策略运行状态。
- 今日成交量。
- 今日 PnL。
- 当前库存。
- 当前 open orders。
- 风控事件数。
- WebSocket 延迟。
- REST 错误率。

核心卡片：

- `Trading Mode`
- `Exchange Connections`
- `Active Strategies`
- `Open Orders`
- `Inventory Exposure`
- `Daily PnL`
- `Risk Events`
- `System Health`

图表：

- 总资产曲线。
- PnL 曲线。
- 成交量曲线。
- 库存变化曲线。
- WebSocket 延迟曲线。

## 3.2 交易所账号

目标：用户无代码接入 BitMart、后续 Binance/OKX 等。

### 功能

- 新增交易所账号。
- 选择交易所：BitMart / Binance / OKX / Bybit。
- 配置 API Key。
- 配置 API Secret。
- 配置 Memo / Passphrase。
- 配置 REST Endpoint。
- 配置 Public WS Endpoint。
- 配置 Private WS Endpoint。
- 配置是否启用只读模式。
- 配置是否允许下单。
- 配置 IP 白名单确认。
- 配置无提现权限确认。
- 测试 REST 连接。
- 测试公共 WebSocket。
- 测试私有 WebSocket。
- 查询余额。
- 查询 open orders。
- 查询手续费等级。

### 页面布局

```text
交易所账号

[新增账号]

账号列表：
交易所 | 账号名 | 环境 | REST | Public WS | Private WS | 下单权限 | 最后同步 | 操作

账号详情：
- 基础信息
- API Key 配置
- 网络配置
- 权限检查
- 连接测试
- 余额快照
- Open Orders 快照
```

### 安全设计

- Secret 默认不可见。
- Secret 不返回前端明文。
- 保存 Key 前显示权限检查清单。
- Live 下单必须显式打开。
- API Key 有提现权限则禁止上线。
- 缺少 IP 白名单确认则禁止上线。

## 3.3 交易对市场

目标：用户配置目标交易对，并看到同步后的行情数据。

### 功能

- 新增交易对。
- 选择交易所账号。
- 输入交易对，如 `BTC_USDT`。
- 自动同步交易规则：
  - base。
  - quote。
  - price increment。
  - size increment。
  - min size。
  - min notional。
  - fee。
- 配置是否启用做市。
- 配置最大库存。
- 配置最大挂单金额。
- 配置外部参考价格源。
- 配置 fair price 权重。
- 查看价格曲线。
- 查看盘口深度。
- 查看成交流。
- 查看本地 order book 状态。

### 页面布局

```text
交易对市场

交易对列表：
交易对 | 交易所 | 状态 | Mid | Spread | 24h Vol | 外部价 | 延迟 | 操作

交易对详情：
[价格曲线]
[盘口深度]
[成交流]
[交易规则]
[外部价格源]
[库存和限额]
```

### 数据显示

- 实时 mid price。
- bid/ask。
- spread bps。
- order book depth。
- 最近成交。
- 本地价格 vs 外部指数价。
- 行情延迟。
- order book version。
- gap count。

## 3.4 策略中心

目标：用户通过模板创建、配置、启动多个策略实例。

### 策略层级

```text
策略模板 Strategy Template
  └── 策略实例 Strategy Instance
        └── 策略实例 ID + 绑定交易所账号 + 交易对 + 风控参数
```

### 策略模板

内置模板：

- 基础双边做市 `basic_mm`。
- 多层盘口做市 `ladder_mm`。
- 库存偏移 `inventory_skew`。
- 波动率自适应价差 `volatility_spread`。
- 区间库存再平衡 `range_rebalance`。
- 微价格做市 `microprice_mm`。
- 盘口不平衡做市 `order_book_imbalance`。
- Avellaneda-Stoikov 最优做市 `avellaneda_stoikov`。
- 外部指数价做市 `external_fair_price`。
- 防御撤退策略 `defensive_retreat`。
- 跨所对冲策略 `hedged_mm`。

### 策略实例配置

用户创建策略时，不编辑代码，只填表单：

- 策略名称。
- 策略实例 ID，同一策略模板和同一交易对可以创建多个实例，订单槽位按实例 ID 隔离。
- 交易所账号。
- 交易对。
- 模式：paper / dry-run / live。
- 报价间隔。
- 买卖价差 bps。
- 每层订单大小。
- 挂单层数。
- 层间距 bps。
- 最大订单金额。
- 最大挂单金额。
- 最大库存。
- 是否启用库存偏移。
- 是否启用外部价格。
- 是否启用对冲。
- 启动时间。
- 自动暂停条件。

### 区间库存再平衡策略

`range_rebalance` 是被动 maker 库存管理策略，不做主动吃单拉盘或砸盘：

- `direction=auto`：同一实例同时支持补库存区和减库存区。
- `direction=buy_only`：只在低价区补库存，适合和另一个 `sell_only` 实例配成反向组合。
- `direction=sell_only`：只在高价区减库存，和 `buy_only` 使用不同实例 ID，订单不会互相覆盖。
- 当前价格低于 `hard_floor` 或高于 `hard_ceiling`：策略不再输出新报价，QuoteEngine 会撤掉该策略旧报价槽位。
- `hard_floor <= price < buy_below`：当当前 Base 库存低于 `target_base` 时，逐层挂被动买单补库存。
- `sell_above < price <= hard_ceiling`：当当前 Base 库存高于 `target_base` 时，逐层挂被动卖单减库存。
- 中性区间：策略不输出再平衡报价，避免无意义增加订单流。
- 所有报价仍经过最小下单量、post-only 防穿越、最大单笔金额、最大持仓、最大开放订单数和 stale market data 风控检查。

### 策略页面

```text
策略中心

[创建策略实例]

策略实例列表：
名称 | 模板 | 交易所 | 交易对 | 状态 | Mode | Spread | Open Orders | PnL | 操作

操作：
- 启动
- 暂停
- 停止并撤单
- 复制策略
- 编辑参数
- 查看订单
- 查看成交
- 查看日志
```

### 策略详情页

必须显示：

- 参数。
- 当前报价。
- 当前 fair price。
- 当前库存偏移。
- 当前生成的目标订单。
- 实际本地订单。
- 交易所远程订单。
- 成交记录。
- PnL。
- 风控事件。
- 策略日志。

## 3.5 订单中心

目标：用户能看懂本地订单、远程订单和差异，并能安全管理订单。

### 核心视图

订单中心分三个 Tab：

1. 本地订单 Local OMS。
2. 远程订单 Exchange Open Orders。
3. 对账差异 Reconciliation Diff。

### 本地订单表

字段：

- Client Order ID。
- Exchange Order ID。
- 交易所。
- 交易对。
- 策略。
- 方向。
- 价格。
- 数量。
- 已成交。
- 剩余。
- 状态。
- 创建时间。
- 更新时间。
- 最后消息。

操作：

- 查看详情。
- 单笔撤单计划。
- 标记需要对账。
- 查看事件链路。

### 远程订单表

字段：

- Exchange Order ID。
- Client Order ID。
- 交易对。
- 方向。
- 价格。
- 数量。
- 已成交。
- 状态。
- 来源账号。

操作：

- 拉取远程订单。
- 与本地对账。
- 生成撤单计划。

### 对账差异

类型：

- 本地有，远程无。
- 远程有，本地无。
- 状态不一致。
- 数量不一致。
- 成交不一致。

动作：

- 标记 UNKNOWN。
- 拉取单笔订单。
- 生成修复计划。
- 进入 SAFE_MODE。
- 暂停新单。

### 危险操作

以下动作必须二次确认：

- 撤销单笔远程订单。
- 撤销某交易对全部订单。
- 撤销全部订单。
- Kill Switch。

## 3.6 成交与库存

目标：用户能看到成交情况和库存风险。

### 成交列表

字段：

- Trade ID。
- 交易所。
- 交易对。
- 策略。
- 订单 ID。
- 方向。
- 价格。
- 数量。
- 手续费。
- maker/taker。
- 成交时间。

### 库存面板

- base 可用。
- base 冻结。
- quote 可用。
- quote 冻结。
- 当前库存价值。
- 目标库存。
- 偏离比例。
- 库存风险等级。

### 图表

- 库存曲线。
- 成交量曲线。
- 买卖成交分布。
- 手续费统计。

## 3.7 风控后台

目标：所有风控规则可见、可配置、可演练。

### 风控规则

全局风控：

- 最大单笔订单金额。
- 最大挂单金额。
- 最大挂单数量。
- 最大库存。
- 最大日亏损。
- 最大价格偏离。
- 行情过期阈值。
- WebSocket 断流阈值。
- UNKNOWN order 阈值。

策略级风控：

- 单策略最大订单金额。
- 单策略最大挂单数量。
- 单策略最大挂单金额。
- 单策略最大库存贡献。
- 单策略最大亏损。

交易对风控：

- 单交易对最大库存。
- 单交易对最大挂单金额。
- 单交易对最大 open orders。
- 单交易对最大价格偏离。

### 风控页面

```text
风控后台

当前状态：
Normal / Degraded / SAFE_MODE

规则列表：
规则 | 范围 | 阈值 | 当前值 | 状态 | 触发动作 | 操作

操作：
- 演练规则
- 暂停新单
- 恢复新单
- 全撤计划
- Kill Switch
```

## 3.8 数据报表

目标：用户看到策略表现和系统表现。

报表：

- 今日 PnL。
- 累计 PnL。
- 策略 PnL。
- 交易对 PnL。
- 成交量。
- maker/taker 比例。
- 手续费。
- 撤单率。
- 下单成功率。
- 拒单率。
- 风控拦截次数。
- WebSocket 延迟。
- REST 错误率。

图表：

- PnL 曲线。
- 价格曲线。
- 库存曲线。
- 成交量柱状图。
- 策略收益对比。

## 3.9 审计日志

目标：所有操作可追踪。

审计内容：

- 谁修改了 API Key 配置。
- 谁修改了交易对。
- 谁修改了策略参数。
- 谁启动/暂停策略。
- 谁触发全撤。
- 谁触发 Kill Switch。
- 每次订单生成原因。
- 每次风控拒绝原因。

字段：

- 时间。
- 用户。
- 操作类型。
- 对象。
- 旧值。
- 新值。
- 结果。
- Trace ID。

## 4. 用户核心流程

## 4.1 首次接入交易所

```text
交易所账号 -> 新增 BitMart -> 填 API Key -> 权限确认 -> 测试 REST -> 测试 WS -> 保存账号
```

成功后显示：

- REST 正常。
- Public WS 正常。
- Private WS 正常。
- 余额已同步。
- open orders 已同步。

## 4.2 配置交易对

```text
交易对市场 -> 新增交易对 -> 选择账号 -> 输入 BTC_USDT -> 同步规则 -> 开启行情 -> 查看价格曲线
```

成功后显示：

- 实时 bid/ask。
- mid price。
- spread。
- 深度。
- 成交流。

## 4.3 创建策略

```text
策略中心 -> 创建策略 -> 选择 basic_mm -> 选择 BTC_USDT -> 填参数 -> 保存 -> Paper 测试
```

成功后显示：

- 策略状态：Ready。
- 目标报价。
- 预计订单。
- 风控检查通过。

## 4.4 启动策略

```text
策略详情 -> Start Paper / Start Dry Run / Start Live
```

Live 启动前必须通过：

- API Key 无提现权限。
- IP 白名单确认。
- 风控配置完整。
- 交易所连接正常。
- 私有订单流正常。
- open orders 对账通过。
- 用户二次确认。

## 4.5 订单管理

```text
订单中心 -> 查看本地订单 -> 拉取远程订单 -> 对账 -> 处理差异 -> 生成撤单计划
```

撤单必须分两步：

1. 生成撤单计划。
2. 用户确认执行。

## 5. 页面模块与后端 API

### 5.1 交易所账号 API

- `GET /api/exchanges`
- `POST /api/exchanges`
- `POST /api/exchanges/:id/test-rest`
- `POST /api/exchanges/:id/test-public-ws`
- `POST /api/exchanges/:id/test-private-ws`
- `GET /api/exchanges/:id/balances`
- `GET /api/exchanges/:id/open-orders`

### 5.2 交易对 API

- `GET /api/symbols`
- `POST /api/symbols`
- `POST /api/symbols/:symbol/sync-rules`
- `GET /api/symbols/:symbol/market`
- `GET /api/symbols/:symbol/orderbook`
- `GET /api/symbols/:symbol/trades`

### 5.3 策略 API

- `GET /api/strategies`
- `POST /api/strategies`
- `PATCH /api/strategies/:id`
- `POST /api/strategies/:id/start`
- `POST /api/strategies/:id/pause`
- `POST /api/strategies/:id/stop`
- `GET /api/strategies/:id/orders`
- `GET /api/strategies/:id/fills`
- `GET /api/strategies/:id/pnl`

### 5.4 订单 API

- `GET /api/orders/local`
- `GET /api/orders/remote`
- `POST /api/orders/reconcile`
- `POST /api/orders/cancel-plan`
- `POST /api/orders/cancel`
- `POST /api/orders/cancel-all`

### 5.5 风控 API

- `GET /api/risk/status`
- `GET /api/risk/rules`
- `PATCH /api/risk/rules/:id`
- `POST /api/risk/drill`
- `POST /api/risk/pause-new-orders`
- `POST /api/risk/resume-new-orders`
- `POST /api/risk/kill-switch`

## 6. MVP 控制台优先级

### P0

- 交易对配置页面。
- 策略配置页面。
- 订单库页面。
- 本地订单读取。
- 配置保存。
- 策略参数保存。
- 撤单计划 dry-run。
- 验收报告展示。

### P1

- 交易所账号配置。
- API Key 加密保存。
- REST/WS 连接测试。
- 远程 open orders 拉取。
- 本地/远程订单对账。
- 策略启动/暂停。

### P2

- 实时价格曲线。
- 实时盘口。
- 成交流。
- 策略级 PnL。
- 用户权限。
- 审计日志搜索。

## 7. 当前实现状态

当前 Admin 控制台已落地为多页面无代码操作台：

- 系统总览：验收状态、交易所账号数、策略实例数、open orders、成交数、价格曲线。
- 交易所账号：BitMart-first 账号表单、REST/Public WS/Private WS 配置、API Key 安全占位、权限确认、连接 dry-run 校验。
- 交易对市场：交易对表单、交易规则保存、市场列表、行情曲线数据。
- 策略中心：插件模板选择、无代码参数表单、策略实例列表、启动/暂停状态接口。
- 订单中心：本地订单库、远端订单视图、对账差异视图、撤单计划 dry-run。
- 成交与库存：成交列表、余额、PnL。
- 风控后台：风险限额、上线检查、SAFE_MODE 状态、暂停新单接口。
- 审计与报告：验收报告、控制台规格、事件日志、订单库入口。

当前已实现 API：

- `GET /api/config`
- `GET /api/exchanges`
- `POST /api/exchanges`
- `POST /api/exchanges/test`
- `GET /api/symbols`
- `POST /api/symbols`
- `GET /api/strategies`
- `POST /api/strategies`
- `POST /api/strategies/state`
- `GET /api/orders`
- `GET /api/orders/remote`
- `GET /api/orders/reconcile`
- `POST /api/orders/cancel-plan`
- `GET /api/fills`
- `GET /api/inventory`
- `GET /api/market/history`
- `GET /api/risk`
- `POST /api/risk/kill-switch`

当前策略参数表单已按模板区分：

- `basic_mm` 已接入运行时：`spread_bps`、`order_size`、`levels`、`level_spacing_bps`、`size_multiplier`。
- `inventory_skew` 已接入运行时：`target_base`、`skew_bps_per_full_deviation`。
- `ladder_mm` 已接入运行时：买卖侧层数、首层数量、层间距、数量倍数、最远报价距离。
- `volatility_spread` 已接入运行时：波动窗口、波动倍数、最小/最大价差、订单数量、层数。
- `hedged_mm` 已接入运行时：做市价差、订单数量、对冲交易所、对冲阈值、最大滑点、对冲模式。
- `range_rebalance` 已接入运行时：运行方向、下保护价、补库存触发价、减库存触发价、上保护价、目标 Base 库存、买/卖单笔数量、分层数量、挂单偏移、层间距。
- `microprice_mm` 已接入运行时：盘口深度档位、微价格 fair value、价差、订单数量、层数、层间距、数量倍数。
- `order_book_imbalance` 已接入运行时：盘口深度档位、盘口不平衡阈值、偏移 bps、不平衡扩价、订单数量、层数、层间距。
- `avellaneda_stoikov` 已接入运行时：风险厌恶、目标库存、最大库存归一化、波动窗口、风险时间窗、库存风险倍数、动态价差上下限。

深度行情方案：

- `MarketSnapshot` 支持 `bids` / `asks` 多档盘口，同时保留 L1 `bid` / `ask` / `bid_size` / `ask_size`，旧策略兼容。
- BitMart 增量深度进入 `OrderBook` 后输出完整 L2 快照；Paper 模式生成 5 档模拟盘口；回放会恢复历史事件中的 `bids` / `asks`。
- `microprice_mm` 和 `order_book_imbalance` 通过 `depth_levels` 控制聚合档位；没有深度时自动降级为 L1。
- Runtime Snapshot 输出每个交易对的深度档位计数，便于验收 WebSocket 深度是否真的接入。

全部策略模板现在都能保存为策略实例。`hedged_mm` 产生做市报价，并通过现有 hedging engine 在成交后生成 dry-run 对冲结果；真实跨所对冲仍需要在 live 上线前接入交易所账号、私有订单流和权限审计。

下一阶段生产化需要补：

- API Key 使用系统钥匙串或 KMS 加密保存。
- live_read_only 远程订单、余额、成交只读同步。
- 私有 WebSocket 订单流和本地 OMS 对账闭环。
- 策略启动/暂停接入真实运行时 supervisor。
- 操作员登录、角色权限、二次确认、审计日志搜索。
