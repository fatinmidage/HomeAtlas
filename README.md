# HomeAtlas

HomeAtlas 是一个家庭物品库存服务，用来记录家里的东西放在哪里、谁动过、哪些东西快过期或要续费。

它主要给 Hermes 使用：Hermes 通过一个 MCP 工具 `home_atlas(request)` 把中文请求发给 HomeAtlas，HomeAtlas 负责落库、权限校验和审计记录。

## 你能用它做什么

| 场景 | 示例 |
| --- | --- |
| 记录物品位置 | `把护照放进保险柜抽屉` |
| 查询物品位置 | `护照在哪？` |
| 查询操作记录 | `上次谁动了护照？` |
| 临期提醒 | `哪些物品 14 天内临期或待续费？` |
| 多人审计 | 不同 Hermes 客户端使用不同 token，服务端自动识别操作者 |

## 推荐部署方式

推荐使用 Docker Compose 启动：

- `postgres`：保存家庭物品数据。
- `home_atlas`：提供 MCP HTTP 服务，默认监听 `8080` 端口。

不推荐把长期数据放在本地 SQLite 里；SQLite 只适合临时开发和单元测试。

## 1. 拉取项目

```bash
cd /Users/wuyingheng/项目
git clone git@github.com:fatinmidage/HomeAtlas.git
cd HomeAtlas
```

## 2. 配置 `.env`

先复制模板：

```bash
cp .env.example .env
```

然后编辑 `.env`，至少确认这些值：

| 配置项 | 必填 | 说明 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | 是 | PostgreSQL 主用户密码 |
| `HOME_ATLAS_READONLY_PASSWORD` | 是 | PostgreSQL 只读用户密码 |
| `HOME_ATLAS_TOKEN_MAP` | 是 | token 到家庭成员姓名的映射 |
| `HOME_ATLAS_ADMINS` | 建议 | 管理员姓名，必须匹配 `HOME_ATLAS_TOKEN_MAP` 里的姓名 |
| `HOME_ATLAS_AGENT_MODE` | 是 | 没有 LLM key 时建议设为 `rules` |
| `HOME_ATLAS_PORT` | 可选 | 默认 `8080` |
| `HOME_ATLAS_LLM_MODEL` | 可选 | AI 模式使用，例如 `deepseek:deepseek-chat` |
| `HOME_ATLAS_LLM_API_KEY` | 可选 | AI 模式才需要 |

示例：

```env
POSTGRES_PASSWORD=replace-with-a-strong-password
HOME_ATLAS_READONLY_PASSWORD=replace-with-another-strong-password

HOME_ATLAS_TOKEN_MAP={"replace-with-token-1":"你","replace-with-token-2":"配偶"}
HOME_ATLAS_ADMINS=你
HOME_ATLAS_AGENT_MODE=rules
HOME_ATLAS_PORT=8080

HOME_ATLAS_LLM_MODEL=deepseek:deepseek-chat
HOME_ATLAS_LLM_API_KEY=
HOME_ATLAS_MCP_ISSUER_URL=http://localhost:8080
HOME_ATLAS_MCP_RESOURCE_SERVER_URL=http://localhost:8080/mcp
```

注意：

- `HOME_ATLAS_TOKEN_MAP` 里的 token 就是 Hermes 调用 MCP 时使用的 Bearer token。
- 不要把真实 token、密码提交到 Git。
- 如果 `HOME_ATLAS_AGENT_MODE=auto` 但没有配置 LLM key，Hermes 会收到配置提醒；想先稳定使用，设为 `rules`。

## 3. 启动服务

```bash
docker compose up -d postgres
docker compose build home_atlas
docker compose run --rm home_atlas python -m home_atlas.interfaces.cli init-db
docker compose up -d home_atlas
```

每次拉取了包含数据库迁移的新代码后，也要重新执行：

```bash
docker compose run --rm home_atlas python -m home_atlas.interfaces.cli init-db
```

## 4. 验证服务

查看容器：

```bash
docker compose ps
```

查看 HomeAtlas 日志：

```bash
docker logs homeatlas-service --tail 40
```

检查数据库连接：

```bash
docker compose run --rm home_atlas python -m home_atlas.interfaces.cli doctor
```

检查 MCP 服务是否在线：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/mcp
```

如果返回 `401`，这是正常结果：说明服务在线，并且 Bearer 认证正在生效。

## 5. 配置 Hermes MCP

把 HomeAtlas 加到 Hermes 的 MCP 配置里。推荐用 Hermes CLI 写入配置：

```bash
hermes config set mcp_servers.home_atlas.url "http://localhost:8080/mcp"
hermes config set mcp_servers.home_atlas.headers.Authorization "Bearer replace-with-token-1"
```

如果 Hermes 不在同一台机器上，把 `localhost` 换成运行 HomeAtlas 的家庭服务器局域网 IP：

```bash
hermes config set mcp_servers.home_atlas.url "http://<家庭服务器局域网IP>:8080/mcp"
```

也可以手动编辑 Hermes 配置，形态如下：

```yaml
mcp_servers:
  home_atlas:
    url: "http://localhost:8080/mcp"
    headers:
      Authorization: "Bearer replace-with-token-1"
