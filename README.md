# HomeAtlas

HomeAtlas 是一个家庭物品库存服务，用于通过 Hermes MCP 管理家里的物品、位置、临期提醒和审计记录。

它对外暴露一个高层委托工具 `home_atlas(request)`；真正的写入操作都收在 Ontology 风格的 Actions 后面，由 Actions 负责校验输入、记录操作者，并追加审计 Events。

## 已实现内容

- SQLModel 对象模型：`Person`、`Location`、`Item`、`Event`
- Ontology Actions：添加、移动、调整数量、设置数量、更新、写入/更新卡片引用、丢弃、设置人员角色
- 由 Registry 投射出的 Read Functions：搜索、查询位置、临期列表、近期活动、最后操作记录
- 敏感数据校验覆盖名称、位置、备注和属性：禁止完整 13-19 位卡号，包括用空格或连字符分隔的形式；禁止 CVV/卡号字段；银行卡属性只允许引用字段
- token 到人员身份的解析；REST 和 MCP 都在服务端解析操作者
- RBAC 默认把新人员设为 `member`；仅管理员可执行更新、丢弃和角色变更
- 启动时 schema 闸门：Alembic 迁移和 schema metadata 未更新时，服务拒绝启动
- 脱敏读取输出：Registry read functions 返回适合 MCP/REST 使用的安全字典
- 重名对象有确定性的查找行为：选择最新匹配，并标注存在歧义
- 带前缀的领域工具集：`perishable_*`、`card_*`、`equipment_*`
- `home_atlas(request)` 背后的规则型编排器，用于本地确定性行为
- FastMCP 构造钩子，以及用于本地冒烟测试的小型标准库 HTTP runner
- Alembic 迁移和 pytest 覆盖核心验证清单

## 初始化

```bash
uv sync
cp .env.example .env
uv run python -m home_atlas.cli init-db
```

启动任何长驻入口前，都要先运行 `init-db`，包括 `home_atlas.mcp_server`、`home_atlas.http_server` 或生成的 REST app。HomeAtlas 不再在服务启动时自动建表；如果数据库 schema 缺失或比代码旧，它会快速失败并停止启动。

本地单元测试不需要 PostgreSQL 服务。测试会使用内存 SQLite 数据库，同时仍然覆盖同一套 SQLModel 表和 Action 层。

```bash
uv run pytest
```

## PostgreSQL

本地开发可以使用 Docker Compose：

```bash
/Applications/Docker.app/Contents/Resources/bin/docker compose up -d postgres
```

然后初始化 schema，并写入 token 映射到的人员：

```bash
cp .env.example .env
uv run python -m home_atlas.cli doctor
uv run python -m home_atlas.cli init-db
uv run python -m home_atlas.cli smoke --token replace-with-token-1
uv run python -m home_atlas.cli dual-smoke --writer-token replace-with-token-1 --reader-token replace-with-token-2
```

预期冒烟测试结果中会包含：

```text
"answer": "护照 在 保险柜抽屉"
```

如果你在 Docker 外自行管理 PostgreSQL，请先创建数据库，设置 `HOME_ATLAS_DATABASE_URL`，然后运行：

```bash
uv run python -m home_atlas.cli init-db
```

连接字符串示例：

```text
postgresql+psycopg://home_atlas:<password>@localhost:5432/home_atlas
```

Python 运维入口不要求 `psql` 在 `PATH` 中：

```bash
export HOME_ATLAS_DATABASE_URL='postgresql+psycopg://home_atlas:<password>@localhost:5432/home_atlas'
export HOME_ATLAS_TOKEN_MAP='{"replace-with-token-1":"你","replace-with-token-2":"配偶"}'
export HOME_ATLAS_ADMINS='你'

uv run python -m home_atlas.cli doctor
uv run python -m home_atlas.cli init-db --create-database
uv run python -m home_atlas.cli smoke --token replace-with-token-1
```

如果数据库角色已经存在，但数据库本身还不存在，`--create-database` 会通过名为 `postgres` 的维护数据库创建配置里的目标数据库。如果你的本地 Postgres 使用 macOS 用户名作为角色，请相应修改 URL，例如：

```bash
export HOME_ATLAS_DATABASE_URL='postgresql+psycopg://<local-user>@localhost:5432/home_atlas'
```

## Hermes MCP 配置形态

