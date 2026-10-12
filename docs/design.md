# 设计文档：小小麦门 · 带娃吃麦定制官（mcd-baby-bite）

- 日期：2026-10-12
- 状态：已评审通过（对话中确认）
- 调研依据：`/Users/wenzhou/ob/个人项目/mc/麦当劳MCP创意大赛-调研与Top3方案.md`

## 1. 目标

为带 1-6 岁孩子（主打 1-3 岁）外出吃麦当劳的家长，基于**门店真实在售菜单**和**官方营养数据**，一次性给出：

1. **宝宝定制单**：选出适合宝宝的餐品和份量，套餐内可换的搭配自动换（饮料选纯牛奶、小食选玉米杯或苹果片），可特制的配料自动去掉（酱、吉士、酸黄瓜、洋葱等）
2. **大人餐**（可选，按人数给常规推荐，不做营养约束）
3. **店员话术卡**：线上去不掉的诉求（肉饼不撒盐、薯条不加盐），到店出示；外送场景写进订单备注（`remark`，≤50 字）
4. **钠预算说明**：按年龄档位的每日食盐上限换算单餐钠预算，展示每样餐品的官方钠含量和建议份量

下单为可选步骤，必须显式确认。

### 非目标

- 不做通用点餐助手、优惠券、积分（赛道已饱和）
- 不做医疗或营养诊断；不面向 12 月龄以下
- MVP 不做外送地址管理以外的外送全链路（见第 9 节分期）

## 2. 交付形态

```
mcd-baby-bite/
├── SKILL.md                    # Agent Skill 定义（Claude Code / WorkBuddy / Cursor 等可加载）
├── README.md                   # 必备：介绍、安装、使用示例、目标用户
├── MCP_INTEGRATION.md          # 必备：用到的 Server / Tool / 调用流程 / 业务价值
├── CONTEST_DECLARATION.md      # 必备：官方原文逐字拷贝，不可改动
├── mcp-config.example.json     # 必备：仅环境变量占位符
├── LICENSE                     # MIT
├── babybite/                   # Python 3.9+ 标准库实现，零第三方依赖
│   ├── __init__.py
│   ├── __main__.py             # python3 -m babybite
│   ├── cli.py
│   ├── mcp_client.py           # Streamable HTTP 客户端 + 离线回放客户端
│   ├── scenes.py               # 到店 / 得来速 / 外送 的参数规则
│   ├── nutrition.py            # 营养表解析 + 名称匹配
│   ├── age_rules.py            # 年龄档位、钠预算、禁忌
│   ├── menu.py                 # 菜单、套餐详情的结构化解析
│   ├── planner.py              # 宝宝餐组合与份量
│   ├── customize.py            # rounds 换搭配 + modification 去料，生成下单入参
│   ├── cards.py                # Markdown / JSON / HTML 卡片 / 话术卡 / 备注
│   └── errors.py
├── fixtures/real/              # 用真实 Token 录制并脱敏的响应（离线演示与测试用）
├── examples/                   # 真实运行输出
├── scripts/
│   ├── record_fixtures.py      # 真实录制（只读接口）
│   └── smoke_real.py           # 真实只读冒烟
├── tests/                      # unittest
└── docs/
    ├── design.md               # 本文件
    ├── plan.md                 # 实施计划
    └── index.html              # GitHub Pages 演示页（静态）
```

## 3. 麦当劳 MCP 接口事实（2026-10-12 用真实 Token 实测）

- 地址 `https://mcp.mcd.cn`；`initialize` 返回 `serverInfo={name: mcd-mcp, version: 1.0.0}`，`protocolVersion=2025-06-18`
- 响应 `Content-Type: application/json`（非 SSE），**不返回 `Mcp-Session-Id`**；客户端仍需兼容 SSE 与会话头
- `tools/call` 结果同时含 `structuredContent`（标准 JSON：`success/code/message/datetime/traceId/data`）和 `content[0].text`（Markdown 说明 + JSON）。**优先使用 `structuredContent`**，缺失时从 text 中第一个 `{"success"` 处 `raw_decode`
- 金额单位：菜单 `currentPrice` 为"元"字符串（如 `"23.5"`）；`calculate-price` 返回为"分"
- 共 35 个 Tool