```

参考文件：

- `deploy/hermes/mcp.yaml.example`

验证 MCP 连接：

```bash
hermes mcp list
hermes mcp test home_atlas
```

验证通过后，重启 Hermes 或开新会话，让它重新加载 MCP server。

重要限制：

- `Authorization` 里的 token 必须存在于 `.env` 的 `HOME_ATLAS_TOKEN_MAP` 中。
- 不要使用 `hermes mcp add` 这类交互式命令让 Agent 代填；用上面的 `hermes config set` 更稳定。
- Hermes Agent 通常不能直接改 `~/.hermes/config.yaml` 这类安全配置文件；请自己运行 Hermes 配置命令或手动编辑。

## 6. 安装 Hermes Skill

HomeAtlas 的 Hermes Skill 在：

```text
deploy/hermes/skills/home-atlas/SKILL.md
```

如果要手动安装到当前用户的 Hermes skills 目录，可以执行：

```bash
mkdir -p ~/.hermes/skills/home-atlas
cp deploy/hermes/skills/home-atlas/SKILL.md ~/.hermes/skills/home-atlas/SKILL.md
```

安装后可以检查：

```bash
hermes skills list
hermes skills check
```

这个 Skill 的作用是告诉 Hermes：

- 什么时候该调用 HomeAtlas。
- 读/模糊查询调用 `home_atlas(request)`。
- 明确写入调用结构化工具：`search_items`、`add_item`、`move_item`、`update_item`、`discard_item`。
- 不要绕过 MCP 直接读数据库。
- 不要把完整银行卡号、CVV 等敏感信息传给服务。

安装后，在 Hermes 里确认能看到类似下面的工具：

```text
mcp_home_atlas_home_atlas
mcp_home_atlas_search_items
mcp_home_atlas_add_item
mcp_home_atlas_move_item
mcp_home_atlas_update_item
mcp_home_atlas_discard_item
```

然后就可以直接说：

```text
把护照放进保险柜抽屉
护照在哪？
上次谁动了护照？
哪些物品 14 天内临期或待续费？
```

## 7. 可选：手动跑一次写入测试

这个命令会真的往数据库写入测试物品，只在你接受测试数据时运行：

```bash
docker compose run --rm home_atlas python -m home_atlas.interfaces.cli smoke \
  --token replace-with-token-1 \
  --item 测试护照 \
  --location 测试保险柜
```

双 token 审计测试：

```bash
docker compose run --rm home_atlas python -m home_atlas.interfaces.cli dual-smoke \
  --writer-token replace-with-token-1 \
  --reader-token replace-with-token-2 \
  --item 双端烟测护照 \
  --location 双端烟测保险柜
```

## 常用运维命令

| 目的 | 命令 |
| --- | --- |
| 查看服务状态 | `docker compose ps` |
| 看 HomeAtlas 日志 | `docker logs homeatlas-service --tail 40` |
| 看 Postgres 日志 | `docker logs homeatlas-postgres --tail 40` |
| 重新跑迁移 | `docker compose run --rm home_atlas python -m home_atlas.interfaces.cli init-db` |
| 停止服务 | `docker compose down` |
| 重新构建服务镜像 | `docker compose build home_atlas` |

## 备份

Docker Compose 部署时，PostgreSQL 不暴露到宿主机。备份可以这样做：

```bash
mkdir -p backups
docker exec homeatlas-postgres pg_dump -U home_atlas -d home_atlas -Fc -f /tmp/ha.dump
docker cp homeatlas-postgres:/tmp/ha.dump ./backups/home_atlas-$(date +%Y%m%d-%H%M%S).dump
```

## 排错

| 现象 | 检查 |
| --- | --- |
| `curl /mcp` 返回 `401` | 正常，表示服务在线但需要 Bearer token |
| Hermes 看不到 `mcp_home_atlas_home_atlas` | 检查 Hermes MCP 配置，确认改完后已重启 Hermes |
| Hermes 认证失败 | 检查 Hermes 配置里的 token 是否存在于 `.env` 的 `HOME_ATLAS_TOKEN_MAP` |
| 服务启动失败 | 先看 `docker logs homeatlas-service --tail 40` |
| 数据库连接失败 | 运行 `docker compose run --rm home_atlas python -m home_atlas.interfaces.cli doctor` |
| 拉新代码后启动失败 | 重新执行 `init-db` 跑迁移 |

## 本地测试

单元测试不需要 PostgreSQL，会使用内存 SQLite：

```bash
uv run pytest
```

## 项目结构

| 目录 | 作用 |
| --- | --- |
| `home_atlas/domain/` | 数据模型、Ontology、属性 schema |
| `home_atlas/app/` | 业务动作、自然语言路由、工具调度 |
| `home_atlas/infra/` | 数据库、迁移检查、备份、事件 |
| `home_atlas/interfaces/` | CLI、MCP server、HTTP runner、REST API |
| `deploy/hermes/` | Hermes MCP 示例、Skill、提醒模板 |
| `migrations/` | Alembic 数据库迁移 |
