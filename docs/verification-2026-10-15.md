# 当前机器验收与改进记录（2026-10-15）

**最新状态：本机网站已切换为真实模型，知识库问答、个人资料问答及后台复习提纲生成通过。** 下文保留此前缺少密钥、认证失败和供应商超时的排查过程；这些是历史阶段，最新结果见本文末尾“真实模式切换与演示截图”。固定 50 题评测及人工质量核对仍待完成。

环境：Windows 11、WSL 3.0.1、Docker Desktop 当前用户安装、Docker CLI 29.8.2、Compose 5.6.0；项目 `C:\ai\it-work`，基线提交 `fd7712d`。

## 1. 业务验收

- 正式 Compose 构建、迁移、初始化及首页、健康接口、管理员/学生登录通过。
- `docker compose --profile test run --build --rm tests`：169 passed，37.44 秒，无跳过。测试使用独立随机 PostgreSQL schema。
- 本机 Chrome / Playwright：4 passed，49.8 秒。
  - 管理员上传 → 学生带来源问答 → 确认工单 → 管理员处理回复 → 学生关闭。
  - 校园通知草稿、审核发布、订阅消息、个人待办与提醒。
  - 个人课程上传、资料问答、来源、复习提纲、练习和刷新恢复。
  - 练习提交、逐题评分、答案开关和刷新后恢复。
- 截图保存在本地忽略目录 `work/verification-20261015/`。工单流程保留带 E2E 标识的演示数据，个人课程测试自行清理。
- 上述模型为 Mock；浏览器用例中的“真实资料问答”指实际上传/索引/Worker 链路，不代表调用真实聊天模型。

## 2. 真实模型

用户选择 DeepSeek 聊天 + 本地 BGE-M3。当前缺少 `LLM_API_KEY`，保持 Mock，不能报告真实模型准确率、延迟或费用。后续项目进度见本文新增记录。

- BGE-M3 固定 revision `5617a9f61b028005a4858fdac845db406aefb181` 已下载并启动，容器 healthy。权重 SHA-256 `1eebfb28493f67bba03ce0ef64bfdc7fc5a3bd9d7493f818bb1d78cd798416b4` 已与官方固定版本元数据核对。
- API 容器直接调用实际嵌入服务：2 个输入均返回有效 1024 维向量。此验证没有切换聊天模式，没有调用付费聊天服务。
- 新增 `samples/evaluation-50.json`：39 道基于模拟资料的正例、9 道资料不足题、2 道权限拒答题，包含人工核对参考要点。它有重复主题，不是独立真实校园样本。
- `scripts/enable-real.ps1` 提供独立探针、切换、索引版本保留和失败恢复；重建索引及恢复已有 ready 版本经过测试。完整真实切换仍待密钥。
- `scripts/evaluate-real.ps1` 可直接调用容器内 Python，报告保存到忽略的 `work/evaluations/`。协议失败、预期不匹配或引用验证失败均返回非零；人工答案准确率保持独立核对。

## 3. 自动恢复、日志与备份

- API、Worker、Scheduler、PostgreSQL、Redis、Web、Gateway、Embedding 配置 `unless-stopped`，迁移/测试不自动重启。长期服务日志按 `json-file`、10 MB × 3 轮转。
- `scripts/backup.ps1` 实际生成备份：`work/backups/20261015-before-improvements/`。备份前暂停写入，完成后恢复原服务；SHA-256 清单保存于同目录。
- `scripts/verify-restore.ps1` 在随机独立项目 `campus-restore-04a2a4a9ec52` 恢复：25 张表记录数和全部 5 个上传文件的 SHA-256 与备份一致，恢复 API readiness=200。演练项目及其卷已清理，原项目保留。
- 重启 API、Worker、Scheduler、PostgreSQL、Redis 后，持久化脚本验证账号、文档原文件、会话、已关闭工单和人工回复均可访问。

## 4. 模型配置体验