### 3.1 场景参数

| 场景 | beType | orderType | beCode | takeWayCode | addressId | 门店来源 |
|---|---|---|---|---|---|---|
| 到店自提 pickup | 1 | 1 | 不传（传了报错） | create-order 必传，取自 calculate-price 的 `data.takeWayList[].code` | - | query-nearby-stores |
| 得来速 drive | 5 | 1 | 必传 | 同上 | - | query-nearby-stores |
| 麦乐送 delivery | 2 | 2 | 必传 | 不传 | 必传 | delivery-query-stores |

`reservationDate`（`yyyy-MM-dd HH:mm`）在预约场景下需全链路一致（query-meals / query-meal-detail / calculate-price / create-order）。

### 3.2 关键 Tool

| Tool | 必填 | 返回要点 |
|---|---|---|
| `query-nearby-stores` | beType, searchType(2=按位置，需 city + keyword) | `data[]`: storeCode, storeName, address, distance, businessStatus, businessStartTime/EndTime, beCode(得来速), reservation, reservationTimeOptions[] |
| `query-meals` | storeCode, orderType, beType | `data.categories[] {name, meals:[{code}]}`，`data.meals {code: {name, currentPrice, originalPrice, canWithOrder}}`；非营业时段可能返回 code=600057 |
| `query-meal-detail` | storeCode, orderType, beType, code | `data {code, name, rounds[], modification?, supportModify}`；`rounds[] {id, name, quantity, minQuantity, maxQuantity, choices[] {code, name, isDefault, diffPrice("+ ¥0"), supportModify, modification?}}` |
| `list-nutrition-foods` | 无 | `data` 为字符串：首行 `[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:`，其后每行逗号分隔 |
| `calculate-price` | storeCode, orderType, beType | items[] 见 3.3；金额为分 |
| `create-order` | storeCode, orderType, beType, items | 到店需 takeWayCode；外送需 addressId，可带 remark(≤50 字) |
| `query-order` | orderId | 订单详情，用于核验特制 |
| `cancel-order` | orderId, cancelReasonCode(字符串，"1"=改主意了) | |

### 3.3 下单 items 结构与特制 key 规则

```json
{
  "productCode": "9900016057",
  "quantity": 1,
  "modification": {"values": [{"code": "...", "key": "...", "quantity": 1}]},
  "roundList": [
    {"round": "1", "comboItemList": [
      {"code": "1000", "quantity": 1,
       "modification": {"values": [
         {"code": "100202", "key": "0-0", "quantity": 0},
         {"code": "100212", "key": "0-0", "quantity": 0},
         {"code": "100214", "key": "0-0", "quantity": 0},
         {"code": "102230", "key": "0-0", "quantity": 0}
       ]}}
    ]},
    {"round": "3", "comboItemList": [{"code": "4437", "quantity": 1}]}
  ]
}
```

**官方 key 规则（tools/list 原文）**：对包含 `unselectedKey` 的特调组，**组内所有特调项都必须传入**；保留的项 `key=selectedKey`，去掉的项 `key=unselectedKey`。`quantity`：保留项取 `selectedQuantity`，去掉项取 0。特制 code 只能取自 `query-meal-detail`，**禁止凭空构造**。`calculate-price` 不回显特制，是否生效以 `query-order` 为准（待闭环实测确认，见 8.3）。

### 3.4 实测样例（上海黄浦华旭国际大厦餐厅 1450713，午餐预约时段）

