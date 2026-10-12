# 开发、部署与运维

## 本地开发

先准备可用的 PostgreSQL 16 + pgvector 和 Redis。优先用 Compose，手动启动开发 API 时需在覆盖文件中临时为 postgres/redis 增加 localhost 绑定端口，或使用独立开发服务。不要直接把数据库和 Redis 端口绑定公网。

后端工作目录 `backend`，Python 3.12：

```powershell
uv sync --frozen
$env:DATABASE_URL='postgresql+psycopg://campus:你的密码@127.0.0.1:5432/campus'
$env:REDIS_URL='redis://127.0.0.1:6379/0'
$env:STORAGE_DIR='../data/files'
$env:PUBLIC_ORIGIN='http://localhost:5173'
uv run alembic upgrade head
uv run python -m app.cli seed
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

其他后端终端也需要设置上述环境变量，然后分别运行 `uv run celery -A app.jobs.celery worker --loglevel=INFO --concurrency=1` 和 `uv run celery -A app.jobs.celery beat --loglevel=INFO`。Windows 原生 Celery 开发应使用 `--pool=solo`，部署使用 Linux 容器。前端工作目录 `frontend`，执行 `pnpm install --frozen-lockfile`、`pnpm dev`。统一使用 `http://localhost:5173`，不要混用 127.0.0.1 与 localhost。Vite 已配置 `/api` 代理。

API OpenAPI：开发环境 `http://127.0.0.1:8000/docs`。在线程中执行同步数据库访问，避免 SSE 查询阻塞 API 事件循环；初版无多进程部署支持。

## 测试

单元测试不需要云端模型或数据库；数据库测试在未配置 TEST_DATABASE_URL 时明确跳过。集成测试创建独立随机 schema，执行正式 Alembic 迁移，再清理该 schema，不清空业务 schema。测试必须连接专用测试数据库，并使用专用 Redis 库。

```powershell
# backend 目录
uv run pytest tests/test_units.py -q
$env:TEST_DATABASE_URL='postgresql+psycopg://campus:你的测试密码@127.0.0.1:5432/campus_test'
$env:TEST_REDIS_URL='redis://127.0.0.1:6379/1'
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
```

容器：根目录 `docker compose --profile test run --build --rm tests`，涵盖实际 PostgreSQL/pgvector 和 Redis 派发。浏览器：先启动服务和初始化账号，在 frontend 执行 `pnpm exec playwright install chromium`、设置两个 DEMO_*_PASSWORD，再 `pnpm test:e2e`。测试新增 `e2e-vpn.md` 和一张演示工单；请在测试环境运行。Linux CI 会自动安装浏览器依赖。

自动化验证文件 `.github/workflows/verify.yml` 已配置，但本次未连接仓库或触发远程运行。可将项目推送到你自己的 GitHub 仓库后运行。CI 会检查 frozen 安装、类型、构建、后端故障与权限、真实 Worker 浏览器流程和服务重启持久化。

## 真模型 M6

聊天使用官方 `https://api.deepseek.com/v1` 与 `deepseek-flash`（V4.1 Flash），嵌入使用本地 Docker CPU `BAAI/bge-m3` 1024 维，见 [BGE-M3 接入步骤](bge-m3-setup.md)。DeepSeek 使用 max_tokens，默认关闭思考。当前部署已通过接入探针并启用真实模式，新环境仍先运行 Mock 再验证。

在 `.env` 设置 `MODEL_MODE=real`，分别填写 LLM_API_BASE / KEY / MODEL 和 EMBEDDING_API_BASE / KEY / MODEL。BASE 是 API 前缀，例如 `https://供应商地址/v1`，代码会追加 `/chat/completions` 或 `/embeddings`。需支持 JSON object 输出；响应格式不兼容会明确失败。Embedding 必须返回 1024 维；若模型固定维度且不接受 dimensions 参数，设置 `EMBEDDING_SEND_DIMENSIONS=false`。

配置缺失时启动失败，不降级 Mock。更新配置后重新创建 API、Worker 和 Scheduler：

```powershell
docker compose up -d --force-recreate api worker scheduler
```

