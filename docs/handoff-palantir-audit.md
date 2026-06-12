# HomeAtlas 审计 Handoff：Palantir Ontology / AIP 对标（复核版）

> 初审：2026-06-11（基线 bf01dee）。**复核：2026-06-11 晚（HEAD 3987a56）**。
> 复核方法与初审相同：通读 diff、编译 DDL/SQL、一次性 PG16 容器跑完整迁移链 + 集成测试、
> 生产库只读检查。本文档为唯一有效版本。

---

## 1. 当前状态一句话

**代码层 9 项修复全部落地且经实测验证（P0×4 + P1×5），本轮又完成 2 项 P2 低风险代码修复、README 更新与生产库收编；
当前无硬阻塞。**

| 板块 | 状态 |
|---|---|
| P0-1~4（schema 治理 / REST） | ✅ 已修复，已验证 |
| P1-1~5（masking / 治理入口 / 时区 / 确定性 / 过滤语义） | ✅ 已修复，已验证 |
| 生产库收编（原 Commit 4） | ✅ 已完成，生产库已重建为 Alembic schema |
| README 与部署文档 | ✅ 已更新，补充 init-db 硬顺序与 Docker Compose 部署 |
| P2 备选项 | 🟡 部分完成（#12/#13 已修复；其余仍可选） |

---

## 2. 已完成项与验证记录（复核确认）

| # | 修复 | Commit | 复核验证方式与结果 |
|---|---|---|---|
| P0-1 | JSON→JSONB（`with_variant`），重写迁移 0003（先 ALTER TYPE 再建 GIN），`property_filter` 查询简化 | 4909ab8 | DDL 编译 `properties JSONB NOT NULL` ✓；一次性 PG16 容器 `alembic upgrade head` **全链通过** ✓；GIN 索引存在 ✓ |
| P0-2 | 新迁移 0008 `ALTER TYPE eventaction ADD VALUE 'SET_PERSON_ROLE'` | 4909ab8 | 迁移后 `pg_enum` 为 8 值 ✓；集成测试 `set_person_role` 在迁移库上成功 ✓ |
| P0-3 | 服务入口删 `create_all`；`require_schema_version` 不匹配即拒绝启动；PG 集成测试改走 alembic 建表（临时库建/删） | 4909ab8 | 对未初始化库 `build_rest_app` 抛 RuntimeError ✓（实测）；集成测试 3/3 过 ✓；`CURRENT_SCHEMA_VERSION`=2 与迁移 0009 写入值一致 ✓ |
| P0-4 | REST 跳过注册 `item_kind=None` 且非 Item 的对象端点；列表 handler 改走 `dispatch_function` | 4909ab8 | 实测路由清单：仅 Item + 9 子类型，无 Person/Location/Event ✓ |
| P1-1 | links.py 全面 ORM 化并复用 `_item_dict`/`_masked_snapshot`；`_tool_result` 改用 `_masked_properties` | d491f42 | 新增 2 个泄密回归测试过 ✓；traverse 输出 Event before/after 已掩码 ✓ |
| P1-2 | agents/orchestrator/toolsets/cli 读路径统一 `dispatch_function` | 0d8bdb4 | grep 全包零绕过（仅剩 Registry `implementation=` 声明，即合法单一来源）✓ |
| P1-3 | 全部时间戳列 `DateTime(timezone=True)` + 迁移 0009（timestamptz + 版本 bump 到 2）；输出统一 `utc_isoformat`（SQLite naive 兜底） | 0274248 | DDL 编译 `TIMESTAMP WITH TIME ZONE` ✓；SQLite 侧不变 ✓ |
| P1-4 | `ObjectTypeDef` 增加 `primary_key`/`title_property`；where_is/upsert 按 `updated_at desc, id desc` 确定性排序，多命中返回 `match_note` | 3987a56 | 新增同名物品测试 ✓ |
| P1-5 | `property_filter` 锁定"顶层标量等值"契约：嵌套值直接拒绝，双后端同语义 + 测试 | 3987a56 | 拒绝嵌套测试 ✓ + PG 集成过滤用例 ✓ |