- 菜单 86 个餐品，14 个分类，含"开心乐园"分类：汉堡开心乐园餐 9900016057、麦乐鸡开心乐园餐 9900016056、鱼排堡开心乐园餐 9900016058
- 汉堡开心乐园餐 rounds：①汉堡包(1000，可特制：酸黄瓜/洋葱粒/番茄酱/芥末酱) ②迷你薯条(504643，不可换不可特制) ③小食：小杯玉米杯 4437 / 苹果片 6102 ④饮料：纯牛奶 3755(默认) / 纯悦 3757 / 100%苹果汁 6362 ⑤玩具
- 双层吉士汉堡 1120 特制组：吉士 / 酸黄瓜 / 洋葱粒 / 番茄酱 / 芥末酱
- 营养（mg 钠）：吉士汉堡包 673、汉堡包 492、儿童鱼排堡 442、麦乐鸡 4 块 337、迷你薯条 61、纯牛奶(盒装) 73、小杯玉米杯 1、苹果片 0、100%苹果汁 0

## 4. 年龄规则（依据与常量）

依据：中国营养学会团体标准《家庭减盐行为指南》T/CNSS 022-2023；《中国居民膳食指南（2022）》7-24 月龄婴幼儿平衡膳食宝塔。1g 食盐 ≈ 393mg 钠。

| 月龄 | 每日食盐上限 | 每日钠上限(mg) | 单餐预算(默认 1/3) |
|---|---|---|---|
| < 12 | 不额外加盐 | - | **不推荐外食，直接返回建议** |
| 12-23 | 1.5g | 590 | 197 |
| 24-47 | 2g | 786 | 262 |
| 48-83 | 3g | 1179 | 393 |
| 84-131 | 4g | 1572 | 524 |
| ≥ 132 | 5g | 1965 | 655 |

- 单餐占比可通过 `--meal-share` 调整（0.2-0.5）
- 档位常量集中在 `age_rules.py`，附出处注释

### 4.1 餐品适配规则（按名称关键词，规则表可扩展）

| 类别 | 关键词 | 处理 |
|---|---|---|
| 排除（全年龄） | 咖啡、拿铁、美式、摩卡、麦咖啡、可乐、雪碧、芬达、汽水、气泡、麦辣、香辣、劲辣、麻辣、辣 | 不进入宝宝候选 |
| 排除（< 36 月龄） | 冰淇淋、新地、麦旋风、圆筒、派、奶昔、果汁（以牛奶 / 水优先）、粥（钠高） | 不进入宝宝候选 |
| 优先 | 玉米杯、苹果片、纯牛奶、牛奶、纯悦（水） | 加分 |
| 主食蛋白候选 | 汉堡包、吉士汉堡、儿童鱼排堡、麦香鱼、麦乐鸡、板烧鸡腿堡、开心乐园餐；早餐时段：麦满分 | 按钠和年龄算份量；"套餐 / 件套 / 单人餐"等组合不作为单点候选 |

- **过敏原**：官方未提供过敏原数据。按名称做"可能含"提示（鱼→鱼类；吉士 / 芝士 / 牛奶→乳制品；蛋→蛋类；堡 / 面包 / 派 / 麦满分 / 卷 / 麦乐鸡 / 鸡块→小麦麸质），并提示以门店为准。用户 `--allergy 鱼,蛋` 时排除命中项
- **质地 / 防噎提示**（< 48 月龄，依据美国 CDC 幼儿防噎指南：整粒玉米、硬的生水果块属于噎食风险，切小、压碎可降低风险）：配菜份量备注改为"整份，压碎后再给（整粒玉米有噎食风险）""整份，切成细丝或刮泥再给（生苹果较硬）"；温馨提示写明整粒玉米压碎、生苹果切细丝或刮泥、肉类撕成小块、全程看护。此规则由真实 Agent（Codex）验收时发现并补充

### 4.2 去料语义（customize）

