# HomeAtlas — 开发计划与验证清单（Handoff）

## 1. Context（背景与目标）

家庭物品管理工具。需求方（你）和配偶各自使用一个 **Hermes Agent**（Nous Research 出品的自托管 AI Agent，支持 MCP），共享**同一个 PostgreSQL** 数据库来管理家里的东西：用自然语言"把护照放进保险柜抽屉""护照在哪？""哪些药快过期"。

本项目**带学习/探索性质**：刻意把三套范式落地——Palantir **Ontology**（语义数据层）、Palantir **AIP**（在 Ontology 上搭 AI 的规范）、**Pydantic AI** 多 Agent 编排（用领域子 Agent 隔离 MCP 工具）。需求方为编程爱好者，代码要可读、概念要清晰。

**交付方式：一次性交付完整系统（"一起上"）**——不做分阶段发布。下面第 10 节是内部构建顺序（仍需有序实现 + 单测），第 11 节是最终端到端验证清单。

## 2. 已确认的需求（recap）

| 项 | 结论 |
|---|---|
| 用户 | 你 + 配偶，各自一个 Hermes Agent |
| 部署 | 两台**不同的 Mac mini**（同一局域网）；其中一台当"家庭服务器"跑 Postgres + HomeAtlas 服务 |
| 数据库 | 自建 **PostgreSQL**（共享） |
| 物品范围 | 食品/药品、保险单/信用卡/会员卡、工具/电器 → 3 个领域 |
| 敏感信息 | **只存引用信息**；信用卡绝不存完整卡号（仅发卡行/类型/后四位/到期/实体位置） |
| 身份/审计 | 每台 Mac mini 一个 token → 服务端认人；自动记 `added_by/updated_by` + 变更流水 |
| 语言/栈 | Python；Pydantic AI；官方 MCP SDK（FastMCP，HTTP）；PostgreSQL + SQLModel |
| 编排 | orchestrator + 3 个领域子 Agent，按前缀隔离工具（"一起上"，第一天就带编排层） |

## 3. 总体架构

```
你的 Mac mini                              配偶的 Mac mini
  └ Hermes Agent (token A = 你)              └ Hermes Agent (token B = 配偶)
        \                                        /
         \___ 局域网 HTTP(MCP) + 各自 Bearer token ___/
                          │  (服务端凭 token 认人 → actor)
        ┌─────────────────▼──────────── 家庭服务器 Mac mini ───────────────┐
        │  HomeAtlas 服务（单一 Python 进程）                              │
        │                                                                  │
        │  ⑤ 对外 MCP 接口：单个委派工具 home_atlas(request)              │ ← Hermes 眼里只有 1 个工具
        │  ④ Pydantic AI orchestrator ──路由──▶ 3 个领域子 Agent           │
        │        · 每个子 Agent 只挂自己领域的工具集（前缀隔离）          │
        │  ③ 领域工具集：perishable_* / card_* / equipment_*               │
        │        · 工具 = 对 Ontology Action/Function 的封装               │
        │  ② Ontology 核心：Object / Link / Action / Function              │
        │        · Action = 唯一写入口（校验 + 盖 actor + 写 Event 流水）  │
        │  ① PostgreSQL（共享数据）                                        │
        └──────────────────────────────────────────────────────────────────┘
```

**为什么对外只暴露 1 个工具**：领域工具增多会占 Hermes 上下文并降低命中率（实测 34 工具≈22k tokens≈半个上下文；大目录致"决策瘫痪"）。把整套 HomeAtlas 收敛成 `home_atlas(request)` 一个工具，Hermes 上下文开销**恒定**；难选择被拆成"orchestrator 选领域(3 选 1) → 子 Agent 选工具(少量里选)"两个简单步骤。

## 4. 技术栈

- Python 3.12+，包管理 **uv**
- **Pydantic AI**（orchestrator + 子 Agent 编排）
- 官方 **`mcp` SDK / FastMCP**（对外 Streamable HTTP MCP 服务）
- **PostgreSQL 16** + **SQLModel**（对象类型即模型，SQLAlchemy+Pydantic 二合一）+ **Alembic**（迁移）+ **asyncpg**（驱动）
- 配置 **pydantic-settings** + `.env`；测试 **pytest** + **pytest-asyncio**
- LLM provider：默认 **DeepSeek**（Pydantic AI 原生 provider），模型值放在 `.env` 的 `HOME_ATLAS_LLM_MODEL`

## 5. 数据模型（Ontology：Object / Link / Action / Function）