- AI 配置展示知识问答/工单、学习、通知、搜索、索引的实际配置来源与模拟/真实状态。连接状态不把字段齐全当成网络可用。
- 管理员可检测服务器聊天/嵌入，个人模型沿用表单检测；学生不能调用管理员服务器检测接口。
- 桌面及 390 px 手机宽度验证通过，弹窗正文滚动，保存按钮可访问。截图：`work/verification-20261015/model-status.png`、`model-status-mobile.png`。

## 5. 额度、并发与用量

- 登录按连接来源及账号限制；AI/上传按登录用户限制频率和每日额度，请求并发使用 Redis 原子租约，队列任务按账号限制。
- 并发测试验证 30 次竞争只接纳 2 个名额；覆盖每日额度、租约过期、流式断开释放、Redis 不可用、跨账号用量隔离及真实登录后的 429 行为。
- 提交串行化使用 PostgreSQL 事务咨询锁，避免账号行锁阻塞独立模型追踪事务；通知摘要的该场景已有防回归测试。
- AI 配置可查看本人的 Token 和管理员配置单价对应的人民币估算。无价格/无 Token 时不估算；非有限数、负价格或不完整价格拒绝启动。真实连接检测也记录用量。

## 6. 配置与文档

- README 和 `docs/deployment-guide.md` 明确首次 Mock、真实模型、长期部署三条路径，旧环境文档已标为历史记录。
- `.env.example` 删除重复分块参数、关闭默认 BGE profile，并提供额度和可选价格配置。Windows 新增不依赖主机 Python 的随机配置初始化脚本。
- CI 保持 Mock、业务额度关闭；限流用例单独启用真实 Redis 原子验证。未触发远程 GitHub Actions。

## 最终检查

- 最终完整后端回归：**190 passed，无跳过，42.03 秒**，使用源码挂载、独立随机 PostgreSQL schema 和测试 Redis 库。
- Ruff 检查通过，56 个 Python 文件格式检查通过。
- 正式前端 Docker TypeScript/Vite 生产构建通过。本机常规执行环境的前端构建也通过；受限终端对 pnpm 依赖链接的解析报错，不作为应用代码类型错误处理。
- 浏览器：知识库/工单、通知/待办、课程学习、练习评分、个人 AI 配置五项通过；新增服务器模型/用量页修正按钮定位后单独通过，包含手机视口操作验证。
- 全部 PowerShell 运维脚本语法检查通过；Git diff 空白检查通过。
- 尚未完成：DeepSeek 实际密钥探针、真实模式切换与 50 题调用/人工质量评测。没有用历史结果或 Mock 结果替代本机真实验收。

## 第二项继续执行：密钥接入尝试