去掉：名称含 酱、吉士、芝士、奶酪、酸黄瓜、洋葱、芥末、番茄酱、沙拉酱、蛋黄酱、黑椒、胡椒、辣、培根。
保留：生菜、番茄片、鸡蛋、肉饼及其他未命中项。
≥ 48 月龄时保留吉士（可通过 `--keep` 覆盖）。命中不到任何可去项时，在输出中如实说明"该餐品线上无可去配料"。

### 4.3 搭配替换（rounds）

- 饮料轮：优先 纯牛奶 > 牛奶 > 纯悦(水) > 苹果汁（仅 ≥ 36 月龄）；不选碳酸、咖啡
- 小食轮：优先 玉米杯 > 苹果片
- 薯条轮：若有非薯条选项则替换；只有薯条时保留，并在话术卡中加入"薯条不加盐"，在份量建议中写"薯条大人吃 / 宝宝少量尝"
- 玩具等无关轮：取默认

## 5. 组合与份量（planner）

输入：门店菜单 + 营养表 + 年龄档位 + 过敏原。输出 1 个主推方案 + 最多 2 个备选。

1. 将菜单餐品与营养表按名称归一化匹配（去空格、括号、"（盒装）"等后缀；套餐按 rounds 内单品匹配）。匹配不上的标注"无官方营养数据"，**不估算**
2. 先选配菜饮品（4.1 的"优先"项），其钠从单餐预算中扣除，得到主食可用预算
3. 主食蛋白份量 `portion = min(1, 主食可用预算 / 单品钠)`，按 1、3/4、1/2、1/3、1/4 向下取到最近档位；低于 1/4 则不推荐该单品
4. 排序分数 = 钠余量比例（1 - 宝宝钠 / 单餐预算）+ 开心乐园餐加 2 分 + 0.05 ×（线上去掉的配料数 + 请店员帮忙的诉求数）- 无营养数据子项数 - 0.1 × 可能过敏原类别数；即优先开心乐园餐（家长熟悉、搭配已含玉米杯 / 苹果片 / 牛奶），其次是能去料、能减盐的组合（实际钠低于官方整份数值），再看钠余量与过敏原
5. 结果给出：每项官方钠、建议份量、本餐宝宝钠估算（按份量折算，标注"不高于"）、占单餐预算百分比、占全天上限百分比

## 6. 输出

- **终端 Markdown**（默认）：门店、宝宝定制单（含已线上去掉的配料、已替换搭配）、份量与钠预算表、大人餐、话术卡、温馨提示、免责
- **`--json`**：结构化结果（供 Agent 与 `order` 子命令使用）
- **`--card out.html`**：单文件 HTML 卡片（内联 CSS，可截图分享）
- **话术卡文案**（到店）："您好，这份是给 {N} 岁宝宝的。线上已经去掉了 {去料列表}。如果方便的话：肉饼麻烦不撒盐、薯条不加盐。做不到也没关系，谢谢您！"；没有去料时省略"线上已经去掉"一句，既无去料也无诉求时写"按正常出餐即可"
- **钠的写法**：子项有去料时写"≤x mg"（官方为默认配方数值），未改动的子项写确定值；合计在有去料或减盐诉求时写"≤"，否则写"约"
- **外送备注**（≤50 字）："宝宝餐：肉饼请勿撒盐，薯条不加盐，谢谢"
- **温馨提示**：偶尔吃；先尝温度和咸淡；撕小块；搭配水果和白水
- 文案禁止：与其他品牌比较；贬低麦当劳；"健康""营养均衡"等绝对化承诺

## 7. CLI

