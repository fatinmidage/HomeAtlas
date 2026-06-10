# HomeAtlas 重构计划 v2 — 安全加固与 Ontology 一致性

> 状态跟踪：完成一个 Phase 就把下表打勾。**未打勾 = 未开始**。
>
> | Phase | 主题 | 优先级 | 状态 |
> |-------|------|--------|------|
> | R1 | 安全堵漏（REST 认证 / RBAC / 敏感数据护栏） | 🔴 高危 | ☐ |
> | R2 | 统一 Action Dispatcher，让 Registry 元数据真正生效 | 🟠 高 | ☐ |
> | R3 | 审计与副作用正确性（post-commit 派发 / version 并发） | 🟠 中 | ☐ |
> | R4 | 本体一致性（命名空间统一 / 单一事实源 / 双向 Link） | 🟡 中 | ☐ |
> | R5 | AI 与读函数全面成为 Registry 投影 | 🟡 中 | ☐ |
> | R6 | 清尾与文档对齐 | ⚪ 低 | ☐ |

## Context

2026-06 架构审计结论：项目对 Palantir Ontology/AIP 的骨架复刻成功（集中式 Registry、
Action 唯一写入口、审计 Event、MCP 端服务端身份解析），但存在两类问题：

1. **安全缺口**：REST API 无认证且 `actor_id` 由客户端自报；所有 Person 默认 `admin`
   角色使 RBAC 失效；完整卡号扫描只覆盖 `payment_card` 的 properties，`notes` 字段和
   其他 kind 可绕过。
2. **声明-执行脱节**：Registry 里声明的 `requires_confirm`、`parameters`、`secret`、
   `post_hooks` 没有任何执行层消费；Link 端点用表名而 Object Type 用 kind 名，两套命名
   空间不相交；`PropertyDef` 与 Pydantic schema 双重事实源且已漂移
   （`warranty_expiry`: date vs str）；AI 工具仍手写硬编码。

上一轮重构文档（`docs/ontology-aip-refactoring-plan.md`，Phase 0–5）已实施完成并删除。
其唯一未完成部分（Phase 3 的 AI toolset Registry 化）并入本计划 R5。

## 全局规则（每个 Phase 强制）

1. **接口不变**：对外 MCP 工具 `home_atlas(request)` 与 `ontology_describe` 的签名和
   行为契约不变。
2. **测试全绿才算完成**：每个 Phase 结束必须 `uv run pytest` 全量通过，不允许跳过或
   删除既有用例来换取通过。
3. **每 Phase 一个独立 commit**：格式 `refactor(R<n>): <summary>`，必须可独立回滚；
   涉及 DB 迁移的 Phase，迁移脚本与代码在同一个 commit。
4. **新行为必须有新测试**：修缺陷先写能复现缺陷的失败测试，再修复。
5. **顺序执行**：R1 → R6 按编号推进，前一个 Phase 的 commit 是后一个的起点。
6. **完成后更新本文档**：勾选状态表，并在 Phase 末尾追加一行实际 commit hash。

---

## Phase R1 — 安全堵漏（高危，最先做）

**目标**：消除三个高危缺口，使「actor 不可伪造、权限有实效、敏感数据进不来」在所有
入口成立，而不只是 MCP 入口。

### R1.1 REST API 认证

- `rest_api.py`：增加 FastAPI 依赖项，校验 `Authorization: Bearer <token>` 并复用
  `security.resolve_actor_id()` 在服务端解析 actor（与 MCP 入口同一套 token_map）。
- 从 `ActionRequest` 中**删除** `actor_id` 字段——actor 只能来自 token，不能来自请求体。
- 无 token / 无效 token 返回 401。

### R1.2 敏感数据护栏全域化

- `security.py`：新增 `scan_sensitive_text(values)`——对完整卡号正则（13–19 位连续
  数字）和 CVV 键名做扫描，适用于**任意 kind**。
