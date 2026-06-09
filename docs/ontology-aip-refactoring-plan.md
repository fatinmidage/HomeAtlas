# HomeAtlas Ontology/AIP 重构方案

## Context

HomeAtlas 当前架构在 AIP 编排层（Agent 分域、Action 约束、安全护栏）已做得较好，但在 Ontology 数据建模层与 Palantir 规范有明显差距：`Item` 超级表 + `kind` 枚举 + `properties` JSON 口袋缺乏强类型约束；对象关系、Action 定义、Property Schema 分散在各文件中无统一注册；AI Agent 的工具和指令全部硬编码。

本重构的目标是引入 Palantir Ontology 的核心抽象——**集中式 Schema Registry**，让 Object Types、Properties、Link Types、Action Types 成为显式声明的元数据，所有消费者（AI Agent、Toolset、验证逻辑）从 Registry 动态获取，而非硬编码。

**设计约束**：
- 不改 DB 表结构（保留 `item` 单表），Ontology 层在 Python 代码层实现
- MCP 外部接口 `home_atlas(request)` 不变
- 每个 Phase 独立可部署、可回滚，测试全绿
- 复用 `actions.py`、`security.py`、`db_isolation.py` 现有代码

---

## Phase 0: Ontology Schema Registry

**目标**：创建集中式 Registry，声明所有 Object Types、Link Types、Action Types。

**Palantir 对应**：Ontology 元数据目录（所有 UI/API/AIP 消费者查询的中心注册表）。

**用 Python dataclasses 而非 YAML/DB 的原因**：Registry 描述代码自身的 schema，随代码版本走，dataclass 提供导入期类型检查和 IDE 补全，零运行时 IO。

### 新建文件

**`home_atlas/ontology.py`** — 核心数据结构：
- `PropertyDef(name, python_type, required, secret, description)` — 属性定义
- `ObjectTypeDef(api_name, item_kind, domain, typed_properties, base_columns, description)` — 对象类型定义，每个 ItemKind 一个（9 个）
- `LinkTypeDef(api_name, source_type, target_type, fk_column, cardinality, description)` — 关系定义（6 个：storedAt, addedBy, updatedBy, parentLocation, itemEvents, actorEvents）
- `ActionParameterDef(name, python_type, required, description)` — Action 参数定义
- `ActionTypeDef(api_name, event_action, applicable_to, parameters, requires_confirm, description)` — 操作类型定义，每个 EventAction 一个（7 个）
- `OntologyRegistry` — 容器类，提供查询方法：
  - `object_types_for_domain(domain)` → 按领域筛选
  - `actions_for_object_type(api_name)` → 按对象类型筛选可用 Action
  - `validate_properties(api_name, properties)` → 属性校验
  - `describe_for_llm(domain=None)` → 生成 LLM 可读的 Ontology 描述

模块级 `build_registry() -> OntologyRegistry` 和 `get_registry()` 缓存单例。

**`tests/test_ontology.py`** — 验证：
- 每个 ItemKind 映射到恰好一个 ObjectTypeDef
- 每个 EventAction 映射到恰好一个 ActionTypeDef
- Property 校验（拒绝未知 key、强制 required、接受合法输入）
- LinkTypeDef 的 fk_column 存在于对应 Model
- `describe_for_llm()` 产出非空文本

### 修改文件

- **`home_atlas/actions.py`** — 在 `add_item`、`update_item`、`upsert_card_reference` 入口添加 `registry.validate_properties()` 调用（增量校验，现有 `reject_payment_card_secrets` 保留为纵深防御）

### 验证

```bash
pytest tests/test_ontology.py tests/test_actions.py
```

---

## Phase 1: 强类型 Property Schemas

**目标**：为 `properties` JSON 口袋引入 per-ObjectType 的 Pydantic 验证模型。

**Palantir 对应**：每个 Object Type 拥有声明式 Property 集合，属性有类型、必填/可选、约束。

### 新建文件

**`home_atlas/property_schemas.py`**：
- 每个 ObjectType 一个 Pydantic BaseModel（如 `FoodItemProperties`、`PaymentCardProperties`）
- `PaymentCardProperties` 设置 `extra="forbid"`，校验 `last4` 格式
- `PROPERTY_SCHEMAS: dict[ItemKind, type[BaseModel]]` 映射表
- `validate_item_properties(kind, properties) -> dict` — 校验并返回清洗后的属性，失败抛 `HomeAtlasError`

**`tests/test_property_schemas.py`** — 覆盖 extra forbid、last4 格式、可选字段、清洗输出。

### 修改文件

- **`home_atlas/ontology.py`** — `validate_properties` 委托给 `property_schemas.validate_item_properties`
- **`home_atlas/actions.py`** — `add_item` 和 `upsert_card_reference` 调用 `validate_item_properties`（替代 Phase 0 的松散校验）

### 验证

```bash
pytest tests/test_property_schemas.py tests/test_actions.py tests/test_ontology.py
```

---

## Phase 2: Link Types 一等公民

**目标**：让 FK 关系可通过 Registry 按名称遍历，AI Agent 可询问"这个对象有什么关系"。

**Palantir 对应**：命名的、有方向的 Link Types（`Item —[storedAt]→ Location`）。

### 新建文件