- 已确认本地 `.env` 存在一条 `LLM_API_KEY`，不是已知占位文本；配置接口主机为 `api.deepseek.com`。未记录或输出密钥。
- 切换前备份已完成：`work/backups/20261015-before-real-model/`，包含 25 张业务表、6 个文件及校验清单。
- 首次探针：BGE-M3 返回正常，DeepSeek HTTPS 连接失败。Clash 日志确认 `api.deepseek.com` 命中 `GeoIP/cn` 直连，多个目标地址连接超时。
- 通过现有本地控制管道对两个已有节点分别探测 DeepSeek；均可达。仅为 `api.deepseek.com` 增加已验证节点的前置路由，同时保存在当前订阅的 rules 扩展文件和运行配置；保留其余代理组选择与 TLS 证书验证。控制接口参考 [Mihomo API](https://wiki.metacubex.one/api/)。
- 代理原配置备份保存在忽略目录 `.cache/model-network/route-backup-1792036049114/`，包含私有代理配置，不应提交或分享。
- 网络修复后再次探针：DeepSeek 返回认证错误；独立 `/models` 检查同样返回 **HTTP 401**，错误分类 `authentication_error`。这不是模型输出质量问题，需提供有效的对应服务商密钥。
- 探针在切换前退出，当前 `/api/v1/health/ready` 返回 `{"status":"ok","model_mode":"mock"}`。未切换真实模式，未重建业务索引，未运行 50 题评测；等待本地密钥更新。

### 新密钥更新后的复验（北京时间 2026-10-15 中午）

- 新密钥认证已通过：DeepSeek `/models` 返回 HTTP 200，可用模型包含 `deepseek-flash` 和 `deepseek-v4-pro`。未输出密钥或账户余额。
- 原专用路由节点出现连接波动，已通过现有控制接口探测并将 DeepSeek 单域名路由切换到另一已验证节点；其余代理组选择不变。该次代理配置备份位于忽略目录 `.cache/model-network/route-backup-1792036560487/`。
- 实际 JSON 回答探针未能完成，约 96 秒后返回 `MODEL_TIMEOUT`；64 Token 的最小非思考流式探针建立 HTTP 200 连接，但 45 秒内未收到回复。随后使用官方根路径复验，仍在 150 秒的总时限内未收到生成内容，返回 `TimeoutError`，诊断容器已结束。
- 本地配置增加 `LLM_MAX_COMPLETION_TOKENS=4096` 和 `PROVIDER_TIMEOUT=90`，限制常规生成输出并给予合理响应时间；显式业务生成预算仍由对应代码控制。
- [DeepSeek 官方事故记录](https://status.deepseek.com/incidents/7116348214287)确认 2026-10-15 北京时间 08:11 起网页/API 部分中断，涉及 Flash 和 Pro API；检查时仍为“已定位原因，正在实施修复”。这与认证通过但生成无内容/超时的实测现象一致，不能将本次阻塞归因于新密钥无效。
- 在真实回答与引用探针成功之前继续保持 Mock，不发布新索引，不以 50 次失败调用冒充效果评测。待供应商恢复后继续真实切换与固定 50 题评测。

## 真实模式切换与演示截图（北京时间 2026-10-15）

- 用户授权切换后执行 `scripts/enable-real.ps1`。独立探针实际调用 DeepSeek `deepseek-flash` 和本地 `BAAI/bge-m3`：2 个嵌入输入返回 1024 维向量，聊天回答包含 `IT-1024` 且引用正确；本次探针耗时 6005 ms、聊天共 193 Token。
- 本地 `.env` 已设为 `MODEL_MODE=real`、`COMPOSE_PROFILES=bge`，API、Worker、Scheduler 已重新加载配置，6 份原有资料的新索引发布成功。旧文件及版本保留，密钥和本地环境文件不上传仓库。
- API readiness 返回 `{"status":"ok","model_mode":"real"}`；Worker 独立读取配置同样为 `real` 和 `deepseek-flash`，BGE-M3 容器健康。
- 在独立演示账号中，通过实际网页提交 VPN 问题、上传自编数据库笔记并进行 ACID 问答、提交后台复习提纲。三项结果均记录 `model_mode=real`，分别带 2、1、1 条引用；逐条读取来源接口均返回 HTTP 200。
- 页面中的服务器聊天、嵌入连接检测均通过。该演示账号持久化用量为 DeepSeek 输入 3786、输出 800 Token；这是本账号此次演示的统计，不包含其他探针及账号。未设置模型价格，费用保持“未估算”；嵌入服务未报告 Token 用量。
- README 演示图已更新为实际真实调用的知识问答、资料问答、复习提纲与模型/用量页面。截图仅包含自编资料和演示账号；已检查不含密钥。原始响应与运行报告保存在忽略的 `work/real-demo-20261015/`。
- 本次验证覆盖上述真实调用与引用访问，不等同于固定 50 题评测，也不代表已验证联网搜索、所有业务或全面回答准确率。仓库的新环境默认配置仍为 Mock，其他部署需使用自己的密钥执行启用脚本。
