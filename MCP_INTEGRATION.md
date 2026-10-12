# MCP_INTEGRATION：麦当劳 MCP 集成说明

本项目真实调用麦当劳中国官方 MCP Server，并可选联动高德地图 MCP 与小红书 MCP。以下所有字段与规则均来自 2026-10-12 使用真实 Token 的 `tools/list` 与实际调用结果。

## 1. 使用的 MCP Server

| Server | 地址 | 协议 | 鉴权 | 是否必需 |
|---|---|---|---|---|
| 麦当劳 MCP（mcd-mcp 1.0.0） | `https://mcp.mcd.cn` | Streamable HTTP（协议版本 2025-06-18） | `Authorization: Bearer ${MCD_MCP_TOKEN}` | 必需（离线演示模式除外） |
| 高德地图 MCP | `https://mcp.amap.com/mcp?key=${AMAP_MAPS_API_KEY}` | Streamable HTTP | URL 参数 key | 可选（`--from`、`--play`） |
| 小红书 MCP（xiaohongshu-mcp，本机） | `http://127.0.0.1:18060/mcp` | Streamable HTTP | 无 | 可选（`share --publish`） |

配置示例见 `mcp-config.example.json`（只含环境变量占位符）。

## 2. 使用的麦当劳 MCP Tool

| Tool | 用途 | 关键入参 | 本项目如何使用返回值 |
|---|---|---|---|
| `query-nearby-stores` | 找门店 | `beType`(1 到店 / 5 得来速), `searchType=2`, `city`, `keyword` | 取 storeCode、营业状态、可预约时段；得来速取 beCode |
| `delivery-query-addresses` | 外送地址 | 无 | 只展示 addressId 与脱敏摘要 |
| `delivery-query-stores` | 外送门店 | `beType=2`, `addressId` | 取 storeCode + beCode |
| `query-meals` | 门店实时菜单 | `storeCode`, `orderType`, `beType`, 预约时 `reservationDate` | 优先"开心乐园"分类作为宝宝餐候选 |
| `list-nutrition-foods` | 官方营养数据 | 无 | 解析 160 条单品的能量 / 蛋白 / 钠 / 钙，钠用于份量计算 |
| `query-meal-detail` | 套餐组成与特制 | `storeCode`, `orderType`, `beType`, `code` | `rounds` 换搭配，`modification` 生成去料入参 |
| `calculate-price` | 实时核价 | 门店参数 + `items` | 校验特制入参被接受，取实付金额与 `takeWayList` |
| `create-order` | 下单 | 门店参数 + `items` + `takeWayCode` / `addressId` + `remark` | 仅在 `order --confirm` 时调用，不自动重试 |
| `query-order` | 查单 | `orderId` | 核验特制项是否体现在订单详情 |
| `cancel-order` | 取消 | `orderId`, `cancelReasonCode` | 用于验收闭环 |
| `campaign-calendar` | 官方活动日历 | 无 | 实测返回 JSON（`data.dailyList[].events[].articleDto{title, content}`），筛出亲子相关活动（如过家家派对、亲子读书会、趣读派对）展示在定制单中 |

## 3. 调用流程

```
plan --age-months 18 --city 上海市 --keyword 人民广场 --when "2026-10-20 11:30"
 │
 ├─ query-nearby-stores ─────────► 选第一家营业中 / 可预约的门店
 ├─ query-meals ─────────────────► 门店实时菜单（86 个餐品，含 3 种开心乐园餐）
 ├─ list-nutrition-foods ────────► 160 条官方营养数据
 ├─ query-meal-detail × ≤4 ──────► 每个候选套餐的轮次与特制项
 │     └─ 本地：换搭配（牛奶 / 玉米杯 / 苹果片）+ 去料（开关型特制组整组传入）
 │     └─ 本地：年龄档位钠预算 → 份量（1、3/4、1/2、1/3、1/4）→ 排序
 ├─ calculate-price ─────────────► 用宝宝特制入参实时核价
 ├─ campaign-calendar ───────────► 本月亲子活动；套餐详情中的玩具轮次 → 随餐玩具
 └─ 输出：定制单 + 店员话术卡 + 钠预算表（+ 手机卡片 / 打卡照 / 识物卡 / 高德 / 小红书草稿）

order --plan plan.json [--confirm]
 ├─ calculate-price ─────────────► 再次核价，展示金额与线上去料
 └─ create-order（仅 --confirm）─► 返回订单与支付信息
```

## 4. 参数规则（实测）

