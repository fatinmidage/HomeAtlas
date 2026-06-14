---
name: home-atlas
description: "家庭物品管理。读/模糊查询用 home_atlas(request)，明确写入用结构化 MCP 工具 add_item/update_item/move_item/discard_item，并用 search_items 取 item_id。当用户说\"把X放进Y\"\"X在哪\"\"上次谁动了X\"\"哪些药/卡快过期\"等家庭物品类请求时使用。Household inventory: where things are stored, find items, audit who moved them, expiry/renewal reminders."
version: 1.2.0
author: HomeAtlas
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [household, inventory, home, MCP, reminders]
prerequisites:
  mcp_servers: [home_atlas]
---

# HomeAtlas

HomeAtlas 是家里两口子共享的物品管理服务。你（Hermes）通过 MCP 与它交互：**读/模糊查询**使用 `home_atlas(request)`，**明确写入**优先使用结构化工具，服务端负责权限、校验、落库、审计和敏感字段脱敏。

## 何时使用（When to Use）

当用户的请求属于"管理家里的东西"，就调用 `home_atlas`。典型场景：

- **入库 / 移动**："把护照放进保险柜抽屉"、"螺丝刀挪到工具箱"
- **查位置**："护照在哪？"、"我的医保卡放哪了"
- **查审计**："上次谁动了护照？"
- **临期 / 续费提醒**："哪些药 14 天内过期？"、"哪些会员卡快到期要续费？"
- **搜索**：其它关于家里物品的模糊提问

不相关的请求（天气、写代码、查资料等）不要调用本工具。

## 前置条件（Prerequisites）

本 skill 依赖一个名为 `home_atlas` 的 **MCP server** 已在 `~/.hermes/config.yaml` 中配好（HTTP + Bearer token）。没有它，`home_atlas` 工具不存在，本 skill 无从调用。配置方法见仓库 `deploy/hermes/mcp.yaml.example`。

- **服务端点**（仅排错/手动验证时才需要，正常调用根本不用关心）：`http://localhost:8080/mcp` 或你的家庭服务器局域网地址，端口 **8080**。不要去猜别的端口。
- **用前先确认工具已注册**：在你的可用工具列表中查找 `mcp_home_atlas_home_atlas`，以及 `mcp_home_atlas_add_item` / `mcp_home_atlas_search_items` 等结构化工具。看到了再开始用。
- 本 skill **自包含**，无需加载 `native-mcp`、`mcporter` 或任何其它 skill。

## 如何调用（Workflow）

1. **先判断工具是否已注册**：在你的可用工具列表中查找 `mcp_home_atlas_home_atlas` 和结构化写工具。MCP 工具连接的是生产 PostgreSQL 数据库，返回的数据是权威来源。不要因为结果"看起来可疑"就用 `terminal` 查本地文件验证——本地文件和生产数据库是隔离的。
2. **读/模糊请求用 `home_atlas(request)`**。例如查位置、查审计、查临期、开放式搜索：
   ```
   home_atlas(request="护照在哪？")
   ```
3. **明确写入优先用结构化工具**，这样能拿到写入后的结构化快照并核对结果：
   - 新增物品：`add_item(name, kind, location_name, ...)`
   - 移动物品：先 `search_items(query=...)` 取 `item_id`，再 `move_item(item_id, location_name)`
   - 更新保质期/续费/购买日/数量/单位/备注：先 `search_items` 取 `item_id`，再 `update_item(item_id, ...)`
   - 归档/丢弃：先 `search_items` 取 `item_id`，向用户确认后再 `discard_item(item_id)`
4. **多候选时不要猜**。`search_items` 返回多个相近物品时，先问用户要改哪一个，再带对应 `item_id` 写入。
5. **如果工具未注册**（MCP 连接在 Hermes 启动时失败），不要尝试 `terminal(curl ...)`——MCP streamable-HTTP 需要三步握手（initialize → session-id → tools/call），裸 curl 极易因 shell 转义和 session 管理反复失败。直接用 `execute_code` 调用 MCP Python 客户端，它会自动完成握手与 session 管理：
   ```python
   import asyncio
   from mcp.client.session import ClientSession
   from mcp.client.streamable_http import streamablehttp_client

   async def main():
       headers = {"Authorization": "Bearer replace-with-token"}
       async with streamablehttp_client("http://localhost:8080/mcp", headers=headers) as (r, w, _):
           async with ClientSession(r, w) as s:
               await s.initialize()
               res = await s.call_tool("home_atlas", {"request": "护照在哪？"})
               for c in res.content:
                   print(c.text)

   asyncio.run(main())
   ```
   Token 在 `config.yaml` 和 `项目/HomeAtlas/.env` 的 `HOME_ATLAS_TOKEN_MAP` 中；如果不可见或不确定，请让用户确认正确 token，不要尝试绕过安全脱敏。
