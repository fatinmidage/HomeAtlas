# HomeAtlas 模块分类重构 Hand off

## 一句话结论

本文件只定义重构计划与验收标准；在用户明确批准前，不移动代码、不改 import、不提交 commit。

## 当前状态快照

| 观察项 | 当前状态 | 判断 |
| --- | --- | --- |
| 包结构 | `home_atlas/` 下所有代码文件平铺 | 可读性开始下降，但还没到必须一次性大搬家的程度 |
| 代码规模 | 约 22 个 `.py` 文件，总计约 3500 行 | 可以分阶段整理 |
| 偏大的文件 | `ontology.py` 约 747 行，`actions.py` 约 579 行 | 优先成为边界整理对象 |
| 外部引用 | 测试、README、入口命令大量引用 `home_atlas.actions`、`home_atlas.models` 等旧路径 | 直接搬目录风险中等 |
| 推荐策略 | 先定义职责边界，再小步迁移 | 避免一次性改动过大 |

## 总成功目标

重构完成后应同时满足：

1. `home_atlas` 代码按职责归类，阅读入口更清楚。
2. 现有公开入口保持可用，包括：
   - `python -m home_atlas.cli ...`
   - `python -m home_atlas.mcp_server`
   - `python -m home_atlas.http_server`
   - `from home_atlas import add_item, home_atlas`
3. 测试全部通过。
4. README 中的命令和代码路径不误导后续维护者。
5. 每个阶段都是独立 commit，可单独回滚。
6. 不引入新功能，不顺手重构无关代码。

## 推荐目标结构

```text
home_atlas/
  domain/
    models.py
    ontology.py
    property_schemas.py
    links.py

  app/
    actions.py
    dispatcher.py
    orchestrator.py
    agents.py
    toolsets.py

  infra/
    db.py
    db_isolation.py
    schema_migration.py
    event_bus.py
    backup.py

  interfaces/
    cli.py
    mcp_server.py
    http_server.py
    rest_api.py

  core/
    config.py
    llm_config.py
    security.py

  __init__.py
```

## 归类原则

| 分类 | 放入标准 | 当前候选文件 |
| --- | --- | --- |
| `domain/` | 描述“家里有什么、东西之间怎么关联”的核心概念 | `models.py`、`ontology.py`、`property_schemas.py`、`links.py` |
| `app/` | 执行业务动作、路由请求、调度工具和 AI agent | `actions.py`、`dispatcher.py`、`orchestrator.py`、`agents.py`、`toolsets.py` |
| `infra/` | 数据库、迁移、备份、事件投递等运行支撑 | `db.py`、`db_isolation.py`、`schema_migration.py`、`event_bus.py`、`backup.py` |
| `interfaces/` | CLI、MCP、HTTP、REST 这些对外入口 | `cli.py`、`mcp_server.py`、`http_server.py`、`rest_api.py` |
| `core/` | 配置、安全、LLM 配置等被多处依赖的基础能力 | `config.py`、`security.py`、`llm_config.py` |

## 阶段 0：批准前准备

| 项 | 内容 |
| --- | --- |
| 目标 | 只确认计划，不改业务代码 |
| 允许改动 | 本文件 |
| 禁止改动 | 移动模块、改 import、改测试、提交 commit |
| 验证 | 用户明确批准执行 |
| commit | 不提交 |

## 阶段 1：建立包目录与兼容层

| 项 | 内容 |
| --- | --- |
| 目标 | 创建新目录结构，但尽量保持旧 import 路径可用 |
| 主要动作 | 新建 `domain/`、`app/`、`infra/`、`interfaces/`、`core/` 目录和 `__init__.py` |
| 迁移策略 | 每移动一个旧模块，就在旧路径保留薄兼容文件，例如 `home_atlas/actions.py` 继续 re-export `home_atlas.app.actions` |
| 成功标准 | 旧路径和新路径都能导入 |
| 验证命令 | `uv run pytest` |
| 额外验证 | `uv run python -m home_atlas.cli doctor` |
| commit 时机 | 所有验证通过后 |
| 建议 commit 信息 | `refactor: add package structure with compatibility imports` |

## 阶段 2：迁移低风险基础模块

| 项 | 内容 |
| --- | --- |
| 目标 | 先移动依赖关系较基础、行为稳定的模块 |
| 建议范围 | `config.py`、`llm_config.py`、`security.py`、`models.py`、`property_schemas.py` |
| 成功标准 | 调用方行为不变，旧 import 仍可用 |
| 重点检查 | 循环导入、测试中的直接 import、Alembic 迁移引用 |
| 验证命令 | `uv run pytest tests/test_property_schemas.py tests/test_rbac.py tests/test_cli.py` |
| 全量验证 | `uv run pytest` |
| commit 时机 | 所有验证通过后 |
| 建议 commit 信息 | `refactor: move core and domain foundation modules` |

## 阶段 3：迁移基础设施模块