- `actions.py`：`add_item` / `update_item` / `upsert_card_reference` 对 `name`、
  `notes`、以及 `properties` 的全部字符串值调用该扫描；现有
  `reject_payment_card_secrets` 保留为 payment_card 的更严格护栏。

### R1.3 RBAC 实效化

- `models.py` + 迁移 `0006`：`Person.roles` 默认值改为 `["member"]`（含
  `server_default` 修正）。已存在的数据行保持原值，由部署者显式调整。
- 新增 `SetPersonRole` Action：注册进 Registry（`required_role="admin"`），走标准
  Action 流程并写审计 Event——角色变更本身必须可追溯。
- Bootstrap：新增 `HOME_ATLAS_ADMINS` 环境变量（人名列表），`seed_people_from_tokens`
  时据此赋予 admin，解决「第一个 admin 从哪来」的问题。

### ✅ 验证目标（全部写成自动化断言）

| # | 断言 |
|---|------|
| 1 | 无 token 的 REST 写请求返回 401；带合法 token 的写入，审计 `Event.actor_id` 与 token 对应的人一致 |
| 2 | 请求体伪造他人身份不可能（`actor_id` 字段已不存在，传入被忽略/拒绝） |
| 3 | 任意 kind 的 `notes` 或 `properties` 含 16 位卡号 → `HomeAtlasError` 拒绝 |
| 4 | `kind=other` 携带 `card_number` 属性 → 拒绝 |
| 5 | member 角色调用 `UpdateItem` / `DiscardItem` → 权限错误；admin 成功 |
| 6 | `SetPersonRole` 成功后产生一条审计 Event，且只有 admin 能调用 |

**新增/修改测试**：`tests/test_rest_api.py`（认证用例）、`tests/test_actions.py`
（护栏用例）、`tests/test_rbac.py`（默认角色 + SetPersonRole）。

**完成标准**：`uv run pytest` 全绿 → `alembic upgrade head` 可执行 →
commit `refactor(R1): close REST auth, RBAC, and sensitive-data gaps`。

---

## Phase R2 — 统一 Action Dispatcher（声明即生效）

**目标**：建立单一调用通道，让 Registry 中声明的元数据成为唯一权威。Palantir 的核心
理念是「元数据驱动执行」，本 Phase 是整个计划的枢纽。

### 改动

- 新建 `home_atlas/dispatcher.py`：
  `dispatch_action(session, actor_id, api_name, params, confirm=False)`，统一流程：
  1. Registry 查 `ActionTypeDef`，未注册即报错；
  2. 按 `ActionParameterDef` 校验参数（缺必填、未知参数、类型不符均拒绝）；
  3. 按 `required_role` 做权限检查（从各 action 实现中移除分散的
     `check_action_permission` 调用，收口到 dispatcher）；
  4. 按 `requires_confirm` 统一执行 confirm 检查（**行为变化**：`UpdateItem` 原本只对
     name/properties 改动要求 confirm，统一后任何 UpdateItem 都要求——以 Registry 声明
     为准）；
  5. `resolve_action()` 调用实现函数。
- `rest_api.py`：删除手写 `_ACTION_DISPATCH` lambda 表，全部 Action 经 dispatcher
  自动暴露（7/7 可调，消除「返回 200 但未实现」的假成功响应）。
- `toolsets.py` 与 `orchestrator.py` 的写路径改走 dispatcher。
- **决策 A — `secret` 标志**：让它生效——为 `document_number`、`policy_number`、
  `member_id` 标记 `secret=True`，`_item_dict` 序列化时打码（如 `****1234`），
  `describe_for_llm` 标注 secret。若评估后认为家庭场景不需要，则删除该字段——
  二选一，不允许继续「声明了不生效」。
- **决策 B — `post_hooks` / `resolve_hooks`**：与 EventBus 是冗余的两套钩子机制。
  保留 EventBus（R3 修其时序），**删除** `ActionTypeDef.post_hooks` 与
  `resolve_hooks()` 死代码。

### ✅ 验证目标