Hermes 应该只看到一个可写工具：

```yaml
mcp_servers:
  home_atlas:
    url: "http://<家庭服务器局域网IP>:8080/mcp"
    headers: { Authorization: "Bearer <该机器的token>" }
```

通过 `HOME_ATLAS_TOKEN_MAP` 设置 token 属于谁：

```json
{"replace-with-token-1":"你","replace-with-token-2":"配偶"}
```

服务端会解析 Bearer token，并只把 `actor_id` 传入 Actions，所以 LLM 不能伪造操作者。
初始管理员通过 `HOME_ATLAS_ADMINS` 设置，格式是逗号分隔的姓名列表，姓名要匹配 `HOME_ATLAS_TOKEN_MAP` 的值。已有记录会保留当前角色；如需变更角色，请使用 `SetPersonRole` Action，这样会留下审计记录。

运行带 Bearer 认证的 FastMCP streamable HTTP server：

```bash
uv run python -m home_atlas.cli init-db
uv run python -m home_atlas.mcp_server
```

Hermes 会向 `/mcp` 发送 `Authorization: Bearer <token>`。FastMCP 会在工具运行前校验 Bearer token，然后 `home_atlas(request)` 在服务端解析操作者。

可以把 `deploy/hermes/mcp.yaml.example` 当作双设备模板。每个 Hermes 客户端使用同一个 URL，但使用各自独立的 Bearer token。

在两台真实 Hermes 客户端接入前，可以用下面的命令在本地验证同一套操作者模型：token A 写入，token B 读取，数据库审计事件必须显示 token A 对应的操作者。

```bash
uv run python -m home_atlas.cli dual-smoke \
  --writer-token replace-with-token-1 \
  --reader-token replace-with-token-2 \
  --item 双端烟测护照 \
  --location 双端烟测保险柜
```

## REST API

生成的 REST API 同样会从 Bearer token 解析操作者。读写接口都需要 `Authorization`；未认证的读取请求会返回 401。

```bash
curl http://localhost:8080/api/objects/Food \
  -H 'Authorization: Bearer replace-with-token-1'

curl http://localhost:8080/api/ontology \
  -H 'Authorization: Bearer replace-with-token-1'
```

## Agent 模式

HomeAtlas 支持几种编排路径：

- `HOME_ATLAS_AGENT_MODE=rules`：确定性的关键词/正则路由器，不需要 LLM key。
- `HOME_ATLAS_AGENT_MODE=ai`：Pydantic AI 父 Agent 委托给易耗品、卡片/证件或设备子 Agent。
- `HOME_ATLAS_AGENT_MODE=auto`：当 `HOME_ATLAS_LLM_API_KEY` 或 provider key 存在时使用 AI；否则向 Hermes 返回配置提醒，而不是静默降级。

在 `.env` 中填写下面配置，即可启用 Pydantic AI 委托：

```bash
HOME_ATLAS_LLM_MODEL=deepseek:deepseek-chat
HOME_ATLAS_LLM_API_KEY=...
```

如果你明确想使用不依赖 LLM 的确定性关键词路由器，请设置：

```bash
HOME_ATLAS_AGENT_MODE=rules
```

模型值和其它运行时配置一起放在 `.env` 中。`home_atlas/llm_config.py` 只定义环境变量名和 DeepSeek provider key 映射。

裸 DeepSeek 模型名，例如 `deepseek-v4-flash`，会在运行时规范化为 Pydantic AI 的 provider 形式：`deepseek:deepseek-v4-flash`。

## 家庭服务器进程

### Docker Compose

接近生产形态的 Compose 栈会同时运行 PostgreSQL 和 HomeAtlas MCP 服务。PostgreSQL 容器只在 Compose 内部网络中可访问。

```bash
docker compose up -d postgres
docker compose build home_atlas
docker compose run --rm home_atlas python -m home_atlas.cli init-db
docker compose up -d home_atlas
docker logs homeatlas-service --tail 20
```

拉取包含新迁移的代码后，也要执行同样的 `compose run --rm home_atlas python -m home_atlas.cli init-db` 步骤。如果已有部署是由旧的 `create_all` 快照创建的，请在启动新服务前迁移或重建数据库；否则 schema 闸门会有意阻止服务启动。

### launchd

launchd 模板位于 `deploy/launchd/com.homeatlas.server.plist`。它运行：

