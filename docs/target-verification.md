# Docker 目标环境验收（2026-10-09）

环境：Docker Desktop 4.94.0，CLI 29.8.2，WSL 2.6.3；desktop-linux 连接。默认 Mock 模式，没有调用真实供应商。

2026-10-10 更新：OpenAI 接入准备新增 10 项测试，完整后端回归 **36 passed**；Ruff 与 27 个文件的格式检查通过。离线预检明确报告两个密钥缺失；真实评测在当前 Mock 模式下于登录前拒绝执行，没有发起云端模型调用。M6 继续待验收，步骤见 openai-setup.md。

同日部署发现 API 重建后 Nginx 缓存旧上游地址导致 502。已使用 Docker DNS、带 zone 的 resolve upstream 自动刷新 API/web 地址；nginx -t 通过，重新加载后公网入口（仅本机绑定）/api/v1/system 与健康检查恢复 200。启动脚本增加有限重试以等待 DNS 刷新。依据 Nginx 1.28 支持的 [upstream resolve](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#server) 实现。

| 检查 | 结果 |
|---|---|
| Compose 构建、迁移与启动 | 通过：PostgreSQL 16 / pgvector 0.8.1、Redis 7.2.12、Python 3.12.14 API、Celery Worker、Beat、前端与 Nginx 网关 |
| 原生数据库 / Redis 后端测试 | **26 passed，无跳过**，含并发提交和真实 broker 测试 |
| 测试 schema 隔离回归 | 通过：测试前后已有演示账号和已发布文档摘要不变 |
| 浏览器完整流程 | **1 passed**：实际 Compose API、Worker、Redis、数据库；Chrome / Playwright 1.64.0 |
| pnpm frozen 安装 | 通过：Docker Linux 和本机普通执行环境，pnpm 10.33.0 |
| 前端类型检查、生产构建 | 通过：正式 Dockerfile 的 tsc --noEmit / Vite 7.3.7，不使用替代路径配置 |
| uv frozen 安装 | 通过：正式 Dockerfile 安装运行与测试依赖 |
| 重启持久化 | 通过：重启 API、Worker、Beat、PostgreSQL、Redis 后，账号、文档原文件、会话、工单与回复可访问 |

浏览器流程：管理员上传 MD → Celery 发布 → 学生提问并打开来源 → 编辑草稿、明确建单 → 管理员回复并解决 → 学生关闭。业务测试 12.2 秒，总测试 13.6 秒，仅代表本次 Mock 流程，不代表真实模型延迟。截图：工作区 `work/docker-validation/student-ticket.png`。

## 本次修复

- Desktop 未运行、default 引擎管道不存在：启动 Desktop；启动脚本在没有显式远程配置且使用 default 时选择已有 desktop-linux，不改变全局配置。
- 当前终端缺少凭证助手 PATH：为启动脚本进程补齐 Docker 工具目录。
- 测试容器模块导入失败：改为 python -m pytest，构建排除各级 __pycache__ / pyc。
- Windows PowerShell 5.1 健康检查解析失败：增加 UseBasicParsing。
- 测试隔离缺陷：原测试误读 public.alembic_version，跳过测试 schema 建表，随后测试清理回落到 public。现在迁移版本表固定在当前 schema，创建后断言所有业务表确实存在于测试 schema。修复后重复测试并比较应用记录摘要，确认隔离生效。首次存在此缺陷时的测试通过不作为验收依据。

该缺陷曾影响演示数据，四份演示文档已重新导入。2026-10-10 用户确认当前可用，继续保持现有账号状态，不执行密码恢复；账号实际密码与 .env 初始值不同。未删除用户、会话或工单。

M6 仍待真实供应商配置；没有真实模型准确率、成本或延迟结果。备份恢复命令已提供，但尚未进行独立灾难恢复演练；重启持久化不代替备份恢复验证。GitHub Actions 尚未触发。

Vite 的 JS 大小提示约 1.24 MB / gzip 390 KB；FastAPI TestClient 有 httpx 弃用提示，jieba 有旧字符串提示，当前测试和构建通过。
# 2026-10-10 DeepSeek 选型更新验证

当前配置模型 ID 为 `deepseek-v4.1-flash` / `deepseek-embedding`，新增 DeepSeek 请求参数模式与接入说明。Ruff 检查及格式检查通过；PostgreSQL/Redis 容器测试 41 项通过（7.93 秒），包含关闭/开启思考的参数合同、OpenAI 兼容回归与嵌入维度错误拒绝。首次测试构建包含修改前的 OpenAI 测试配置，受环境变量影响有一项失败；明确隔离测试 API style 后重建全部通过。

API、Worker、Scheduler 已重建，首页、`/api/v1/system`、`/api/v1/health/ready` 均 HTTP 200。离线预检提示尚缺聊天/嵌入 API Base 与密钥；保持 Mock，未调用真实供应商。两个用户指定 ID 的实际服务及 1024 维支持仍待确认，M6 未完成真实验收。未修改数据库或账号凭据。
# 2026-10-10 本地 BGE-M3 验证

当前 DeepSeek + Docker CPU BGE-M3 真实模式已启动。模型固定 revision，使用持久化缓存，无公开嵌入端口且不转发旧 API 密钥；真实探针返回 1024 维并通过回答/引用校验。四份演示资料真实索引 ready，五题 SSE 与引用验证完成，无失败；详细模型配置、CPU 2048 token 限制、时间与用量见 `real-results.md`。42 项后端集成测试、Ruff、格式与 PowerShell 启动脚本语法检查通过。首次权重约 2.27 GB，启动脚本新增可配置等待时间。期间 Docker Desktop 停止后已恢复，缓存保留。

# 2026-10-10 检索质量对比阶段

新增权限范围内检索对比接口、21 道标注问题、标准库对比脚本和可复现报告。最终后端容器测试 49 项通过（13.39 秒），覆盖无登录、角色隔离、仅一次嵌入、参数校验、当前版本、删除退出检索、并发知识库变化与指标分母；Ruff 和格式检查通过。

真实学生范围内 21/21 题完成，每题 3 次（另有 1 次预热），重复排名稳定，没有禁止文档命中；17 正例的 Recall@3 为 vector 94.12% / hybrid 100%，MRR@5 为 0.9559 / 0.9706。原始报告及指标边界见 `retrieval-results.md`。未调用聊天服务、未修改线上 RETRIEVAL_MODE、文档、工单或账号凭据。部署期间 Docker Desktop 退出后已恢复；采样在服务健康后进行，最终报告知识库版本固定。