| # | 断言 |
|---|------|
| 1 | 缺必填参数 / 传未知参数 / 类型不符 → 统一报错且错误信息包含参数名 |
| 2 | `requires_confirm=True` 的 Action 不带 `confirm=True` → 拒绝（UpdateItem、DiscardItem 行为一致） |
| 3 | member 经 dispatcher 调 admin 级 Action → 权限错误（与 R1 直调行为一致） |
| 4 | REST 上 7 个 Action 全部可成功调用；未注册的 action 名返回 404 |
| 5 | 元测试：Registry 中每个 `ActionTypeDef.implementation` 可 resolve，且声明参数是实现函数签名的子集 |
| 6 | `secret` 属性在读输出中已打码（若走决策 A） |

**新增测试**：`tests/test_dispatcher.py`；`tests/test_rest_api.py` 扩展。

**完成标准**：`uv run pytest` 全绿 →
commit `refactor(R2): central action dispatcher driven by registry metadata`。

---

## Phase R3 — 审计与副作用正确性

**目标**：副作用严格发生在事务提交之后；审计 version 在并发下唯一。

### 改动

- EventBus 派发时机：`actions._event()` 不再直接 `dispatch()`，改为把事件挂到
  session 的 pending 列表，**commit 成功后**统一派发（实现位置建议在 dispatcher 包裹
  commit 的层面，R2 已提供该收口点）。
- version 并发安全：PostgreSQL 下计算 `_next_version` 前对 item 行
  `SELECT ... FOR UPDATE`；并为 `event(item_id, version)` 加部分唯一索引
  （迁移 `0007`）作为最后防线。

### ✅ 验证目标

| # | 断言 |
|---|------|
| 1 | commit 失败（测试中注入异常）时，EventBus handler **不被调用** |
| 2 | commit 成功后 handler 收到的快照与数据库已提交状态一致 |
| 3 | PostgreSQL 集成测试：多线程并发写同一 item，version 严格递增、无重复（扩展 `tests/test_postgres_integration.py`，现有用例只写不同 item，测不出竞态） |

**完成标准**：`uv run pytest` 全绿 + 集成测试（有 Postgres 时）通过 →
commit `refactor(R3): post-commit event dispatch and concurrency-safe versions`。

---

## Phase R4 — 本体一致性

**目标**：Registry 成为自洽、可自校验的单一事实源——Palantir 中「一切皆 Object Type、
Link 连接注册类型、属性只有一份定义」。

### 改动

- **注册全部实体**：`ObjectTypeDef` 泛化（`item_kind` 可为 `None`，新增 `table` 字段），
  把 `Person`、`Location`、`Event` 注册为一等 Object Type；`Item` 注册为 interface/
  基类型，9 个 kind 类型声明其 parent。
- **Registry 构建期自检**：`build_registry()` 校验每个 `LinkTypeDef` 的
  source/target 是已注册的 Object Type、`fk_column` 真实存在于对应 SQLModel——
  不一致则 import 即失败。
- **单一属性事实源**：用 `pydantic.create_model` 从 `PropertyDef` 动态生成校验模型，
  删除 `property_schemas.py` 中的手写类（PaymentCard 的 `extra="forbid"` 与 last4
  校验作为特例注入）；修复 `warranty_expiry` 的 date/str 漂移。
- **双向 Link**：`LinkTypeDef` 增加 `inverse_name`（如 `storedAt` ↔ `itemsStored`），
  `traverse_link` / `shortest_path` 支持反向遍历。

### ✅ 验证目标

| # | 断言 |
|---|------|
| 1 | 故意注册一个端点未注册的 Link → `build_registry()` 抛错（负面测试） |
| 2 | `ontology_describe` 输出包含 Person / Location / Event |
| 3 | `warranty_expiry` 接受 `date` 类型并正确序列化（漂移已修） |
| 4 | 删除手写 schema 后，`tests/test_property_schemas.py` 既有用例全部仍通过（行为不变证明） |
| 5 | `auto_traverse(Location, id, Item)` 能回答「位置 X 里有哪些物品」 |

**完成标准**：`uv run pytest` 全绿 →
commit `refactor(R4): unify ontology namespace, single property source, bidirectional links`。

