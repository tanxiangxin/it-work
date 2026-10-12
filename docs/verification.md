# 早期本地验证记录

**以下为 Docker 可用前的历史记录。当前已补齐原生 Compose、26 项 PostgreSQL/Redis 测试、pnpm frozen 安装、浏览器完整流程和重启持久化验收，参见 [目标环境验收](target-verification.md)。演示密码恢复的待授权事项也记录于该文档。**

日期：2026-10-09。源码位置：`D:\vibe coding\ai-01`。默认 Mock 模式，没有调用真实供应商。

## 已运行

| 检查 | 结果 | 环境与边界 |
|---|---|---|
| 后端单元及数据库集成 | **24 passed，2 skipped** | Python 3.12.14；PGlite 0.5.8 的 PostgreSQL 18.3 WASM + pgvector；不是目标 PostgreSQL 16 容器 |
| 浏览器完整流程 | **1 passed** | 本机 Chrome / Playwright、构建后的 React、实际 FastAPI、上述数据库；同一 Worker 业务函数由测试线程派发，替代 Redis/Celery broker |
| TypeScript 类型检查 | 通过 | `tsc --noEmit` |
| Vite 生产构建 | 通过 | 工作区验证副本；Windows realpath 限制下，验证配置启用 Vite preserveSymlinks，使用正式源码 |
| Ruff | 通过 | app、迁移和测试静态检查、格式检查 |
| uv 锁文件 | 通过 | `uv lock --check`，65 个锁定包 |
| pnpm 锁文件结构 | 通过 | 从已安装 npm 图转换，199 个 registry 包，核对引用与完整性哈希；pnpm 原生 reader/writer 接受并序列化为 v9 YAML |

覆盖四种文档格式、中文标题和步骤、PDF 页码与扫描件拒绝、空/坏文件、上传限制、确定性模拟向量；角色与跨用户权限、管理员资料过滤、来源绕过、撤回后隐藏旧回答且清理模型历史；版本去重、失败重试、旧版本保留、部分分块清理、超时 lease 回收、模型索引隔离；供应商超时、限流、输出格式和维度错误；工单幂等、不同内容冲突、状态越权、回复、重新打开和关闭后禁止回复。

浏览器实际执行：管理员登录 → 上传 MD → 发布 → 学生登录 → 问答 → 打开来源 → 生成并编辑草稿 → 明确提交 → 管理员处理、回复、解决 → 学生确认关闭。

修复了表格类型推断、按钮可访问名称、撤回资料进入历史上下文、旧任务被另一模型写入、SSE 数据库访问阻塞事件循环和来源抽屉的错误缓存展示。相关权限、索引与业务流程已回归。问答、草稿和后台向量化均记录模式、调用次数、耗时和供应商可用用量。

## 尚未完成的目标环境验收

1. **Docker Compose**：本机没有可用 Docker Engine，未构建目标镜像、启动目标 PostgreSQL 16 或验证实际 Redis/Celery/Beat 和网关容器。已经提供固定镜像、健康检查、持久化卷、test profile 和 GitHub Actions。
2. **pnpm frozen 安装**：当前 Windows 环境中 realpath 返回 EPERM。本地前端使用 npm 图验证，锁文件经过 pnpm 原生读写；`pnpm install --frozen-lockfile` 仍须在常规环境或 CI 执行。
3. **并发与 broker**：跳过的是并发提交和真实 Redis 派发。PGlite 的连接和事务行为不同，不用它证明 PostgreSQL 并发。Compose test profile 会启用这两项测试。
4. **持久化与恢复**：提供重启检查脚本和备份恢复命令，目标容器环境未执行。内存测试数据库的成功不代表持久化验收。
5. **M6**：真实接口、配置校验和固定问题集工具已实现；尚缺供应商配置，没有真实准确率、延迟或成本结果。

M1—M4 的业务代码已完成本地 Mock 流程验证；M0 的目标容器环境和 M5 的完整部署验收仍有以上待执行项。**整个 M0—M5 尚未完全验收通过。**

## 复现

标准环境按 README 启动和初始化，在根目录执行：

```powershell
docker compose --profile test run --build --rm tests
Set-Location frontend
pnpm install --frozen-lockfile
pnpm build
pnpm exec playwright install chromium
# 设置 DEMO_ADMIN_PASSWORD / DEMO_STUDENT_PASSWORD 为 .env 中的两个值
pnpm test:e2e
Set-Location ..
docker compose restart api worker scheduler postgres redis
python scripts/check_persistence.py
```

GitHub Actions 已配置同样流程，尚未推送或触发。所有产品源码和测试在项目目录中；临时验证服务、日志与截图留在原工作区 work，没有改变正式 PostgreSQL/Redis 选型。

实际构建有 Vite 的 bundle 提示：初始 JS 约 1.24 MB、gzip 392 KB，构建成功。后续可拆分管理员页面。FastAPI TestClient 有 httpx 依赖弃用提示，当前组合测试通过。jieba 0.42.1 的静态无依赖元数据依据其 setup.py 提供，避免锁定时执行旧源码包。
