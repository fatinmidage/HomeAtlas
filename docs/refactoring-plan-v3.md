# HomeAtlas 重构计划 v3 — 复审残留修复（R7–R9）

> 状态跟踪：完成一个 Phase 就把下表打勾。**未打勾 = 未开始**。
>
> | Phase | 主题 | 优先级 | 状态 |
> |-------|------|--------|------|
> | R7 | 堵读路径泄漏链（读端点认证 / Function 权限 / 审计打码） | 🔴 高危 | ☑ |
> | R8 | R5 真正收尾：AI 工具由 ActionTypeDef 生成 | 🟠 中 | ☐ |
> | R9 | 护栏硬化与文档对齐 | 🟡 低 | ☐ |

## Context

2026-06-10 对 R1–R6 重构的复审结论：原审计 12 项发现中 11 项已修复、测试 99 全绿，
整体质量高。但复审发现一条**完整的泄漏链**和一项**计划与实际不符**：

1. **泄漏链（洞 A+B+C 串联）**：REST 读端点（`/api/objects/*`、`/api/functions/*`、
   `/api/ontology`）没有挂认证依赖（A）；`dispatch_function` 不消费
   `FunctionDef.required_role`——「声明不生效」的老毛病在新代码上复发（B）；
   Event 的 before/after 快照存原始 properties，`recent_activity` 原样返回（C）。
   三者叠加 = 不带 token 就能读到未打码的证件号/保单号。
2. **R5 只完成了一半**：v2 计划要求 AI 工具从 `ActionTypeDef` **生成**并删除手写
   builder。实际只做到「AI 工具改走 dispatcher」——
   `agents.py` 的 `_build_ai_toolset_for_domain()` 内部仍是三组手写工具函数，
   「新增类型后 Agent 自动获得能力」的演练测试也没有写。v2 文档却把 R5 勾成了已完成。
3. **护栏强度问题**：卡号正则 `\b\d{13,19}\b` 拦不住带空格/连字符的写法
   （`4111 1111 1111 1111`）；`location_name` 未纳入敏感扫描。

v2 计划文档（R1–R6）已执行完毕并删除；上述残留即本计划的全部范围。

## 全局规则（每个 Phase 强制）

1. **接口不变**：对外 MCP 工具 `home_atlas(request)` 与 `ontology_describe` 的签名和
   行为契约不变。（注意：R7 会改变 REST 的读端点行为——这是计划内的 breaking change，
   见 R7 风险说明。）
2. **测试全绿才算完成**：每个 Phase 结束必须 `uv run pytest` 全量通过，不允许跳过或
   删除既有用例来换取通过。
3. **每 Phase 一个独立 commit**：格式 `refactor(R<n>): <summary>`，必须可独立回滚。
4. **新行为必须有新测试**：修缺陷先写能复现缺陷的失败测试（如「无 token 读返回 200」
   的现状断言翻转为「必须 401」），再修复。
5. **顺序执行**：R7 → R8 → R9。
6. **完成后更新本文档**：勾选状态表，并在 Phase 末尾如实追加「实际结果」——
   如果某项没做或缩了范围，必须写明，不允许笼统措辞掩盖（v2 的 R5 是反面教材）。

---

## Phase R7 — 堵读路径泄漏链（高危，最先做）

**目标**：让「任何读取都先认人、按角色放行、输出不含明文 secret」在 REST 路径成立，
与写路径（R1/R2 已修）对齐。

### R7.1 读端点认证（洞 A）

- `rest_api.py`：`/api/objects/*`、`/api/functions/*`、`/api/ontology` 全部挂
  `Depends(_actor_id)` 认证依赖，与写端点同一套 Bearer token 解析；
  无 token / 无效 token 返回 401。

### R7.2 Function 权限生效（洞 B）

- `dispatcher.py`：`dispatch_function` 签名增加 `actor_id`，按
  `FunctionDef.required_role` 做权限检查。
- `ontology.py`：`check_permission` 目前只查 `action_types`，需泛化为同时支持
  Function（或新增 `check_function_permission`），角色层级沿用
  viewer(0) < member(1) < admin(2)。
- 调用方同步：`rest_api.py` 的 function 端点传入认证得到的 `actor_id`。

### R7.3 审计输出打码（洞 C）