```
python3 -m babybite plan   --age-months 18 [--kids 1] [--adults 2] [--scene pickup|drive|delivery]
                           (--city 上海市 --keyword 人民广场 | --store 1450713)
                           [--when "2026-10-12 11:30"] [--allergy 鱼,蛋] [--meal-share 0.33]
                           [--json] [--card out.html] [--save plan.json] [--offline]
python3 -m babybite stores --city 上海市 --keyword 人民广场 [--scene pickup|drive] [--offline]
python3 -m babybite order  --plan plan.json --confirm      # 先 calculate-price 展示金额，再 create-order
python3 -m babybite verify --order-id <id>                 # query-order，比对特制是否生效
python3 -m babybite cancel --order-id <id> [--reason 1]
```

- Token：仅从环境变量 `MCD_MCP_TOKEN` 读取；缺失时提示申请地址；任何输出和异常信息中 Token 一律打码
- `--offline`：使用 `fixtures/real/` 回放，不需要 Token
- `order` 没有 `--confirm` 时只算价不下单；`create-order` 失败**不自动重试**

## 8. 错误处理与测试

### 8.1 错误处理

| 情况 | 处理 |
|---|---|
| HTTP 401 | 提示 Token 无效或过期，给申请地址 |
| HTTP 429 | 指数退避重试最多 3 次（create-order 除外） |
| 业务 code ≠ 200 | 抛出带 code/message 的业务异常；600057 提示"门店不在营业时间，可用 --when 预约" |
| 网络超时 | 读取类重试 2 次；写操作不重试，提示到官方 App 核对 |
| 营养匹配失败 | 标注"无官方营养数据"，不进入钠计算的主推 |
| < 12 月龄 | 不调用接口，直接返回喂养建议与出处 |

### 8.2 测试

- `unittest`，零依赖；`python3 -m unittest discover -s tests`
- 覆盖：mcp_client（本地 http.server 假服务：JSON 与 SSE 两种响应、401、429、业务错误、Token 打码）、nutrition 解析与匹配、age_rules 边界、customize（key 规则：组内全传）、planner（份量档位、预算、过敏原排除）、cards（备注 ≤50 字、禁用词）、CLI 离线端到端黄金输出
- 合规自检测试：必备文件存在；`CONTEST_DECLARATION.md` 与官方原文逐字一致；仓库内无 32 位 Token 样式字符串；`mcp-config.example.json` 只含 `${...}` 占位符

### 8.3 真实验收

1. `scripts/smoke_real.py`：真实只读链路（门店 → 菜单 → 营养 → 详情 → 算价）全部成功
2. 真实闭环（**需用户单独同意**）：`order --confirm` 下单汉堡开心乐园餐（宝宝定制）→ `verify` 核验特制 → `cancel`
3. 用真实数据重录 `fixtures/real/`、生成 `examples/`

## 9. 分期

- **P0（MVP）**：到店自提 + 得来速；plan / stores / order / verify / cancel；离线模式；必备文档；测试
- **P1**：麦乐送（`delivery-query-addresses` 选择已有地址，不新建地址）+ 备注；HTML 卡片；GitHub Pages 演示页
- **P2（时间允许）**：高德 MCP（步行距离 / 天气推荐场景）；小红书打卡文案草稿（只生成文本，不自动发布）

## 10. 安全与合规

- 仓库位于 `mc/mcd-baby-bite/` 子目录，与上级目录中的小红书 `cookies.json` 隔离
- 录制数据只含门店公开商业信息、菜单与营养；订单号、地址、手机号一律不入库
- `CONTEST_DECLARATION.md` 使用官方原文
- 文案遵守活动"内容合规"条款

## 11. 扩展功能（2026-10-12 追加，经真实数据可行性验证）

### 11.1 功能分层

| 层级 | 功能 | 依赖 |
|---|---|---|
| 基础 | 宝宝定制单（去料、份量、钠预算、话术卡）、门店查询、核价、下单、麦乐送备注 | 麦当劳 MCP |
| 高级 | 手机卡片（店员出示卡、年龄速查卡）、打卡照片、中英文教育卡片（可打印）、小红书笔记 | 麦当劳 MCP + 本机浏览器（渲染 PNG/PDF）；发布需小红书 MCP |
| 扩展 | 天气提醒、步行到店、导航链接、饭后遛娃（周边儿童乐园 / 公园） | 高德 MCP（需 `AMAP_MAPS_API_KEY`） |