测试基线：**116 passed, 5 skipped**（初审时 108+4）；
PG 集成（一次性容器）：**3/3 passed**，含"alembic 建表 + JSONB 过滤 + SetPersonRole"端到端用例。

---

## 3. ✅ 整改一：生产库收编（已完成）

### 原现状（2026-06-11 复核实查）

生产 `homeatlas-postgres` 仍是旧 `create_all` 快照：`properties/before/after` 为 `json`、
`eventaction` 7 值、时间戳无时区、**无 `alembic_version`、无 `schema_metadata`**；
数据仅 2 person / 2 item / 2 event。`homeatlas-service` 容器还在跑旧镜像。

**新行为提醒**：修复后的代码会在启动时 `require_schema_version` 失败即退出。
如果现在直接 `docker compose build && up`，服务会**循环崩溃**（`restart: unless-stopped`）——
这是设计行为（fail fast），收编必须先行。另外 compose 内 postgres **无宿主端口映射**，
所有数据库操作都要经 `docker exec` / `docker compose run` 在容器内进行。

### 方案 A（推荐）：备份 → 删库重建 → init-db → 重录

```bash
cd /path/to/HomeAtlas   # 家庭服务器上的部署目录

# 1) 备份（虽然只有 6 行数据，习惯不能省）
docker exec homeatlas-postgres pg_dump -U home_atlas -d home_atlas -Fc -f /tmp/pre-reonboard.dump
docker cp homeatlas-postgres:/tmp/pre-reonboard.dump ./backups/pre-reonboard-$(date +%Y%m%d).dump

# 2) 抄录现有物品（人工重录的依据）
docker exec homeatlas-postgres psql -U home_atlas -d home_atlas -c \
  "SELECT i.name, l.name AS location, i.kind, i.properties FROM item i JOIN location l ON l.id=i.location_id;"

# 3) 停服务，删库重建（terminate 残留连接后 drop）
docker compose stop home_atlas
docker exec homeatlas-postgres psql -U home_atlas -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='home_atlas';" -c \
  "DROP DATABASE home_atlas;" -c "CREATE DATABASE home_atlas;"

# 4) 重新授权 readonly 角色（角色是集群级的还在，但库级 GRANT 随删库丢失；
#    init_readonly_role.sh 只在数据卷首次初始化时运行，不会自动重跑）
docker exec homeatlas-postgres psql -U home_atlas -d home_atlas -c \
  "GRANT CONNECT ON DATABASE home_atlas TO home_atlas_readonly;" -c \
  "GRANT USAGE ON SCHEMA public TO home_atlas_readonly;" -c \
  "ALTER DEFAULT PRIVILEGES FOR ROLE home_atlas IN SCHEMA public GRANT SELECT ON TABLES TO home_atlas_readonly;"

# 5) 构建新镜像并用它跑迁移（一次性容器，复用 compose 网络与环境变量）
docker compose build home_atlas
docker compose run --rm home_atlas python -m home_atlas.cli init-db

# 6) 启动并核验
docker compose up -d home_atlas
docker logs homeatlas-service --tail 20        # 应无 schema 警告、无重启循环
docker exec homeatlas-postgres psql -U home_atlas -d home_atlas \
  -c "SELECT version_num FROM alembic_version;" \
  -c "SELECT * FROM schema_metadata;"           # 0009 / version 2

# 7) 经 Hermes（或 curl /mcp）重录第 2 步抄下的物品，并跑双端验证
#    期望：write 落库、where 答对、audit 显示写入者
```

### 方案 B（不推荐，仅当流水必须保留）

对存量库手工补差：`ALTER TYPE ... ADD VALUE`、三列 `ALTER ... TYPE jsonb`、五列
`ALTER ... TYPE timestamptz`、建 GIN 索引、建 `schema_metadata`（值 '2'）、
`alembic stamp head`。**风险**：旧库建于约两天前的旧代码，`event.version`、`person.roles`、
`uq_event_item_version` 等后加列/索引是否存在未逐一核实，每缺一项就是一次启动失败排查。
6 行数据不值得，列在这里只为完整性。

### 验证标准（收编完成的定义）

