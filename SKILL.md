---
name: mcd-baby-bite
description: 带娃吃麦当劳的宝宝餐定制官（小小麦门）。当用户提到带宝宝 / 孩子 / 幼儿（1-6 岁）去麦当劳、宝宝能吃什么、怎么去酱去盐、开心乐园餐怎么点、给店员怎么说、宝宝外卖备注、吃完附近哪里遛娃、生成宝宝麦当劳打卡照片、做中英文识物卡片、把带娃吃麦当劳分享到小红书时使用。基于麦当劳 MCP 门店实时菜单与官方营养数据，自动去掉线上可去的配料，按国标年龄档位算钠预算与份量，生成店员话术卡；可选高德（天气、步行到店、饭后遛娃）与小红书（笔记草稿 / 发布）。
---

# 小小麦门 · 带娃吃麦定制官（mcd-baby-bite）

## 运行方式

本技能自带零依赖的 Python 命令行（Python 3.9+）。**先 `cd` 到本 SKILL.md 所在目录**，再运行 `python3 -m babybite ...`。

环境变量：
- `MCD_MCP_TOKEN`：麦当劳 MCP Token（在 https://open.mcd.cn/mcp 申请）。没有时可加 `--offline` 用真实录制数据演示
- `AMAP_MAPS_API_KEY`（可选）：高德 Key，启用 `--from`（天气、步行到店）与 `--play`（饭后遛娃）
- 本机有 Chrome / Edge / Chromium 时，卡片会同时输出 PNG / PDF

## 按用户意图选择命令

| 用户想要 | 命令 |
|---|---|
| 宝宝该怎么点、份量多少 | `python3 -m babybite plan --age-months <月龄> --city <城市> --keyword <地点> [--when "YYYY-MM-DD HH:mm"] [--adults N] [--kids N] [--allergy 鱼,奶,蛋,麸质]` |
| 得来速 / 外卖 | `--scene drive`；外卖先 `python3 -m babybite addresses`，再 `plan --scene delivery --address-id <ID>`（外卖备注自动写"牛肉饼不撒盐，薯条不加盐"） |
| 给店员看的卡片、按年龄速查卡 | `plan ... --phone-card cards/` |
| 天气、走过去多久 | `plan ... --from <出发地>` |
| 吃完去哪遛娃 | `plan ... --play` |
| 保存方案，后续下单 / 打卡 / 学习卡 / 分享 | `plan ... --save plan.json` |
| 下单 | 先 `python3 -m babybite order --plan plan.json`（只算价），**用户明确同意后**再加 `--confirm` |
| 打卡纪念照 | `python3 -m babybite checkin --plan plan.json [--photo 宝宝照片.jpg] [--name 小名] [--text 一句话] --out checkin.png` |
| 中英文识物卡（可打印） | `python3 -m babybite learn --plan plan.json [--photo 宝宝照片.jpg] --out learn-cards/` |
| 小红书笔记 | `python3 -m babybite share --plan plan.json --images <图片...>`；**用户明确同意后**再加 `--publish --confirm` |

把命令输出原样展示给用户；有图片输出时告诉用户文件路径。12 月龄以下不推荐外食，命令会直接给出喂养建议。

## 无法运行命令时：直接调用麦当劳 MCP 工具

1. `query-nearby-stores`（beType=1 到店 / 5 得来速，searchType=2，city + keyword）选营业中或可预约门店
2. `query-meals`（storeCode, orderType=1, beType=1；预约时带 reservationDate，全链路一致），优先"开心乐园"分类
3. `list-nutrition-foods` 取钠；名称去掉括号内容、"一袋"、连字符后匹配；"鱼排堡"对应"儿童鱼排堡"
4. `query-meal-detail`：饮料选纯牛奶（乳制品过敏选纯悦），小食选玉米杯 / 苹果片；开关型特制组（每项都有 unselectedKey）去掉含 酱 / 吉士 / 芝士 / 酸黄瓜 / 洋葱 / 芥末 / 黑椒 / 辣 / 培根 的项（≥48 月龄保留吉士）
5. 特制入参：组内只要去掉一项就整组传入；去掉的 `key=unselectedKey, quantity=0`，保留的 `key=selectedKey, quantity=selectedQuantity`；特制 code 只能取自 query-meal-detail
6. 份量：单餐钠预算 = 每日食盐上限 × 393 ÷ 3（1-2 岁 1.5g、2-3 岁 2g、4-6 岁 3g、7-10 岁 4g、11 岁以上 5g）；配菜饮品整份计入，剩余预算给主食，按 1、3/4、1/2、1/3、1/4 份向下取；薯条建议大人吃
7. `calculate-price` 核价（金额单位为分）；`campaign-calendar` 可查亲子活动

## 红线

- **未经用户明确同意，绝不调用 `create-order`、`cancel-order` 或发布小红书**；先展示门店、餐品、去料、金额
- 只用官方营养数据；匹配不到就写"无官方营养数据"，不估算；去料后的钠写"不高于"
- "不撒盐 / 不加盐"线上无法下单，只能请店员帮忙，门店可能做不到
- 不使用麦当劳官方吉祥物与商标生成图片；宝宝照片只在本地合成
- 不与其他品牌比较，不贬低麦当劳，不做"健康 / 营养均衡"等绝对化表述；提醒"偶尔吃"
- 不构成医疗或营养建议；过敏原仅为按名称的提示

## 依据

- 中国营养学会《家庭减盐行为指南》T/CNSS 022-2023
- 《中国居民膳食指南（2022）》7～24 月龄婴幼儿平衡膳食宝塔