**`home_atlas/links.py`**：
- `traverse_link(session, source_type, source_id, link_name) -> list[dict]` — 通过 Registry 查询 LinkTypeDef，构建 SQLAlchemy 查询，返回目标对象
- 支持 many-to-one（返回单元素列表）和 one-to-many（返回列表）

**`tests/test_links.py`** — 覆盖 storedAt、addedBy、itemEvents、parentLocation、未知 link 报错。

### 修改文件

- **`home_atlas/ontology.py`** — 添加 `describe_links_for_llm()` 方法

不新增 DB 表或列。

### 验证

```bash
pytest tests/test_links.py tests/test_ontology.py
```

---

## Phase 3: Registry 驱动的 Toolset 生成

**目标**：`toolsets.py` 和 `agents.py` 中的工具不再硬编码，改为从 Registry 动态生成。

**Palantir 对应**：AIP 的 Ontology-backed tools — Agent 可用的工具是 Ontology 的投影。

### 修改文件

**`home_atlas/toolsets.py`**：
- 新增 `toolset_for_domain(domain: ItemDomain) -> DomainToolset`，从 Registry 查询该 domain 下所有 ObjectType 和适用的 ActionType，动态构建工具字典
- 现有 `perishable_toolset()`、`cards_docs_toolset()`、`equipment_toolset()` 改为调用 `toolset_for_domain()`
- 保留 `_add_perishable`、`_add_document`、`_add_equipment` 作为 Action 实现（domain kind 约束守卫），在 ActionTypeDef 中声明为 implementation

**`home_atlas/agents.py`**：
- 新增 `_build_ai_toolset_for_domain(domain) -> FunctionToolset`，从 Registry 的 ActionTypeDef 生成 Pydantic AI 工具（docstring 和参数来自声明）
- 替换 `_perishable_ai_toolset()`、`_cards_docs_ai_toolset()`、`_equipment_ai_toolset()`

**`home_atlas/ontology.py`**：
- `ActionTypeDef` 新增 `implementation: str` 字段（dotted path）
- `OntologyRegistry.resolve_action(api_name) -> Callable`
- `OntologyRegistry.action_parameter_schema(api_name) -> dict`

### 关键验证

新测试 `test_generated_toolset_matches_manual` — 比较新旧生成方式产出的工具名一致。

```bash
pytest tests/test_orchestrator.py tests/test_ontology.py
```

---

## Phase 4: Ontology 感知的 AI 层

**目标**：Agent 指令完全从 Registry 生成。新增 ObjectType/ActionType 后无需改 `agents.py`。

**Palantir 对应**：AIP 中新增 Ontology Action Type 后 Agent 自动感知。

### 修改文件

**`home_atlas/agents.py`**：
- `build_agents(model)` 重构：循环 3 个 domain，从 Registry 生成 toolset + instructions
- `_build_sub_agent_instructions(registry, domain) -> str` — 从 ObjectTypeDef 描述生成 Agent 指令
- `_build_orchestrator_instructions(registry) -> str` — 列出所有 domain、ObjectType、可用 Action

**效果**：在 `ontology.py` 中新增 `ItemKind.CLEANING_SUPPLY` + 对应 `ObjectTypeDef`，无需改动 `agents.py`/`toolsets.py`/`orchestrator.py`，Agent 自动获得该类型的管理能力。

### 验证

```bash
pytest tests/ -v  # 全量，确认所有行为不变
```

---

## Phase 5: Event 审计规范化

**目标**：明确架构为 State + Audit Log（非 Event Sourcing），补充 event version 支持有序回放。

**Palantir 对应**：Ontology 审计/溯源。

### 新建文件

**`migrations/versions/0002_event_version.py`** — 添加 `event.version` 列（Integer, nullable）

### 修改文件

- **`home_atlas/models.py`** — `Event` 新增 `version: int | None = Field(default=None)`
- **`home_atlas/actions.py`** — `_event()` 计算 per-item 递增 version；顶部添加架构说明 docstring

### 验证

```bash
alembic upgrade head  # 迁移测试
pytest tests/test_actions.py  # version 递增验证
```

---

## 实施总览

| Phase | 新文件 | 改动文件 | DB 迁移 | 核心交付 |
|-------|--------|----------|---------|----------|
| 0 | `ontology.py`, `tests/test_ontology.py` | `actions.py` | 无 | OntologyRegistry 集中声明 |
| 1 | `property_schemas.py`, `tests/test_property_schemas.py` | `ontology.py`, `actions.py` | 无 | Per-type Pydantic 属性校验 |
| 2 | `links.py`, `tests/test_links.py` | `ontology.py` | 无 | 命名关系遍历 |
| 3 | 无 | `toolsets.py`, `agents.py`, `ontology.py` | 无 | Registry 驱动工具生成 |
| 4 | 无 | `agents.py` | 无 | Registry 驱动 Agent 指令 |
| 5 | `migrations/versions/0002_event_version.py` | `models.py`, `actions.py` | `event.version` | 审计版本号 |

## 端到端验证

每个 Phase 完成后：
1. `pytest tests/ -v` 全量通过
2. 启动 MCP server `python -m home_atlas.mcp_server`，用 bearer token 发送中文请求验证功能不退化
3. Phase 3/4 额外验证：在 `ontology.py` 中假增一个新 ObjectType，确认 toolset 和 agent instructions 自动包含它