- `actions.py`：`recent_activity` 返回的 `before` / `after` 快照经 secret 打码后输出
  （快照里有 `kind` 字段，可复用 `_masked_properties` 的按 kind 查 secret 属性名 +
  `_mask_secret` 逻辑）。
- **决策记录**：打码放在**输出序列化层**而非快照入库层——`item.properties` 在主表
  本来就是明文，入库打码不减少 DB 明文面，反而破坏审计快照的忠实性；泄漏面只在输出。

### ✅ 验证目标（全部写成自动化断言）

| # | 断言 |
|---|------|
| 1 | 无 token：`GET /api/objects/Food` → 401（先写现状是 200 的失败测试再修） |
| 2 | 无 token：`GET /api/functions/search_items` → 401；`GET /api/ontology` → 401 |
| 3 | 带合法 token 的读请求全部正常返回（既有读测试补上 header 后仍通过） |
| 4 | `dispatch_function` 权限元测试：注册一个 `required_role="admin"` 的临时 Function（monkeypatch registry），member 调用被拒、admin 成功——证明 required_role 被真实消费 |
| 5 | 写入含 secret 属性（如 `document_number`）的物品后，`recent_activity` 返回的 `after.properties.document_number` 已打码为 `****XXXX` 形式 |
| 6 | `where_is` / `search_items` / `get_item` 的打码行为不变（回归） |

**新增/修改测试**：`tests/test_rest_api.py`（读端点 401 + 带 token 通过）、
`tests/test_dispatcher.py`（Function 权限）、`tests/test_actions.py`
（recent_activity 打码）。

**⚠️ 风险**：读端点加认证对已有 REST 消费者是 breaking change（Hermes 走 MCP 不受
影响）。`README.md` 的 REST 示例需同步加上 `Authorization` header。

**完成标准**：`uv run pytest` 全绿 →
commit `refactor(R7): authenticate REST read path and mask secrets in audit output`。

**实际结果（2026-06-10）**：

- REST 读端点 `/api/objects/*`、`/api/functions/*`、`/api/ontology` 已统一要求 Bearer token；无 token 返回 401，合法 token 保持读行为可用。
- `dispatch_function` 已消费 `FunctionDef.required_role`，并由 REST function 端点传入认证 actor。
- `recent_activity` 在输出序列化层对 `before` / `after` 快照中的 secret properties 打码；事件入库快照保持原始值。
- 新增覆盖：读端点认证、function required_role、审计快照打码；回归验证 `where_is` / `search_items` / `get_item` 既有打码行为。
- 验证：`uv run pytest` 通过（102 passed, 4 skipped）。

---

## Phase R8 — R5 真正收尾：AI 工具由 ActionTypeDef 生成

**目标**：兑现 v2/R5 未完成的承诺——`agents.py` 删除手写工具函数，AI 工具从
Registry 的声明派生；新增 Action Type 后 AI Agent 无需改代码自动获得工具。

### 改动

- `agents.py`：
  - `_build_ai_toolset_for_domain(domain)` 重写为真正的生成器：遍历该 domain 下
    所有适用的 `ActionTypeDef`，按参数声明（`ActionParameterDef`）动态构造
    Pydantic AI 工具（实现手段自由：动态构造带签名的包装函数，或
    Pydantic AI 的 schema 式 Tool 构造，以工具调用行为等价为准）；
    读工具从 `FunctionDef` 派生。
  - **删除** `_build_perishable_tools` / `_build_cards_docs_tools` /
    `_build_equipment_tools` 三个手写 builder。
  - **工具名兼容**：生成的工具名沿用现有命名（`perishable_add_item`、
    `card_upsert_payment_reference` 等），命名规则放进声明或映射表，
    保证既有行为测试不变。
- 注意 `build_agents` 的 `lru_cache`：依赖 registry 的测试需先清缓存
  （`build_agents.cache_clear()`），避免拿到旧 toolset。

### ✅ 验证目标

| # | 断言 |
|---|------|
| 1 | 回归：三个 domain 生成的工具名集合与删除手写 builder 前完全一致（沿用既有 `test_generated_ai_toolsets_keep_existing_tool_names`，此时它验证的才是真生成） |
| 2 | **自动感知演练**：测试内 monkeypatch registry，给 PERISHABLE 域临时注册一个新 `ActionTypeDef`（如 `PingItem`，复用现有 `ItemKind.FOOD`，因 StrEnum 无法临时加成员），断言 `_build_ai_toolset_for_domain(PERISHABLE)` 自动包含对应新工具——**不改 `agents.py` 一行** |
| 3 | 生成工具的参数与 `ActionParameterDef` 一致（必填/可选/类型），抽查 AddItem 工具 schema |
| 4 | `grep` 确认三个手写 builder 符号已删除、无残留引用 |
| 5 | （有 LLM key 时）`cli smoke` 中文请求行为不退化 |