**Object Types（SQLModel 表）**
- `Person`：id, name（你/配偶）, created_at（token→person 在配置里映射）
- `Location`：id, name（"主卧衣柜""保险柜抽屉"）, parent_id（可空，房间→容器嵌套）, notes
- `Item`：id, name, kind（枚举：food/medicine/insurance_policy/payment_card/membership_card/tool/appliance/other）, domain（由 kind 派生：perishable/card_doc/equipment/other）, location_id(FK), quantity, unit, expiry_date, renewal_date, purchase_date, **properties(JSONB，按 kind 存专属字段)**, notes, added_by(FK Person), updated_by(FK Person), created_at, updated_at, archived(bool)
- `Event`（审计流水）：id, item_id, actor_id(FK Person), action（枚举）, summary, before(JSONB), after(JSONB), created_at

**Link Types（语义上是链接，物理上用外键）**：`Item—stored_in→Location`、`Item—added_by/last_touched_by→Person`、`Location—inside→Location`

**Action Types（唯一写入口；每个都：校验 → 改库 → 写 Event）**
`AddItem` · `MoveItem` · `AdjustQuantity`/`SetQuantity` · `UpdateItem`（改名/备注/日期/保修等）· `UpsertCardReference`（强制无完整卡号）· `DiscardItem`（归档）

**Functions（只读）**
`search_items(query?,kind?,domain?,location?,owner?,expiring_within_days?)` · `get_item(id)` · `where_is(name)` · `list_expiring(within_days)`（含 expiry 与 renewal）· `recent_activity(limit)` · `list_locations()`

## 6. 敏感信息与身份/审计规则

- **信用卡**：`properties` 仅允许 `{issuer, card_type, last4, expiry_my, physical_location}`；校验**拒绝任何 13–19 位连续数字（完整卡号）和 CVV**。
- **会员卡/保险单**：`member_number`/`policy_number` 属低风险引用号，允许明文存（满足"要真用"的场景）。
- **身份**：对外 MCP 用 Bearer token；服务端中间件 `token → Person`，把 `actor` 注入每个 Action（LLM 无法伪造）。这实现 AIP"在调用者身份下执行"。
- **审计**：每个 Action 写一条 `Event`（actor/action/before/after/时间）→ 支撑"上次谁动了护照"。
- **写前确认（AIP 原则）**：破坏性动作（`DiscardItem`、覆盖式更新）需显式 `confirm=true`；子 Agent 被指示先与用户确认再提交。

## 7. Pydantic AI 编排

- **3 个领域子 Agent**，各绑定**唯一**领域工具集（前缀隔离）：
  - `perishables`（food/medicine）：add/move/adjust_quantity/set_expiry/discard + 领域内 search/list_expiring
  - `cards_docs`（insurance/payment/membership）：upsert_card_reference/set_renewal/update/move/discard + 领域内 search/list_expiring(renewal)（强制引用-only）
  - `equipment`（tool/appliance）：add/move/update(warranty/brand/model)/discard + search
- **orchestrator**：解析 NL → 选领域子 Agent（可跨域）→ 汇总结果；透传 `actor`；对写操作执行确认。Pydantic AI **agent delegation**：父 Agent 的工具内调用子 Agent，传递 `ctx.usage`。
- 领域工具集实现为 Pydantic AI toolset（封装第 5 节 Action/Function）。**可选探索变体**：把每个领域做成独立 MCP server，子 Agent 以带前缀的 MCP 客户端消费——更贴近"MCP 无处不在"，但多一层进程，默认不做。

## 8. 对 Hermes 的 MCP 接口与部署

- HomeAtlas 用 FastMCP 暴露 **Streamable HTTP**，对外工具：`home_atlas(request: str)`（委派给 orchestrator）+ 可选只读 `home_atlas_search(...)`。
- 两台 Hermes 各自配置：
  ```yaml
  mcp_servers:
    home_atlas:
      url: "http://<家庭服务器局域网IP>:8080/mcp"
      headers: { Authorization: "Bearer <该机器的token>" }
  ```
  token A→你、token B→配偶。用 `hermes mcp test home_atlas` 验证连通。
- 家庭服务器 Mac mini：Postgres + HomeAtlas 进程常驻（建议 `launchd`/Docker 守护 + `pg_dump` 定时备份）。

## 9. 提醒

`list_expiring(within_days)` + Hermes 自带定时自动化（自然语言排程）：每天/每周让各自 Hermes 播报"本周临期/待续费"。无需自建调度器。

## 10. 开发计划（构建顺序，一次性交付完整系统）