| 项 | 内容 |
| --- | --- |
| 目标 | 把数据库、备份、事件相关代码移动到 `infra/` |
| 建议范围 | `db.py`、`db_isolation.py`、`schema_migration.py`、`event_bus.py`、`backup.py` |
| 成功标准 | 数据库初始化、schema gate、事件记录、备份测试行为不变 |
| 重点检查 | `migrations/env.py`、CLI 入口、服务启动前 schema 检查 |
| 验证命令 | `uv run pytest tests/test_schema_version.py tests/test_event_bus.py tests/test_backup.py tests/test_db_isolation.py` |
| 全量验证 | `uv run pytest` |
| commit 时机 | 所有验证通过后 |
| 建议 commit 信息 | `refactor: move infrastructure modules` |

## 阶段 4：迁移业务应用模块

| 项 | 内容 |
| --- | --- |
| 目标 | 把动作、调度、agent、工具集移动到 `app/` |
| 建议范围 | `actions.py`、`dispatcher.py`、`orchestrator.py`、`agents.py`、`toolsets.py` |
| 成功标准 | 自然语言路由、dispatcher、AI 工具构建、RBAC 行为不变 |
| 重点检查 | `ontology.py` 中的 implementation 字符串、agent adapter 字符串、`__init__.py` re-export |
| 验证命令 | `uv run pytest tests/test_actions.py tests/test_dispatcher.py tests/test_orchestrator.py tests/test_rbac.py` |
| 全量验证 | `uv run pytest` |
| commit 时机 | 所有验证通过后 |
| 建议 commit 信息 | `refactor: move application service modules` |

## 阶段 5：迁移接口入口模块

| 项 | 内容 |
| --- | --- |
| 目标 | 把 CLI、MCP、HTTP、REST 入口移动到 `interfaces/`，同时保持 `python -m home_atlas.cli` 等旧入口可用 |
| 建议范围 | `cli.py`、`mcp_server.py`、`http_server.py`、`rest_api.py` |
| 成功标准 | 老命令不坏，新路径也可被内部代码引用 |
| 重点检查 | Dockerfile、launchd plist、README 命令示例 |
| 验证命令 | `uv run pytest tests/test_cli.py tests/test_rest_api.py tests/test_orchestrator.py` |
| 入口验证 | `uv run python -m home_atlas.cli doctor` |
| 全量验证 | `uv run pytest` |
| commit 时机 | 所有验证通过后 |
| 建议 commit 信息 | `refactor: move interface modules while preserving entrypoints` |

## 阶段 6：文档同步与最终清理

| 项 | 内容 |
| --- | --- |
| 目标 | 让 README 和计划文档准确反映新结构 |
| 建议范围 | `README.md`、本文件 |
| 保留兼容层 | 若外部入口仍依赖旧路径，先保留；不要急着删除 |
| 可删除内容 | 只删除本次迁移产生的无用 import、重复说明或临时兼容说明 |
| 禁止内容 | 不删除历史上已有但与本次无关的死代码 |
| 验证命令 | `uv run pytest` |
| 文档验证 | 手动检查 README 中所有 `home_atlas.*` 路径是否仍成立 |
| commit 时机 | 所有验证通过后 |
| 建议 commit 信息 | `docs: update module layout documentation` |

## 执行检查清单

每个执行阶段都必须满足以下检查项后才能 commit：

```text
1. 确认本阶段只改计划范围内的文件。
2. 确认旧 import 路径仍可用，除非该阶段明确要移除。
3. 运行本阶段指定测试。
4. 运行 `uv run pytest`。
5. 如涉及入口模块，运行对应 `python -m home_atlas...` 命令。
6. 更新 README 或本文件中的阶段状态。
7. 查看 `git diff`，确认没有无关格式化或顺手改动。
8. 所有验证通过后再提交一个独立 commit。
```

## 阶段状态

| 阶段 | 状态 | 备注 |
| --- | --- | --- |
| 阶段 0：批准前准备 | 已完成 | 用户已批准开始执行 |
| 阶段 1：建立包目录与兼容层 | 已完成 | 已创建目标包目录；验证通过并提交 |
| 阶段 2：迁移低风险基础模块 | 已完成 | core/domain 基础模块已迁移；验证通过并提交 |
| 阶段 3：迁移基础设施模块 | 未开始 | 需阶段 2 完成 |
| 阶段 4：迁移业务应用模块 | 未开始 | 需阶段 3 完成 |
| 阶段 5：迁移接口入口模块 | 未开始 | 需阶段 4 完成 |
| 阶段 6：文档同步与最终清理 | 未开始 | 需阶段 5 完成 |

## 回滚原则

| 场景 | 处理方式 |
| --- | --- |
| 某阶段测试失败且短时间无法修复 | 不 commit，回到该阶段开始前的状态 |
| 已提交阶段发现问题 | 只回滚该阶段 commit |
| 发现计划分类不合适 | 停止执行，先更新本文件并重新征求用户批准 |
| 发现无关历史问题 | 记录给用户，不在本轮顺手修 |

## 给后续执行者的提醒

1. 这是结构重构，不是功能开发。
2. 兼容层很重要，先保证旧入口不坏。
3. 变更越小越好，每个 commit 只做一个阶段。
4. 如果某阶段 import 改动过大，应停止并重新拆小阶段。
5. 用户批准前不要开始阶段 1。