- [x] `alembic_version` = `0009_timezone_aware_timestamps`，`schema_metadata` = 2
- [x] 服务稳定运行（无 crash loop），日志无 schema 警告
- [x] 双端验证通过：A token 写、B token 读、DB `last_touched` 事件 actor 显示 A
- [x] `SetPersonRole` 在生产可执行并产生 Event（旧库上这是必炸路径）

### 执行记录（2026-06-11）

| 步骤 | 结果 |
|---|---|
| 备份 | `backups/pre-reonboard-20260611.dump`，`pg_restore -l` 可识别 |
| 旧数据抄录 | `backups/pre-reonboard-20260611-items.tsv` |
| 删库重建 | `DROP DATABASE home_atlas` → `CREATE DATABASE home_atlas` |
| 迁移 | `docker compose run --rm home_atlas python -m home_atlas.cli init-db` 全链 0001→0009 成功 |
| 重录 | `鸡腿软骨 / 冰箱冷冻层`、`豆腐乳 / 厨房柜子` 已重录 |
| 双端验证 | `ok=true`；writer=`你`，reader=`配偶`，Event actor=`你` |
| 管理动作验证 | `SetPersonRole` 成功写入 `SET_PERSON_ROLE` Event |
| 服务状态 | `homeatlas-service` Up；日志显示 Uvicorn 正常启动，无 schema 错误 |

额外修复：`docker-compose.yml` 已补传 `HOME_ATLAS_ADMINS`，否则 `init-db` 看不到 `.env` 中的管理员配置，`SetPersonRole` 会因无人拥有 admin 权限而失败。

---

## 3.1 ✅ 本轮仓库内代码修复（2026-06-11）

| # | 修复 | 验证 |
|---|---|---|
| P2-12 | `_run_alembic_upgrade` 对数据库 URL 中的 `%` 做 configparser 转义，并修复 Alembic env.py 二次回写导致的 `%` 崩溃 | `tests/test_cli.py::test_alembic_upgrade_accepts_percent_encoded_database_url`；`tests/test_cli.py::test_alembic_upgrade_runs_with_percent_in_sqlite_path` |
| P2-13 | `verify_readonly_isolation` 先执行 `SELECT 1` 验证只读连接；连接失败改为 `RuntimeError`，不再伪装成“写入已被拦截” | `tests/test_db_isolation.py::test_verify_raises_when_readonly_database_cannot_connect` |

阶段验证：`uv run pytest -q` → **118 passed, 5 skipped**。

---

## 4. 🟠 整改二：README / 部署文档与新行为脱节

| 位置 | 问题 | 修法 |
|---|---|---|
| README 全文 | ✅ 已补"**先 `init-db` 后启动**"硬顺序；任何入口启动前必须先 `uv run python -m home_atlas.cli init-db` | 已完成 |
| README「Home Server Process」 | ✅ 已增加 Docker Compose 章节：build → `compose run --rm home_atlas python -m home_atlas.cli init-db` → `up -d`；并说明 schema 升级同流程 | 已完成 |
| README「What Is Implemented」 | ✅ 已补 fail-fast 版本门、masking 全出口覆盖、确定性匹配 | 已完成 |
| `docs/handoff-palantir-audit.md`（本文件） | ✅ 本轮已同步；后续收编完成后把第 3 节验证框勾掉 | 已完成 |

---