使用知识库管理为每份文档重新上传版本。相同原始文件在不同 index_key 下可以建新版本。仅在真实导入成功后发布真实版本；旧 Mock 版本不会参与真实检索。相同模型名但供应商改变模型内部实现时，需要修改 EMBEDDING_MODEL 标识或明确维护版本标识并重新索引。

填写实际配置之后执行 `scripts/evaluate_real.py` 和 `samples/questions.json` 的固定问题集，人工核对来源支持程度，再在 `docs/real-results.md` 记录供应商、模型、文档版本、可回答/拒答、延迟及供应商 Token 用量。脚本只记录接口结果，不自动宣称准确率。当前没有真实服务配置，真实效果保持未验收。

## 部署与备份

当前嵌入使用本地 BGE-M3，Compose 通过 `COMPOSE_PROFILES=bge` 启动独立 CPU 服务，详见 [BGE-M3 接入](bge-m3-setup.md)。`embedding_cache` 保存可重新下载的权重缓存；业务备份仍以数据库和 files 卷为准。

默认网关只绑定 `127.0.0.1:8080`。公网演示应先配置 HTTPS 入口，将 PUBLIC_ORIGIN 改为实际 HTTPS 源、COOKIE_SECURE=true；通过受控代理转发到 8080。文件、数据库、Redis 持久化卷分别为 `campus-it-assistant_files`、`campus-it-assistant_database`、`campus-it-assistant_redis`。模型密钥不要提交 Git。

为保持数据库与文件一致，先停止写入服务，生成数据库备份并打包文件卷。不要使用 PowerShell 的文本重定向处理 PostgreSQL 二进制备份：

```powershell
New-Item -ItemType Directory -Force backups
docker compose stop api worker scheduler
docker compose exec -T postgres pg_dump -U campus -d campus -Fc -f /tmp/campus.dump
docker compose cp postgres:/tmp/campus.dump ./backups/campus.dump
docker run --rm -v campus-it-assistant_files:/data:ro -v "${PWD}/backups:/backup" alpine:3.21.3 tar czf /backup/files.tar.gz -C /data .
docker compose start api worker scheduler
```

恢复到隔离环境并停止写入服务，先复制 dump：`docker compose cp ./backups/campus.dump postgres:/tmp/campus.dump`，然后 `docker compose exec -T postgres pg_restore -U campus -d campus --clean --if-exists /tmp/campus.dump`。恢复文件归档到对应 files 卷，保留相同数据库/文件版本，再启动服务、登录验证来源和下载。恢复命令会覆盖目标数据库中的对象，只对预期恢复目标执行。Redis 队列无需从备份恢复，数据库 queued 状态由调度器恢复。

## 常见问题

| 现象 | 检查 |
|---|---|
| 登录后写请求 403 | PUBLIC_ORIGIN 是否与浏览器协议、主机、端口完全一致 |
| 健康检查 503 | 数据库/Redis、迁移、DATABASE_URL 与密码 |
| 任务长期 queued | Worker、Scheduler 日志；数据库任务会自动补发 |
| OCR_REQUIRED | 首版只处理文本 PDF，转换为可提取文本或 TXT |
| 新版本失败 | 旧版本仍生效，查看版本 error 并重试或重新上传 |
| INDEX_MISMATCH | Worker 模式与任务索引不同，重新上传新版本 |
| EMBEDDING_OUTPUT | 模型是否为 1024 维，dimensions 参数是否支持 |
| MODEL_OUTPUT | Chat Completions 是否支持所要求 JSON 输出 |
| SSE 中断 | 请求可能 interrupted，刷新历史再提问；无断点续传 |
| frozen 安装失败 | 检查依赖锁文件与包管理器版本；不能静默忽略锁文件 |
| API 重建后网关 502 | 网关配置使用 Docker DNS 和 resolve upstream；等待约 5 秒刷新，检查 gateway / api 日志。修改配置后先 nginx -t，再 nginx -s reload |

错误包含 request_id，日志不打印密钥、Cookie 或供应商响应正文。上传文件只通过授权下载接口读取。首版允许历史数据增长；实际长期部署需补充会话/文件清理和运维监控。
