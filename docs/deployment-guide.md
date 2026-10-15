# 三条部署路径

## 首次启动：Mock

Windows 安装并启动 Docker Desktop 的 Linux 引擎，在项目根目录运行：

```powershell
powershell -File scripts/init-env.ps1
powershell -File scripts/start.ps1 -Test
```

初始化保留已有 `.env`、数据库和账号密码。访问 http://localhost:8080。学生 `student@example.test`、管理员 `admin@example.test`，初始密码在 `.env` 的 `DEMO_*_PASSWORD`。重启后的已有账号密码不会被 seed 覆盖。

Mock 不需要密钥、不启动 BGE-M3；界面明确标注模拟结果。Python 可用时也能使用 `python scripts/init_env.py`。前端统一使用 `pnpm install --frozen-lockfile`，以 `pnpm-lock.yaml` 为准，不使用历史 `package-lock.json` 安装。

## 真实模型：DeepSeek + 本地 BGE-M3

1. 保留数据库和演示账号配置，将 `.env.deepseek.example` 中的模型字段填入已有 `.env`，填写有效 `LLM_API_KEY`。保持 `MODEL_MODE=mock`，等待探针验证。
2. 运行 `powershell -File scripts/enable-real.ps1`。脚本下载固定 revision 的 BGE-M3（首次数 GB）、等待嵌入服务健康，以独立容器探测真实聊天回答与 1024 维向量，然后切换服务并重建索引。原文件和历史版本保留；发生切换/索引失败时恢复原配置并尝试重新发布原索引。
3. 在 AI 配置中查看各功能模型来源。个人自定义聊天只用于知识问答和工单摘要，学习、通知和联网搜索使用服务器聊天服务，资料索引与检索使用服务器嵌入服务；个人聊天配置不会替换资料向量。
4. 管理员可分别检测服务器聊天/嵌入服务；个人模型使用表单的“测试连接”。“已配置”只说明字段齐全，连接检测和实际业务验证仍需通过。

评测采用 `samples/evaluation-50.json` 的 50 道题、参考要点、引用预期和拒答预期。该集合基于自编模拟资料，有相似问法，不是独立真实校园样本；正式效果评估应补充经授权的真实资料与独立标注问题。评测前保持知识库版本固定，并排除 E2E 上传的替代说明（例如 e2e-vpn.md），避免同主题冲突。

Windows 可直接使用容器内 Python 和已有演示账号配置，无需在主机安装 Python：

```powershell
powershell -File scripts/evaluate-real.ps1
```

已有账号密码若与 `.env` 不同，先更新本地对应演示密码配置并重建 API 的环境变量；脚本不会重置数据库账号。有 Python 的终端也可设置 `EVAL_PASSWORD` 为学生实际密码后运行：

```powershell
python scripts/evaluate_real.py --cases samples/evaluation-50.json --output work/evaluations/baseline-50.json
```

报告保存回答、可访问的引用和延迟，Token 用量见账号 AI 配置中的今日用量。协议失败、引用不可访问或预期不匹配会返回非零退出状态并保留报告。逐题人工核对 reference、来源与答案后记录准确率；协议/引用检查通过不代表答案正确。未提供密钥时，真实聊天和准确率验收保持待完成，不能用 Mock 数据替代。

## 长期部署

- 网关保持本机 `127.0.0.1:8080`；对外服务使用 HTTPS 代理，设置实际 `PUBLIC_ORIGIN` 和 `COOKIE_SECURE=true`。不公开 PostgreSQL、Redis 和 embedding 端口。
- 长期服务采用 `restart: unless-stopped`；迁移和测试为一次性任务。日志按每容器 10 MB × 3 轮转。Windows 自动恢复仍取决于 Docker Desktop/WSL 已启动；主动停止的容器需要再次启动。
- API 健康地址 `/api/v1/health/ready` 检查数据库/Redis，不代表聊天供应商或 Worker 一定健康。结合 Worker/Scheduler 日志和实际任务处理验证服务。
- 默认登录每个连接来源每分钟 60 次、每账号每分钟 10 次；当前网关下连接来源为代理地址，因此来源限制由整个入口共享。正式多人部署可在可信反向代理处补充真实客户端 IP 限流，不信任用户自报的转发头。
- 用户 AI 每分钟 20 次、每天 200 次；上传每分钟 10 次、每天 600 次；同时处理请求上限 2，进行中的学习/搜索/个人资料导入合计上限 3。管理员共享知识库导入也计入管理员任务保护。均可通过 `.env` 调整。每日北京时间零点重置，失败/无效的已接纳请求仍消耗额度，限流拒绝不计入。
- 额度由持久化 Redis 保存，请勿清空业务 Redis。Redis 不可用时，受保护的写入和登录返回 503；读取仍按原权限处理。前台流式请求在结束或断开后释放并发名额，进程异常退出的名额最多一小时回收。
- AI 配置中的“我的今日用量”只显示当前账号，汇总已完成的请求追踪，包括供应商报告的 Token。`MODEL_PRICES` 可填写模型名映射及 `input`、`output` 每百万 Token 人民币单价；缺少价格或用量不计算费用，不自动抓取价格。费用是估算，独立搜索费用和供应商优惠以账单为准。此设置控制请求额度，不是人民币金额硬限额。

### 备份和隔离恢复演练

```powershell
powershell -File scripts/backup.ps1
# 使用上一条输出的备份目录
powershell -File scripts/verify-restore.ps1 -BackupDirectory work/backups/你的备份目录
```

备份会短暂停止原本运行的 API、Worker、Scheduler，导出 PostgreSQL、自定义文件卷、表记录数/文件摘要及 SHA-256 校验；finally 恢复原运行服务。备份位于忽略的 `work/backups/`，包含个人资料，应另存到受控独立存储。

恢复演练先校验备份，创建随机唯一的 Compose 项目，不启动公网网关、Worker 或 Scheduler；核对全部业务表记录数与文件摘要并检查恢复 API，最后只删除该次演练的容器和卷。不会恢复覆盖原项目。正式数据回滚应另行选择明确目标，不能在原项目直接执行演练脚本中的恢复命令。

GitHub Actions 保持 Mock 且关闭业务额度限制，限流测试单独验证原子并发、每日额度、异常释放与用户隔离。当前机器验证记录见 [2026-10-15 验收](verification-2026-10-15.md)；早期文档中的路径、账号状态和真实模型结果均是历史记录。