## 5. 🟡 P2 备选项（全部未动，可选；新增 3 项小发现）

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| 1 | `typed_properties` 不覆盖核心列 | ontology.py | LLM/`/api/ontology` 的 schema 看不到 `expiry_date`；基类型声明核心列 + 子类型拼接 |
| 2 | `parent="Item"` 无继承语义 | ontology.py | 引入 Interface（如 `Expirable`）或把 parent 降级为注释 |
| 3 | submission criteria 不声明式 | actions.py | `quantity>=0` 等上移到 `ActionParameterDef`（min/max/pattern） |
| 4 | AI 模式零 Evals | tests/ | opt-in（有 LLM key 才跑）：固定中文请求集对照 rules 金标准 |
| 5 | `Person.roles` 列表语义从未用到 | actions.py:366 | 简化为单 enum 列 |
| 6 | `schema_version` 双份声明 | ontology.py:157 / schema_migration.py:12 | 本轮已手工同步为 2，但仍是两处；应由一处导出 |
| 7 | `quantity` 用 Float | models.py | `Numeric(10,2)` 更稳 |
| 8 | Event 流水 DB 层可改写 | — | `REVOKE UPDATE, DELETE ON event` 或触发器 |
| 9 | MCP meta token 回退死代码 | mcp_server.py:96-97 | 客户端可控 meta 提供身份，违 on-behalf-of 精神；无调用方，删除即可 |
| 10 | AI 模式静默缺管理动作 | ontology.py | UpdateItem/DiscardItem 无 ai_tools；要么提供带确认门的工具，要么在 instructions 言明 |
| 11 | `Location.name` 全局唯一 | models.py | 记录在案，可接受 |
| 12 | ✅ `_run_alembic_upgrade` / env.py `%` 链路 | cli.py + migrations/env.py | 第三轮发现 env.py 二次回写仍会炸；现已改为直接用 `database_url` 创建 engine，并补真实 SQLite `%` 路径迁移测试 |
| 13 | ✅ `verify_readonly_isolation` 把连接失败计为 blocked | db_isolation.py:41-48 | 已修复：先跑 `SELECT 1`，连接失败直接报配置错误（复核确认 ✓） |
| 14 | 🆕 集成测试临时库无前缀清理 | test_postgres_integration.py | 中途 kill 会留下 `home_atlas_test_*` 孤儿库；低危，知道即可 |

---

## 6. 复核验证记录（2026-06-11，可复跑）

```bash
# 单测基线
uv run pytest -q                      # 116 passed, 5 skipped

# DDL 复核（PG: JSONB + timestamptz；SQLite 不受影响）
uv run python -c "from sqlalchemy.schema import CreateTable; from sqlalchemy.dialects import postgresql; \
  from home_atlas.models import Item; print(CreateTable(Item.__table__).compile(dialect=postgresql.dialect()))"

# 迁移链 + 集成测试（一次性容器，验后已删）
docker run --rm -d --name homeatlas-verify-pg -e POSTGRES_PASSWORD=audit \
  -e POSTGRES_USER=audit -e POSTGRES_DB=audit -p 55432:5432 postgres:16
HOME_ATLAS_DATABASE_URL='postgresql+psycopg://audit:audit@localhost:55432/audit' uv run alembic upgrade head
HOME_ATLAS_INTEGRATION_DATABASE_URL='postgresql+psycopg://audit:audit@localhost:55432/audit' \
  uv run pytest tests/test_postgres_integration.py -v        # 3 passed
# 容器内核验：jsonb / timestamptz / 8 值枚举 / GIN 索引 / schema_metadata=2 / alembic_version=0009 全部 ✓

# fail-fast 行为（未初始化库拒绝启动）
# build_rest_app(Settings(database_url="sqlite:///<新文件>")) → RuntimeError ✓

# 读路径绕过清零
grep -rn "actions\.\(search_items\|list_expiring\|where_is\|last_touched\|recent_activity\)" home_atlas/
# 仅剩 ontology.py 的 implementation= 声明（Registry 单一来源，合法）

# 生产库现状（只读，收编前）
docker exec homeatlas-postgres psql -U home_atlas -d home_atlas -c "..."
# properties=json / eventaction 7 值 / 无 alembic_version / 无 schema_metadata → 待收编
```

---

## 7. 第三轮审计（2026-06-12，HEAD d9f57a7）

> 范围：复核 3 个新 commit（6a21926 / 8aaa94e / d9f57a7）+ 首次通读 backup.py、llm_config.py、
> migrations/env.py、deploy/hermes/、.env.example、仓库卫生（gitignore/dockerignore）。
> 测试基线 **118 passed, 5 skipped**。生产收编以 §3 执行记录为准（未做独立复查，生产容器
> 查询超出代码审计授权范围）。

### 7-1 ✅ P2-12 已修复：`%` 密码场景 env.py 二次回写问题

**证据**（实际执行，非推测）：模拟修复后全链——cli 转义写入 ✓ → env.py:19 `get_main_option`
还原出含裸 `%` 的 URL → **env.py:20 `set_main_option` 原样回写 → configparser `before_set`
直接抛 `ValueError: invalid interpolation syntax ... at position 33`**。
即密码含 `%`（URL 编码 `%25`）时 `init-db` 依然崩溃。