---

## Phase R5 — AI 与读函数全面成为 Registry 投影

**目标**：兑现旧计划 Phase 3/4 的承诺——新增 Object Type / Action Type 后，AI Agent
与 REST 无需改代码即自动获得能力。

### 改动

- `agents.py`：实现 `_build_ai_toolset_for_domain(domain)`，从 `ActionTypeDef` 生成
  Pydantic AI 工具（docstring、参数、默认 kind 来自声明），**删除**三个手写的
  `_*_ai_toolset()`。
- **读函数注册**：Registry 新增 `FunctionDef(api_name, parameters, implementation,
  description)`，把 `search_items` / `where_is` / `list_expiring` /
  `recent_activity` / `last_touched` 注册进去；orchestrator 的 `atlas_*` 工具与
  REST 读端点从 `FunctionDef` 生成。
- 读路径权限：`viewer` 角色获得读语义（Function 默认 `required_role="viewer"`）。

### ✅ 验证目标

| # | 断言 |
|---|------|
| 1 | 回归：生成的 AI 工具名集合与删除前的手写工具名集合一致 |
| 2 | 演练测试：测试内临时注册 `ItemKind.CLEANING_SUPPLY` + ObjectTypeDef，断言 toolset、agent instructions、REST 路由自动包含它（不污染产品代码） |
| 3 | 每个注册的 FunctionDef 可被 REST `GET /api/functions/<name>` 调用 |
| 4 | （有 LLM key 时）`cli smoke` 中文请求行为不退化 |

**完成标准**：`uv run pytest` 全绿 →
commit `refactor(R5): generate AI toolsets and read functions from registry`。

---

## Phase R6 — 清尾与文档对齐

### 改动

- `orchestrator._classify_domain` 兜底从隐式 `cards_docs` 改为显式 `OTHER` 域或
  返回澄清提示。
- 确认 REST 无任何「200 假成功」残留（R2 应已消除，此处复核）。
- 更新 `README.md`、`deploy/hermes/skills/home-atlas/SKILL.md` 使文档与实际行为一致；
  清理 `TODO.md` 已完成项。
- 删除全部已决策移除的死代码（R2 决策 B 等）。

### ✅ 验证目标

| # | 断言 / 核对 |
|---|------|
| 1 | `uv run pytest` 全绿 |
| 2 | 人工核对清单：README 中每条声称（如「no full card numbers」）都有对应测试佐证 |
| 3 | `grep` 确认 `resolve_hooks` / `post_hooks` 等已删符号无残留引用 |

**完成标准**：commit `refactor(R6): cleanup and docs alignment`。

---

## 每 Phase 执行检查清单（模板）

```
☐ 1. 为新行为/缺陷先写测试（失败状态）
☐ 2. 实现改动，uv run pytest 全量通过
☐ 3. 涉及迁移时：alembic upgrade head 在本地 Postgres 验证
☐ 4. （可选）MCP smoke：uv run python -m home_atlas.cli smoke --token you-token
☐ 5. git commit（独立、可回滚，message 按 refactor(R<n>): ... 格式）
☐ 6. 更新本文档状态表 + 记录 commit hash
```

## 风险与注意事项

- **R1.3 迁移风险**：默认角色改 `member` 后，真实家庭部署中的两位用户需用
  `HOME_ATLAS_ADMINS` 或 `SetPersonRole` 显式赋权，否则会失去 UpdateItem/DiscardItem
  权限——升级说明要写进 README。
- **R2 行为变化**：`UpdateItem` 的 confirm 要求从「仅 name/properties」扩大到全部字段，
  AI 子 Agent 的工具封装需同步传 confirm，否则 AI 路径会出现新的失败。
- **R4 是改动面最大的 Phase**：动 `ontology.py` 核心结构，依赖它的
  `links.py` / `toolsets.py` / `agents.py` / `rest_api.py` 都会被波及；
  严格依赖 R2 已建立的 dispatcher 收口，避免多点散改。