```bash
/path/to/HomeAtlas/.venv/bin/python -m home_atlas.mcp_server
```

同时设置 `WorkingDirectory=/path/to/HomeAtlas`，所以服务会读取真实本地项目里的 `.env`。

在家庭服务器 Mac 上安装：

```bash
mkdir -p logs
uv run python -m home_atlas.cli init-db
cp deploy/launchd/com.homeatlas.server.plist ~/Library/LaunchAgents/com.homeatlas.server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.homeatlas.server.plist
launchctl kickstart -k gui/$(id -u)/com.homeatlas.server
launchctl print gui/$(id -u)/com.homeatlas.server
```

停止服务：

```bash
launchctl bootout gui/$(id -u)/com.homeatlas.server
```

## 备份

对于 Docker Compose 部署，PostgreSQL 不暴露到宿主机。请在 PostgreSQL 容器内运行 `pg_dump`，然后把 dump 文件复制出来：

```bash
mkdir -p backups
docker exec homeatlas-postgres pg_dump -U home_atlas -d home_atlas -Fc -f /tmp/ha.dump
docker cp homeatlas-postgres:/tmp/ha.dump ./backups/home_atlas-$(date +%Y%m%d-%H%M%S).dump
```

如果你直接在家庭服务器 Mac 上管理 PostgreSQL，HomeAtlas 也封装了 PostgreSQL 原生备份工具。在这种模式下，宿主机必须安装 `pg_dump` 和 `pg_restore`，并且它们要在 `PATH` 中可用。

```bash
uv run python -m home_atlas.cli backup-db --output backups/home_atlas-$(date +%Y%m%d-%H%M%S).dump
uv run python -m home_atlas.cli verify-backup backups/<backup-file>.dump
```

`verify-backup` 会创建一个临时 PostgreSQL 数据库，把 dump 恢复进去，检查 `item` 和 `event` 数量，然后删除这个临时数据库。

## PostgreSQL 集成测试

并发 PostgreSQL 写入由一个可选集成测试覆盖：

```bash
HOME_ATLAS_INTEGRATION_DATABASE_URL='postgresql+psycopg://home_atlas:<password>@localhost:5432/home_atlas' \
  uv run pytest tests/test_postgres_integration.py
```

这些测试会把多个物品并发写入同一个新位置；当 PostgreSQL 已配置时，还会并发更新同一个物品，以验证审计版本保持唯一且有序。

## Hermes 提醒

使用 `deploy/hermes/list_expiring_reminder.md` 配置 Hermes 定时提醒，让它调用：

```text
哪些物品 14 天内临期或待续费？
```

## 本地 HTTP 冒烟测试 Runner

这个标准库 runner 刻意保持很小，适合在接入完整 MCP 部署前使用。它使用和 CLI 相同的 `HOME_ATLAS_DATABASE_URL` 和 token map：

```bash
uv run python -m home_atlas.cli init-db
uv run python -m home_atlas.http_server
```

然后调用：

```bash
curl -X POST http://localhost:8080/mcp \
  -H 'Authorization: Bearer replace-with-token-1' \
  -H 'Content-Type: application/json' \
  -d '{"request":"把护照放进保险柜抽屉"}'
```

## 设计流程

输入会按下面流程流转：

1. `home_atlas.orchestrator.home_atlas()` 对自然语言请求分类。
2. 被选中的领域工具调用由 Registry 驱动的 dispatcher。
3. dispatcher 校验参数、RBAC、确认信息，并调用 Action。
4. 每个 Action 负责校验、写入对象表、记录一个 `Event`；EventBus handlers 只会在 commit 成功后运行。
5. Read Functions 注册在 Ontology Registry 中，并返回适合 MCP 响应的安全字典。

示例代码路径：

```python
result = home_atlas("把护照放进保险柜抽屉", session, actor_id)
```

这会路由到卡片/证件领域，创建或复用位置，通过 `AddItem` 插入物品，并写入一个带有已解析操作者的 `Event`。

## 剩余生产化工作

- 运行双 Mac Hermes 验证：token A 写入，token B 读取，审计结果显示原始操作者。
- 在家庭服务器 Mac 上安装 launchd plist。
- 在家庭服务器 Mac 上安装 `pg_dump`/`pg_restore`，并运行备份验证。
- 在真实 Hermes 客户端上配置 Hermes 定时提醒。
