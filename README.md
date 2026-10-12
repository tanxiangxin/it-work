# 校园 IT 知识库客服与工单助手

面向个人项目的全栈原型：管理员上传资料，学生提问并查看来源；问题未解决时，确认工单草稿，管理员人工回复和处理，学生确认关闭。

默认使用明确标注的 **Mock 模型**，不需要云端密钥。模拟问答用于验收产品流程，不能作为真实 AI 准确率的依据。

## 启动

需要 Docker Engine / Docker Desktop 与 Compose v2。Windows 使用 Linux containers；先打开 Docker Desktop 并等待引擎就绪。CLI 安装成功不代表引擎已经启动。目标环境的实际验收进度参见 [验证记录](docs/verification.md)。

在 PowerShell 中：

也可在 Docker Desktop 的 Linux 引擎就绪后运行 `powershell -File scripts/start.ps1`。脚本会构建服务、初始化演示账号与资料并检查就绪状态；加 `-Test` 可同时运行后端容器测试。脚本不会覆盖已有 `.env` 或密码。未显式指定远程连接且当前为 default 时，脚本优先使用已存在的 desktop-linux 连接；自动补齐当前进程的 Docker 凭证助手 PATH，无需修改系统环境变量。

```powershell
Set-Location 'D:\vibe coding\ai-01'
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 使用自带的随机配置；如复制模板，需要修改密码，数据库密码同时写入 DATABASE_URL。
docker compose up -d --build --wait
docker compose exec api python -m app.cli seed
# 可选：导入自编的演示资料
docker compose exec api python -m app.cli seed-documents
```

访问 **http://localhost:8080**。学生账号 `student@example.test`，管理员账号 `admin@example.test`；密码分别使用 `.env` 的 `DEMO_STUDENT_PASSWORD` 和 `DEMO_ADMIN_PASSWORD`。

本次已生成本地 `.env` 并设置随机密码；已有文件时跳过上面的复制步骤。密码请在本地文件查看，不要提交 Git。新克隆可运行 `python scripts/init_env.py` 一次性生成随机配置，已有 `.env` 不会被覆盖。

初始化命令幂等，已有账号密码不会被覆盖。资料初始化也会跳过同名未删除文档；重新导入失败资料、切换模型或更新内容时使用管理界面的重试或版本更新。

```powershell
docker compose ps
docker compose logs --tail 100 api worker scheduler
docker compose --profile test run --build --rm tests
docker compose down
```

停止后数据库、上传文件和 Redis 使用持久化卷保存。不要使用 `down -v` 保留数据。

## 代码结构

```text
backend/app/          API、权限、模型接口、检索、解析、任务与业务
backend/migrations/  固定 Alembic 数据库版本
backend/tests/       单元、权限、任务、模型故障与工单集成测试
frontend/src/        React 页面、TanStack Query、SSE 客户端
frontend/e2e/        Playwright 管理员与学生完整流程
deploy/              Nginx 同源反向代理
samples/             自编校园网络、VPN、账号及管理员专用资料
scripts/             重启持久化检查、真实模型验收工具
docs/                架构、演示、部署与验证记录
.github/workflows/   PostgreSQL/Redis/Compose/浏览器验证流水线
```

后端：Python 3.12、FastAPI、SQLAlchemy、Alembic、PostgreSQL 16 / pgvector、Celery / Redis。前端：React、TypeScript、Vite、Ant Design、TanStack Query。检索：精确向量 + jieba 中文 BM25 + RRF（60），最多五个分块；首版只运行一个 API 进程。

Python 依赖由 `backend/uv.lock` 固定；前端提供 `frontend/pnpm-lock.yaml` 和早期验证使用的 `package-lock.json`。pnpm 锁文件原由 npm 依赖图转换生成，现已通过 Docker Linux 与本机 frozen 安装、正式容器生产构建。原生 PostgreSQL/Redis 后端 26 项测试、浏览器完整流程和重启持久化已通过，边界及演示账号待恢复事项见 [目标环境验收](docs/target-verification.md)。

## 阅读顺序

新增 [校园通知、个人待办与学习资料助手](docs/campus-learning.md)：管理员核对通知后发布，学生订阅、收藏并确认加入待办，消息中心提醒；个人课程资料支持带引用问答、复习提纲与练习，资料与历史仅本人可访问。

湖南工业大学师生服务资料见 [湖工大知识库](docs/hut-knowledge.md)：18个官方公开来源主题，覆盖教学、生活、学工与信息服务，保留日期和来源，提供导入及问答验证脚本。

已增加普通对话：问候、能力介绍和通用知识直接回复；校园专属问题继续检索并校验引用。页面区分“普通回复 · 未查询知识库”和“知识库回答”，验证方法见 [普通对话回归](docs/conversation-validation.md)。

新增 [检索质量对比工具](docs/retrieval-evaluation.md) 与 [真实对比结果](docs/retrieval-results.md)：21 题各重复 3 次，同一 BGE-M3 向量比较 vector / hybrid，记录来源、Recall、MRR、权限与耗时；不调用聊天模型或改动线上检索模式。

当前模型配置：DeepSeek `deepseek-flash` 回答 + 本地 Docker CPU `BAAI/bge-m3` 1024 维嵌入。部署与验证见 [BGE-M3 接入](docs/bge-m3-setup.md)，此前 deepseek-embedding 返回 404 的结果仅作为历史记录。

1. [演示脚本](docs/demo.md)：完整流程和失败场景。
2. [架构与实现](docs/architecture.md)：权限、发布、检索、SSE、幂等和状态规则。
3. [开发与部署](docs/operations.md)：本地开发、测试、备份恢复、模型配置和排错。
4. [验收记录](docs/verification.md)：已经运行与尚未运行的检查。

没有实现学校统一认证、邮件、OCR、多部门、SLA 或自动处理工单。当前已启用 DeepSeek + 本地 BGE-M3 真实模式，四份演示资料真实索引及五题冒烟验证通过，见 [真实模型记录](docs/real-results.md)；尚未开展大规模问答效果与成本评测。

2026-10-10 当前配置为 DeepSeek V4.1 Flash（`deepseek-flash`）回答与本地 Docker CPU BGE-M3（`BAAI/bge-m3`）嵌入，见 [BGE-M3 接入步骤](docs/bge-m3-setup.md)。原 deepseek-embedding 接口返回 404，已替换；OpenAI 配置模板保留为可选方案。
