# Handoff：修复 Hermes 无法归档/丢弃物品的问题

## 修复状态

✅ 已完成（2026-06-14）

| 项目 | 状态 |
|------|:---:|
| `DiscardItem` 注册三个 AI 工具 | ✅ |
| `DiscardItem` 降权到 `member` | ✅ |
| AI action 工具自动传递确认型 action 的 `confirm=True` | ✅ |
| AI 工具返回值包含 `archived` | ✅ |
| `pytest tests/` 全绿 | ✅ |
| 本地行为核验：归档后普通列表不再显示该物品 | ✅ |

## 背景

2026-06-14 会话 `20260614_115848_cf0004`（friday profile）中，用户说"第一个鸡腿软骨已经吃完了，要怎么处理？"，Hermes 调用 `mcp_home_atlas_home_atlas("鸡腿软骨已经吃完了，帮我归档掉")`，服务端返回：

> "目前我手头的工具和 perishables（食品）子代理都不支持直接将物品归档或删除...没有归档/删除的权限"

Hermes 最终用"把数量设为 0"作为 workaround，但这不是正确的归档流程。

## 根因分析

有 **两个独立的阻塞点**，两个都满足才能让归档正常工作：

### 阻塞点 1：AI 子代理没有 discard 工具

`DiscardItem` 在 ontology 中没有定义 `ai_tools`（空 tuple），导致 AI 子代理的工具箱里根本没有归档能力。

**证据链**：

- `home_atlas/domain/ontology.py:621-632` — `DiscardItem` 的 `ai_tools` 使用默认值 `()`
- `home_atlas/app/agents.py:200-208` — `_build_ai_toolset_for_domain()` 只注册有 `ai_tools` 条目的 action
- 目前只有 `AddItem` 和 `UpsertCardReference` 有 `ai_tools`，其余 6 个 action 全没有：

| Action | ai_tools | AI 子代理可用？ |
|--------|----------|:---:|
| AddItem | ✅ 有定义 | ✅ |
| UpsertCardReference | ✅ 有定义 | ✅ |
| MoveItem | ❌ 空 | ❌ |
| AdjustQuantity | ❌ 空 | ❌ |
| SetQuantity | ❌ 空 | ❌ |
| UpdateItem | ❌ 空 | ❌ |
| DiscardItem | ❌ 空 | ❌ |
| SetPersonRole | ❌ 空 | ❌ |

> 注：`rules` 模式（`toolsets.py:79`）已经注册了 `DiscardItem → discard`，所以 rules 模式下不存在这个问题。问题只出在 `agent_mode=auto/ai` 时。

### 阻塞点 2：Hermes 用户角色权限不足

即使添加了 `ai_tools`，`discard_item()` 内部的 RBAC 检查也会拒绝：

- Hermes token `LFr6va8j...` → 映射到 person `吴英恒`（id=4）
- `吴英恒` 的 roles = `["member"]`（权限等级 1）
- `DiscardItem` 的 `required_role = "admin"`（权限等级 2）
- `1 < 2` → `UnauthorizedError`

角色权限等级：`{"admin": 2, "member": 1, "viewer": 0}`

当前所有用户角色：

| id | name | roles | 能否 discard？ |
|:--:|------|-------|:---:|
| 1 | 你 | `["admin", "member"]` | ✅ |
| 2 | 配偶 | `["member"]` | ❌ |
| 3 | 曾远清 | `["member"]` | ❌ |
| 4 | 吴英恒 | `["member"]` | ❌ |

---

## 修复项 1：为 `DiscardItem` 添加 `ai_tools`

**文件**：`home_atlas/domain/ontology.py:621-632`

**要做什么**：给 `DiscardItem` 的 `ActionTypeDef` 添加 `ai_tools` 元组，为三个 domain（PERISHABLE、CARDS_DOCS、EQUIPMENT）各注册一个工具，使 AI 子代理能调用归档。

**参考**：`AddItem` 的 `ai_tools` 定义方式（同文件中搜索 `api_name="AddItem"` 即可看到完整示例）。

**注意事项**：

- `DiscardItem` 需要 `item_id`（int）和 `confirm`（bool），confirm 由 `dispatch_action` 传递
- `requires_confirm=True` 已经设置，`dispatch_action` 会处理 confirm 逻辑
- 工具描述建议用中文，如 `"归档/丢弃该食品"` / `"归档/丢弃该证件"` / `"归档/丢弃该设备"`

### 验收标准

| # | 标准 | 验证方法 |
|---|------|---------|
| 1 | `DiscardItem` 的 `ai_tools` 非空，为三个 domain 各有一个工具定义 | `python3 -c "from home_atlas.domain.ontology import get_registry; r=get_registry(); print(len(r.action_types['DiscardItem'].ai_tools))"` 输出 `3` |
| 2 | AI perishables 子代理的工具列表中包含 discard 工具 | 启动服务后，通过 MCP 发送 `ontology_describe()`，确认 PERISHABLE domain 的 actions 中包含 discard 相关工具 |
| 3 | 全量测试通过 | `pytest tests/` 全绿 |

---

## 修复项 2：调整 `DiscardItem` 的权限要求

**文件**：`home_atlas/domain/ontology.py:631`

**当前**：`required_role="admin"`

**需要决策**：选择以下方案之一。

| 方案 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| A：降级权限 | 把 `required_role` 改为 `"member"` | 所有家庭成员都能归档物品，操作更顺畅 | 降低了归档操作的管控力度 |
| B：升级用户 | 给 `吴英恒` 添加 `"admin"` 角色 | 不改代码，只改数据 | 只解决当前用户的问题，其他 member 仍然不能归档 |
| C：两者都做 | 降级权限 + 不改用户 | 最彻底 | 如果归档确实应该是高权限操作，则不合适 |

**建议**：方案 A — 归档/吃完是日常操作，不应该需要 admin 权限。`requires_confirm=True` 已经提供了二次确认保护，足以防止误操作。

### 验收标准

| # | 标准 | 验证方法 |
|---|------|---------|
| 1 | `DiscardItem` 的 `required_role` 为 `"member"` | `grep -A10 "DiscardItem" home_atlas/domain/ontology.py` 确认 `required_role="member"` |
| 2 | member 角色用户可以成功归档物品 | `pytest tests/test_rbac.py` 通过（可能需要更新测试用例） |
| 3 | 归档仍需要 `confirm=true` | `pytest tests/test_actions.py -k discard` 确认不带 confirm 会报错 |

---

## 端到端验收

两个修复项都完成后，执行以下端到端验证：

| # | 标准 | 验证方法 |
|---|------|---------|
| 1 | 全量测试通过 | `pytest tests/` 全绿 |
| 2 | 通过 Hermes 对话归档物品成功 | 在 Hermes 中说"那个没有日期标注的鸡腿软骨已经吃完了，帮我归档掉"，确认 MCP 返回 `archived=true` 且不报权限错误 |
| 3 | 归档后查询库存不再显示已归档物品 | 调用 `home_atlas("列出所有物品")`，确认已归档的物品不在列表中 |