### 11.2 玩具与亲子活动（`babybite/activities.py`）

- 随餐玩具：开心乐园餐套餐详情中名称含"玩具"的轮次（实测"海绵宝宝×航海王系列玩具"），输出"随餐玩具：{名称}（开心乐园餐附赠，以门店实际发放为准）"
- 亲子活动：`campaign-calendar` 实测返回 JSON：`data.dailyList[].events[].articleDto{title, content}`。按关键词（开心乐园、玩具、儿童、亲子、宝宝、派对、小朋友、孩子、童、读书会、体验营）筛选，按标题去重，最多 3 条；摘要取正文首个非空行，最长 40 字
- 文本清洗：NFKC 归一化（如 𝟗.𝟗 → 9.9），去除表情符号（Unicode 类别 So、补充平面字符）与首尾空白
- 活动日历调用失败不影响主流程（静默跳过）；离线模式使用 `fixtures/real/campaign-calendar.json`
- 输出：Markdown 新增"## 玩具与亲子活动"；JSON 新增 `toy`、`campaigns[{date,title,summary}]`

### 11.3 饭后遛娃（高德，`--play`）

- 仅在配置 `AMAP_MAPS_API_KEY` 的在线模式启用；未配置时提示跳过；离线模式提示"离线演示不包含饭后遛娃推荐"
- 门店坐标：`maps_text_search`（门店名）+ `maps_search_detail`
- 周边搜索：`maps_around_search`，关键词依次为"儿童乐园""公园"，半径 2000 米；按 POI id 去重；只保留类型码以 0805（游乐场）或 11（风景名胜 / 公园）开头的 POI；名称含"-"的子景点（如"人民公园-南极石"）剔除
- 同品牌去重：去掉名称末尾括号内的分店名后相同者只保留第一个（真实数据中"百慕大冒险(人广来福士店)"与"百慕大冒险"会同时出现）
- 两个关键词的结果**交替**取前 4 个候选（保证公园有机会入选），`maps_search_detail` 取坐标、`maps_direction_walking` 算步行（分钟向上取整），按步行时间升序取 3 个
- 多样性：若结果中没有公园而候选中有，则用最近的公园替换结果中的最后一个，再按步行时间排序
- 类型标签：0805 开头为"游乐场"，11 开头为"公园"
- 高德免费 Key 有 QPS 限制（实测连续调用返回 `CUQPS_HAS_EXCEEDED_THE_LIMIT`）：在线客户端外包一层节流（两次调用间隔至少 0.35 秒），遇到该错误退避 1 秒后重试，总共最多尝试 3 次
- 输出：Markdown 新增"## 饭后遛娃（高德，门店周边 2 公里）"，每行"- {名称}（{类型}）：步行约 {分钟} 分钟（{米} 米）"；JSON 新增 `playSpots`

### 11.4 打卡照片与教育卡片

- 吉祥物使用原创形象"小麦芽"（`babybite/assets/mascot.png`，由图像模型生成的原创插画），**不使用麦当劳官方吉祥物与商标**；`--mascot` 允许用户替换为自有授权图片
- 实物图：运行时使用菜单接口返回的官方图片链接（不入库）；无图时用原创食物插画（`babybite/assets/food/*.png`）兜底
- 宝宝照片只在本地合成，不上传

**数据**：`MenuItem` 增加 `image`（菜单 `meals[code].image`），`MealDetail` 增加 `image`（套餐详情 `data.image`），二者默认为 None / ""；`PlanResult.images: dict`（菜单 code → 图片链接）。`plan_to_dict` 的每个方案增加 `image`（套餐图），每个 component 增加 `code` 与 `image`（菜单中有该 code 时）。