| 场景 | beType | orderType | beCode | takeWayCode | addressId |
|---|---|---|---|---|---|
| 到店自提 | 1 | 1 | 不传（传了报错） | 下单必传，取自 calculate-price 的 `takeWayList[].code` | - |
| 得来速 | 5 | 1 | 必传 | 同上 | - |
| 麦乐送 | 2 | 2 | 必传 | 不传 | 必传 |

- 预约时 `reservationDate`（`yyyy-MM-dd HH:mm`）需在 query-meals / query-meal-detail / calculate-price / create-order 中保持一致
- `tools/call` 结果同时带 `structuredContent` 与 `content[0].text`（Markdown 说明 + JSON），优先解析前者
- 菜单 `currentPrice` 单位为元，`calculate-price` 返回单位为分
- 门店返回的经纬度为 0，步行距离需借助高德

### 特制（去料）入参

官方 `tools/list` 原文规则：对包含 `unselectedKey` 的特调组，**组内所有特调项都必须传入**，保留项用 `selectedKey`，去掉项用 `unselectedKey`。本项目实现：

```json
{"productCode": "9900016057", "quantity": 1, "roundList": [
  {"round": "1", "comboItemList": [{"code": "1000", "quantity": 1, "modification": {"values": [
    {"code": "100202", "key": "0-0", "quantity": 0},
    {"code": "100212", "key": "0-0", "quantity": 0},
    {"code": "100214", "key": "0-0", "quantity": 0},
    {"code": "102230", "key": "0-0", "quantity": 0}]}}]},
  {"round": "2", "comboItemList": [{"code": "504643", "quantity": 1}]},
  {"round": "3", "comboItemList": [{"code": "4437", "quantity": 1}]},
  {"round": "4", "comboItemList": [{"code": "3755", "quantity": 1}]},
  {"round": "5", "comboItemList": [{"code": "521991", "quantity": 1}]}]}
```

上面这组入参（汉堡开心乐园餐，汉堡包去掉酸黄瓜 / 洋葱粒 / 番茄酱 / 芥末酱）已被真实 `calculate-price` 接受：金额 2350 分，取餐方式 `locker-out`（外带，店外取餐柜）。冰量这类单选组（无 `unselectedKey`）不做改动。

## 5. 联动的其他 MCP

| MCP | Tool | 用途 |
|---|---|---|
| 高德 | `maps_weather` | 用餐当天天气；有雨雪时提示"带娃可选得来速或麦乐送" |
| 高德 | `maps_geo` | 出发地点转坐标 |
| 高德 | `maps_text_search` + `maps_search_detail` | 按门店名称找 POI 并取坐标（实测：直接对门店地址做地理编码只能到道路级，误差约 1 公里，故不用） |
| 高德 | `maps_direction_walking` | 步行时间与距离（实测人民广场到华旭国际大厦店 938 米、约 13 分钟） |
| 高德 | `maps_schema_navi` | 生成高德导航唤端链接 |
| 高德 | `maps_around_search` | 门店周边 2 公里的"儿童乐园""公园"；交替取候选、同品牌去重、至少保留一个公园，按步行时间排序（饭后遛娃） |
| 小红书 | `publish_content` | 用户确认后发布笔记（默认"仅自己可见"） |

### 高德免费 Key 的限流

实测连续调用会返回 `CUQPS_HAS_EXCEEDED_THE_LIMIT`。在线高德客户端外包一层节流：两次调用间隔至少 0.35 秒，遇到限流退避 1 秒后重试，总共最多尝试 3 次；高德异常不影响定制单主流程。

## 6. 业务价值

- **补上系统缺口**：小红书上家长反复提到"系统没有去盐选项，付完单要当面跟店员说"。本项目把线上能去的配料自动去掉，把线上去不掉的诉求变成一张可以直接出示的话术卡（外送场景写进订单备注）
- **按国标给份量**：以中国营养学会《家庭减盐行为指南》与《中国居民膳食指南（2022）》为依据，把官方营养数据换算成"这一餐宝宝吃几分之几"，避免家长凭感觉
- **真实可下单**：所有餐品、价格、特制项均来自门店实时接口，计算结果可直接核价下单
- **合规正向**：主张"偶尔吃、吃得明白"，不贬低、不比较，不做医疗建议

## 7. 已知限制

- 官方营养数据为默认配方整份数值，没有分配料数据，去料后的钠只能按"不高于"计算
- 官方未提供过敏原数据，本项目仅按名称做"可能含"提示
- "不撒盐 / 不加盐"无法线上下单，门店可能无法满足（例如肉饼为预制）
- `calculate-price` 不回显特制项，是否生效以 `query-order` 与小票为准
- 门店是否有儿童游乐设施（滑梯等）：麦当劳 MCP 门店数据与高德 POI 详情均无该字段，本项目不做推断，改为推荐门店周边的儿童乐园与公园