**为什么测试没拦住**：`test_alembic_upgrade_accepts_percent_encoded_database_url` 把
`command.upgrade` mock 掉了，env.py 从未执行——只验证了"cli 写入后能读回"，
没验证 alembic 真实链路。这是本项目已两次出现的复发模式的变体：**修了，但测试没踩真路径**。

**修法**（根治在 env.py，二选一，推荐 ①）：

```python
# ① migrations/env.py — run_migrations_online 绕开 configparser 第二次插值，
#    直接用已还原的 database_url 建 engine；env.py:20 的回写行删除
def run_migrations_online() -> None:
    from sqlalchemy import create_engine
    connectable = create_engine(database_url, poolclass=pool.NullPool)
    ...

# ② 或保留 engine_from_config，回写时转义：
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
```

**配套测试**（真实链路，不 mock）：用含 `%25` 的 SQLite URL（如 tmp 目录名含 `p%ss`）
真跑 `_run_alembic_upgrade`，断言迁移成功且库文件落地。
当前生产密码不含 `%` 时无现实影响，故列 P2 不阻塞；本轮已补真实链路测试防回归。

**本轮处理（2026-06-12）**：`migrations/env.py` 删除 `config.set_main_option` 二次回写，
在线迁移改为 `create_engine(database_url, poolclass=pool.NullPool)`；新增真实链路测试
`tests/test_cli.py::test_alembic_upgrade_runs_with_percent_in_sqlite_path`。阶段验证：
`uv run pytest -q` → **119 passed, 5 skipped**。

### 7-2 ✅ README「Backups」节与 compose 部署不符（已修复）

原 README 仍指导宿主上 `uv run python -m home_atlas.cli backup-db`——compose 的 postgres
**无宿主端口映射**，此命令在唯一的真实部署形态下连不上库（§3 收编时实际用的是
`docker exec homeatlas-postgres pg_dump`）。本轮已在 Backups 节补 compose 形态：

```bash
docker exec homeatlas-postgres pg_dump -U home_atlas -d home_atlas -Fc -f /tmp/ha.dump
docker cp homeatlas-postgres:/tmp/ha.dump ./backups/home_atlas-$(date +%Y%m%d-%H%M%S).dump
```

### 7-3 ✅ 仓库卫生两处小漏（已修复）

| 文件 | 原问题 | 本轮修复 |
|---|---|---|
| .gitignore | 只忽略 `backups/*.dump`，`backups/pre-reonboard-*-items.tsv`（家庭物品抄录）会被 `git add .` 带入仓库 | 已替换为 `backups/` |
| .dockerignore | 未排除 `home_atlas.db`、`logs/`，`COPY . .` 会把本地开发 SQLite 库与日志打进生产镜像 | 已追加 `home_atlas.db`、`logs/` |

### 7-4 ✅ 本轮复核通过的项

| 项 | 结论 |
|---|---|
| P2-13（db_isolation 预检） | 修复正确：`SELECT 1` 失败 → `RuntimeError`，测试覆盖合理 ✓ |
| README init-db 硬顺序 + Docker Compose 章节 + launchd 补步 | 内容准确，与代码行为一致 ✓ |
| docker-compose 补 `HOME_ATLAS_ADMINS`（默认空） | 正确，init-db/seed 能读到管理员 ✓ |
| backup.py（首次通读） | 标识符引用、临时库 terminate+drop、`--clean --if-exists --no-owner` 均无问题 ✓ |
| llm_config.py / deploy/hermes/SKILL.md / .env.example（首次通读） | 无硬编码密钥；SKILL.md 引导用户确认 token 而非绕过脱敏，方向正确 ✓ |
| 测试基线 | 118 passed, 5 skipped ✓ |

### 7-5 本轮待办汇总（已处理）

1. ✅ 修 env.py 的 `%` 链路 + 真实链路测试（§7-1，commit `b5f91f7`）
2. ✅ README Backups 节 compose 化（§7-2）
3. ✅ .gitignore `backups/` 整目录 + .dockerignore 补两行（§7-3）
4. 🟡 其余 P2（#1~#11、#14）维持可选