**教育卡片（`babybite/learn_cards.py`，命令 `learn`）**
- 词表 `VOCAB`（按顺序匹配，名称包含任一关键词即命中）：

| 关键词 | 中文 | 拼音 | English | 例句 | 插画 |
|---|---|---|---|---|---|
| 鱼 | 鱼 | yú | fish | 小鱼在水里游。 / Fish swim in the water. | fish |
| 麦乐鸡、鸡块 | 鸡块 | jī kuài | chicken nuggets | 鸡块小小的。 / The nuggets are small. | nuggets |
| 麦满分、松饼 | 松饼 | sōng bǐng | muffin | 早上吃松饼。 / I eat a muffin in the morning. | muffin |
| 鸡腿、板烧、鸡 | 鸡肉 | jī ròu | chicken | 鸡肉香香的。 / The chicken smells good. | hamburger |
| 汉堡、堡 | 汉堡 | hàn bǎo | hamburger | 我吃汉堡。 / I eat a hamburger. | hamburger |
| 薯条 | 薯条 | shǔ tiáo | French fries | 我和爸爸分薯条。 / I share fries with Dad. | fries |
| 玉米 | 玉米 | yù mǐ | corn | 玉米黄黄的。 / The corn is yellow. | corn |
| 苹果汁、果汁 | 果汁 | guǒ zhī | juice | 果汁甜甜的。 / The juice is sweet. | apple |
| 苹果 | 苹果 | píng guǒ | apple | 苹果甜甜的。 / The apple is sweet. | apple |
| 牛奶 | 牛奶 | niú nǎi | milk | 我爱喝牛奶。 / I like milk. | milk |
| 纯悦、水 | 水 | shuǐ | water | 我喝水。 / I drink water. | water |

- 取主推方案中非"不计入"的子项，按词表去重；提供 `--photo` 时额外生成"宝宝 / bǎo bao / baby / 这是我！ / This is me!"卡（图为宝宝照片）
- 图片优先级：官方实物图（https 链接）> 原创插画
- 输出：`learn-cards.html`（A4 打印版，每页 2×2 四张，带裁切虚线）、`learn-cards.pdf`（有浏览器时）、单张 `card-NN-<english>.png`（NN 从 01 起；english 转小写、空格换成连字符，如 `card-02-french-fries.png`；1080×1440，有浏览器时）

**打卡照片（`babybite/checkin.py`，命令 `checkin`）**
- 参数：`--plan`、`--photo`（可选，JPG/PNG/WebP/GIF；HEIC 等提示先转换）、`--name`（默认"宝宝"）、`--date`（默认方案预约日期，否则今天）、`--text`（可选一句话）、`--mascot`（可选替换）、`--out`（PNG 路径，同目录写 HTML）
- 版式（1080×1440）：暖色背景与点状 / 彩纸图案，散落半透明的食物插画；标题"{name}的麦麦打卡"；"{日期} · {年龄}"；拍立得样式照片（无照片时以吉祥物为主图）；套餐图与名称；"今天吃了：{宝宝实际吃的子项}"（主食写份量如"汉堡包 1/4 份"，整份配菜饮品只写名称，薯条与玩具不列，用"、"连接）；有去料或减盐诉求时显示"去料减盐 宝宝版"徽章；自定义文案；吉祥物与气泡"偶尔吃，吃得明白！"；页脚"mcd-baby-bite · 非麦当劳官方"
- 照片只在本地渲染，不上传

**渲染**：`snapshot.html_to_pdf(html, pdf, browser=None, timeout=60) -> bool` 使用 `--print-to-pdf` 与 `--no-pdf-header-footer`，与截图共用"文件写出且大小稳定即成功"的轮询逻辑

### 11.5 不做的需求

- 门店儿童游乐设施（滑梯等）：麦当劳 MCP 门店数据与高德 POI 详情均无设施字段（实测），无可靠数据源，不做推断