**新增/修改测试**：`tests/test_orchestrator.py`（自动感知演练 + schema 抽查）。

**完成标准**：`uv run pytest` 全绿 →
commit `refactor(R8): derive AI toolsets from ActionTypeDef declarations`。

---

## Phase R9 — 护栏硬化与文档对齐

### 改动

- `security.py`：卡号扫描升级为「**归一化后匹配**」——把候选文本中的空格/连字符剔除后
  再跑 13–19 位检测，拦住 `4111 1111 1111 1111` 与 `4111-1111-1111-1111`；
  先写负面用例防误报（普通句子里的年份、电话、快递单号组合不应被拒）。
- `actions.py`：`location_name` 纳入 `scan_sensitive_text`
  （`add_item` / `move_item` / `upsert_card_reference`）。
- `links.py`：`auto_traverse` 在 source_type == target_type 时返回该对象的完整行数据
  （替代现在的 `[{"id": id}]` 占位），语义统一为「返回目标对象列表」。
- **决策记录**：action 实现内与 dispatcher 重复的权限/confirm 检查**保留**，
  定性为纵深防御（actions 仍可被测试与内部代码直调）；在 `actions.py` 模块
  docstring 写明这一决策，消除「计划说收口、代码是双检」的表述矛盾。
- `README.md` / `deploy/hermes/skills/home-atlas/SKILL.md`：补 R7 的 REST 认证变化
  说明；复核「no full card numbers」等声称与新护栏一致。

### ✅ 验证目标

| # | 断言 |
|---|------|
| 1 | notes/properties 含 `4111 1111 1111 1111` 或 `4111-1111-1111-1111` → 拒绝 |
| 2 | 误报负面用例：含正常数字组合的文本（如「2026年6月 顺丰 SF1234567890123」）不被拒绝——该用例需在实现前确定归一化策略能通过 |
| 3 | `location_name` 含完整卡号 → 拒绝 |
| 4 | `auto_traverse(Item, id, Item)` 返回完整对象行（含 name 字段） |
| 5 | 人工核对：README REST 示例带 Authorization header；文档声称与测试一一对应 |

**新增/修改测试**：`tests/test_actions.py`（分隔符卡号 + 误报负面 + location_name）、
`tests/test_links.py`（同类型遍历语义）。

**完成标准**：`uv run pytest` 全绿 →
commit `refactor(R9): harden sensitive-data guards and align docs`。

---

## 每 Phase 执行检查清单（模板）

```
☐ 1. 为新行为/缺陷先写测试（失败状态）
☐ 2. 实现改动，uv run pytest 全量通过
☐ 3. （可选）MCP smoke：uv run python -m home_atlas.cli smoke --token you-token
☐ 4. git commit（独立、可回滚，message 按 refactor(R<n>): ... 格式）
☐ 5. 更新本文档状态表 + 如实记录「实际结果」（没做的就写没做）
```

## 风险与注意事项

- **R7 是对外行为变化**：REST 读从「裸奔」变为「必须带 token」。本项目当前唯一真实
  消费者 Hermes 走 MCP 不受影响，但 README 示例和任何脚本调用方必须同步。
- **R8 的实现自由度**：Pydantic AI 对工具签名/docstring 有要求，动态生成时优先保证
  「工具名 + 参数 schema + 调用行为」三者与现状等价；如果某个工具（如
  `card_upsert_payment_reference` 的属性拼装逻辑）确实无法纯声明化，允许在声明中
  指向一个显式的 adapter 函数，但 adapter 必须由 Registry 引用而非硬编码在
  `agents.py` 的 domain 分支里。
- **R9 的误报权衡**：归一化扫描比裸正则更激进，先写负面用例锁住边界再实现；
  如果误报无法接受，可缩窄为「仅当剔除分隔符后得到连续 13–19 位**且**
  通过 Luhn 校验」——把这个备选方案留给实现时决策，写进「实际结果」。