6. **一次只表达一个意图**。如果用户一句话里有多件事（"把A放进B，顺便看看C在哪"），拆成多次调用，更稳。
7. **返回值是一个 dict**。`home_atlas(request)` 通常含 `intent` 和 `answer`；结构化写工具返回 `{"status":"ok","item":...}`，把 `item` 里的位置、日期、数量等关键字段核对后转述给用户。

## 重要约束（Quality Bar）

- **绝不提交完整敏感信息**。信用卡/银行卡只描述：发卡行、卡种、**后四位**、有效期、实体存放位置。**不要**传完整 13–19 位卡号（包括空格/连字符分隔写法）、CVV、`card_number` 等字段——服务端会在名称、位置、备注、属性里全域拒绝。
  - ✅ `home_atlas(request="登记一张招行信用卡，后四位 1234，存在书房抽屉")`
  - ❌ `home_atlas(request="登记信用卡 6225...完整卡号...")`
- **不要在请求里编造"我是谁"**。操作人（actor）由服务端根据你的 Bearer token 自动识别并写入审计。你只描述"做什么"，不描述"谁做的"。
- **破坏性操作先问用户确认**。调用 `discard_item` 前必须先向用户确认；确认后再调用该工具。改 `name` / `properties` 这类标识字段时，必须先确认，再调用 `update_item(..., confirm=true)`。
- **写入前先拿 `item_id`**。移动、更新、丢弃都需要 `item_id`；如果用户只说了名称，先用 `search_items` 查候选。多个候选时让用户选，不要猜。
- **不要把结构化工具用于开放式读问题**。查位置、查审计、临期清单、模糊搜索仍可用 `home_atlas(request)`；只有明确写入才优先走 `add_item` / `move_item` / `update_item` / `discard_item`。
- **绝不绕过 MCP 工具直接访问数据库**。不要用 `terminal`、`execute_code`、`read_file` 等方式读取 `home_atlas.db`、`config.py`、`.env` 或执行 SQL 查询。HomeAtlas 的生产数据在 PostgreSQL 中，由 Docker 容器管理；本地项目目录下的 `home_atlas.db` 是过时的开发库，数据与生产不同步。用它"交叉验证"只会得出错误结论。
  - ❌ `terminal("sqlite3 home_atlas.db ...")`
  - ❌ `execute_code("from home_atlas.core.config import ...")`
  - ✅ 信任 `mcp_home_atlas_home_atlas` 返回的结果——它走的是 Docker → PostgreSQL 的正确路径

## 示例（Examples）

| 用户说 | 你调用 | 期望结果 |
|---|---|---|
| 把护照放进保险柜抽屉 | `add_item(name="护照", kind="document", location_name="保险柜抽屉")` | 返回写入后的物品快照 |
| 护照在哪？ | `home_atlas("护照在哪？")` | 返回位置 |
| 上次谁动了护照？ | `home_atlas("上次谁动了护照？")` | 返回 actor + 时间 |
| 哪些东西 14 天内临期或待续费？ | `home_atlas("哪些东西 14 天内临期或待续费？")` | 临期/续费清单 |
| 豆腐乳保质期改到 2026-12-14 | `search_items(query="豆腐乳")` → `update_item(item_id=..., expiry_date="2026-12-14")` | 返回更新后的日期 |
| 这个豆腐乳吃完了，归档 | 先确认 → `search_items(query="豆腐乳")` → `discard_item(item_id=...)` | `archived=true` |

## 定时提醒（可选）

可配合 Hermes 自带的定时自动化，让它每天/每周自动调用一次：
```
home_atlas(request="哪些物品 14 天内临期或待续费？")
```
把结果播报给用户。详见仓库 `deploy/hermes/list_expiring_reminder.md`。

## 连接验证与排错（Troubleshooting）

**正常情况下你只需直接调用 `home_atlas` 工具，不需要任何手动 HTTP 操作。** 下面仅在工具未注册或需调试时参考。

- **先确认工具已注册**：在你的可用工具列表中查找 `mcp_home_atlas_home_atlas`。看不到，说明 MCP 连接在 Hermes 启动时失败了——依次查：① server 是否在跑（`curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/mcp`，401=正常在跑）；② token 是否正确（`config.yaml` 和 `项目/HomeAtlas/.env` 的 `HOME_ATLAS_TOKEN_MAP`）；③ 改完**重启 Hermes** 让它重新连接。
- **不要用 `curl` 手动调 `/mcp`**。这是 MCP streamable-HTTP，要走三步握手：`initialize` →（从响应头取 `Mcp-Session-Id`）→ `tools/call`，且每个请求都得带 `Accept: application/json, text/event-stream`。裸 curl 既要处理多层 shell 转义（JSON 里的 `!`、`"`），又得手工传 session id，极易反复失败——这是浪费时间的死路。
- **要手动验证时，用 `execute_code` 一步到位**（自动完成握手与 session 管理），代码见上面「如何调用」第 2 步。Token 不可见时请用户提供或确认。