> "一起上"＝最终一次交付完整塔；以下为有序构建步骤，每步带 verify，整合后做第 11 节端到端验证。

1. **脚手架与基础设施** → verify：`uv sync` 通过；Postgres 连通；`alembic upgrade head` 建表成功；`pytest` 空跑通过。
2. **Ontology 核心**（第 5 节 Object/Link/Action/Function + 第 6 节校验/审计） → verify：每个 Action 的单测（正常 + 校验失败）；写后产生正确 `actor` 的 `Event`；信用卡完整卡号被拒。
3. **领域工具集 + 3 个子 Agent + orchestrator**（第 7 节） → verify：领域请求路由到正确子 Agent；断言每个子 Agent 仅持有本域工具；跨域请求正确拆分。
4. **对外 MCP 服务 + 身份中间件**（第 8 节） → verify：MCP 连通；分别用 token A/B 调用，`Event.actor` 正确；非法 token 被拒。
5. **两台 Hermes 接入** → verify：从你这台说"把护照放进保险柜抽屉"落库；从配偶那台问"护照在哪？"答得出（共享数据）；"上次谁动了护照"显示 actor。
6. **提醒 + 可选只读网页**（第 9 节） → verify：塞入临期样本，跑排程，播报列出它们。
7. **加固** → verify：两写并发不损坏；进程/DB 重启后可恢复；备份可还原。

## 11. 验证清单（最终端到端）

- [ ] **数据库**：`alembic upgrade head` 建出全部表；可回滚。
- [ ] **Action 单测**：Add/Move/AdjustQuantity/Update/UpsertCardReference/Discard 各有正常 + 失败用例全绿。
- [ ] **写入口唯一性**：绕过 Action 直接改库的路径不存在（写操作只经 Action）。
- [ ] **审计**：每次写都生成 `Event`，actor/before/after 正确。
- [ ] **敏感信息**：输入完整信用卡号被拒；信用卡仅留后四位；会员号/保单号可存。
- [ ] **身份**：token A 操作记为"你"、token B 记为"配偶"；无 token / 错 token 被拒（401）。
- [ ] **子 Agent 隔离**：断言 `perishables/cards_docs/equipment` 各自仅持有本域工具；orchestrator 路由正确（含跨域）。
- [ ] **对外只 1 个工具**：Hermes 端工具列表只见 `home_atlas`（+可选只读搜索）。
- [ ] **端到端（双人共享）**：A 机写入 → B 机读到同一数据；"上次谁动了 X"正确。
- [ ] **写前确认**：`DiscardItem` 未确认不执行；确认后执行并留痕。
- [ ] **提醒**：`list_expiring` 正确；Hermes 定时播报命中临期/待续费样本。
- [ ] **并发**：两端同时写不产生脏数据（事务/约束生效）。
- [ ] **韧性与备份**：HomeAtlas/Postgres 重启后正常；`pg_dump` 备份可还原。
- [ ] **交付物**：本文件落地为仓库内 `handoff.md`；`README` 含家庭服务器与两台 Hermes 的配置步骤。

## 12. 我采用的默认假设（可随时推翻）

- LLM provider 默认 **DeepSeek**（Pydantic AI 原生 provider），模型值放在 `.env` 的 `HOME_ATLAS_LLM_MODEL`；orchestrator 与子 Agent 后续可扩展为不同模型。
- 存储用 **SQLModel + Postgres**；对象类型用单表 `Item`+`kind`+`properties(JSONB)`（务实映射多对象类型）。
- 对外只给 `home_atlas(request)` 一个委派工具（+ 可选只读搜索）；领域 MCP-per-server 仅作可选探索。
- 只读网页看板为**可选**（nice-to-have），非必交付。

## 13. 参考资料

- Palantir Ontology：<https://www.palantir.com/docs/foundry/ontology/core-concepts> ・ Action Types：<https://www.palantir.com/docs/foundry/action-types/overview>
- Palantir AIP（Agent 工具）：<https://www.palantir.com/docs/foundry/agent-studio/tools>
- Pydantic AI：多 Agent <https://ai.pydantic.dev/multi-agent-applications/> ・ Toolsets <https://ai.pydantic.dev/toolsets/> ・ MCP Client <https://ai.pydantic.dev/mcp/client/>
- Hermes：MCP 配置 <https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference> ・ Tool Search <https://www.marktechpost.com/2026/05/29/hermes-agent-ships-tool-search-for-mcp-anthropic-evals-show-49-to-74-accuracy-gain-on-opus-4/>
