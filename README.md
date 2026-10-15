# 校园 IT 服务台与学习助手

管理员上传知识库资料，学生通过带来源问答寻求帮助；未解决时确认工单，由管理员回复处理并由学生关闭。项目还提供校园通知、个人待办、课程资料问答、复习提纲和练习评分。

**新环境默认 Mock 模式，不需要 API 密钥。** 模拟结果用于验证产品流程，不代表真实 AI 效果。部署步骤以 [三条部署路径](docs/deployment-guide.md) 为准；当前机器的实际结果见 [2026-10-15 验收记录](docs/verification-2026-10-15.md)。

## 首次启动

安装 Docker Desktop，打开并等待 Linux 容器引擎就绪。在项目根目录的 PowerShell 中运行：

```powershell
powershell -File scripts/init-env.ps1
powershell -File scripts/start.ps1 -Test
```

访问 **http://localhost:8080**。学生 `student@example.test`，管理员 `admin@example.test`；初始密码在本地 `.env` 的 `DEMO_STUDENT_PASSWORD`、`DEMO_ADMIN_PASSWORD` 中。配置初始化不会覆盖已有文件，账号初始化不会修改已有密码。不要提交 `.env`。

```powershell
docker compose ps
docker compose logs --tail 100 api worker scheduler
docker compose down
```

数据库、上传文件和 Redis 使用持久化卷保存；停止项目时保留数据卷。

## 真实模型与效果验证

支持 DeepSeek 聊天 + 本地 Docker CPU `BAAI/bge-m3` 1024 维嵌入。先将模型配置和密钥填入本地 `.env`，再执行 `powershell -File scripts/enable-real.ps1`，完成探针检测、模式切换和索引重建。首次模型下载为数 GB。

AI 配置页显示各功能使用的模型、配置来源、连接检测和本人当日用量。个人聊天配置用于知识问答和工单摘要；学习、通知与联网搜索使用服务器配置，向量索引也由服务器统一管理。

[50 题评测集](samples/evaluation-50.json) 提供参考要点、来源及拒答预期，基于自编模拟资料，并非真实校园准确率基准。真实评测、人工核对和费用边界见 [部署指南](docs/deployment-guide.md)。缺少密钥时保留 Mock，不宣称真实模型验收通过。旧环境的模型调用与检索结果保留在历史文档中。

## 验证与运维

```powershell
docker compose --profile test run --build --rm tests
powershell -File scripts/backup.ps1
powershell -File scripts/verify-restore.ps1 -BackupDirectory work/backups/你的备份目录
```

前端以 `frontend/pnpm-lock.yaml` 为唯一安装依据，使用 `pnpm install --frozen-lockfile`；`package-lock.json` 是早期历史文件。Python 依赖由 `backend/uv.lock` 固定。浏览器验收使用 Playwright，命令见 [开发与运维](docs/operations.md)。

长期服务已配置自动重启和日志轮转，登录、AI 调用及上传具有额度和并发保护。价格需管理员自行配置，缺少价格或供应商 Token 用量时费用显示未估算。对外部署需要 HTTPS 和实际来源配置；备份应另存到独立存储。详细参数及恢复边界见 [部署指南](docs/deployment-guide.md)。

## 代码结构

```text
backend/app/          API、权限、模型、检索、后台任务和业务
backend/migrations/  Alembic 数据库迁移
backend/tests/       单元、权限、故障与集成测试
frontend/src/        React 页面与 SSE 客户端
frontend/e2e/        Playwright 浏览器验收
deploy/              Nginx 同源反向代理
samples/             自编示例、校园资料与评测问题
scripts/             启动、配置、评测、备份和隔离恢复
```

后端使用 Python 3.12、FastAPI、PostgreSQL/pgvector、Celery/Redis；前端使用 React、TypeScript、Vite、Ant Design 和 TanStack Query。检索采用向量 + 中文 BM25 + RRF，候选数量由配置控制。当前仍按单 API 进程部署。

## 功能和历史资料

- [校园通知、个人待办与学习资料助手](docs/campus-learning.md)
- [湖南工业大学公开服务知识库](docs/hut-knowledge.md)
- [架构与权限](docs/architecture.md)
- [演示流程](docs/demo.md)
- [检索对比工具](docs/retrieval-evaluation.md) 与 [历史对比结果](docs/retrieval-results.md)
- [BGE-M3 接入](docs/bge-m3-setup.md)、[历史真实模型记录](docs/real-results.md)
- [历史目标环境验收](docs/target-verification.md)

尚未接入学校统一认证、邮件、OCR、多部门流转、SLA 或自动处理工单。校园通知及 AI 学习结果应核对原文，练习评分仅作学习参考。
