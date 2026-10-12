# M6 真实模型效果

状态：当前已启用真实模式。DeepSeek + 本地 BGE-M3 接入探针通过，四份演示资料真实索引发布成功，五题端到端冒烟验证通过。下面的 deepseek-embedding 404 记录保留为历史；大规模效果评测尚未开展。

## 当前 BGE-M3 验证（2026-10-10）

- 聊天：`deepseek-flash`，`https://api.deepseek.com/v1`，非思考模式，max_tokens=4096。
- 嵌入：本地 Docker CPU TEI `cpu-1.9`，`BAAI/bge-m3`，revision=`5617a9f61b028005a4858fdac845db406aefb181`，CLS / float32 / 1024 维，无认证且不暴露宿主机端口。
- 配置调整：本机 Docker 可用内存约 8 GB，8192 token 预热反复重启；改为 max-batch-tokens=2048、分词线程=2 后服务健康。该资源配置使单条输入上限为 2048 token，超限默认截断，详见 BGE-M3 接入说明。
- 接入探针：2 条有效 1024 维向量与 1 条带正确引用的 JSON 回答通过，2 次服务请求，整次探针 1088 ms。汇总供应商用量 prompt_tokens=166、completion_tokens=27、total_tokens=193；不是单条聊天的独立计数。
- 实际部署已切换 `MODEL_MODE=real`，真实 index_key=`real:f667560db358954bf41e42d0:1024`。Docker Desktop 中途停止后已恢复，缓存无需重新下载。
- 为 accounts.md、admin-internal.md、campus-network.md、vpn-809.md 通过管理员版本上传接口创建真实版本，四项导入均 ready；保留旧版本与账号凭据。其他自行上传的资料需在管理页面重新上传版本。
- 五题记录见 `evaluations/20261010-bge-m3-smoke.json`：5/5 完成，无模型/协议失败，可回答预期匹配 5/5，预期文档匹配 3/3，引用授权与版本检查失败 0。未知问题和管理员专用问题均拒答。
- 成功案例端到端耗时中位数 7359 ms，p95 8125 ms，包括创建会话、问答与引用检查，不能视为纯模型延迟。
- 已人工阅读三条回答与对应来源片段，结论均受来源支持；两条拒答符合预期。这五题只代表演示冒烟检查，不外推为校园问答准确率；成本尚未测量。
- 后端 PostgreSQL/Redis 自动化测试 42 项通过（9.13 秒），Ruff 与格式检查通过。新增验证本地嵌入无需密钥、旧密钥不转发、权重版本影响索引标识。

## 在线探针结果（2026-10-10）

使用用户本地配置的密钥，在独立临时 API 容器设置 `MODEL_MODE=real` 执行；没有修改现有部署模式、文档或索引。

- 完整探针首先调用嵌入，被接口拒绝：`MODEL_CONFIGURATION`，调用 1 次，耗时 345 ms，供应商用量未知。聊天步骤未执行。
- 进一步检查 `GET https://api.deepseek.com/v1/models` 返回 HTTP 200，列出的模型为 `deepseek-flash`、`deepseek-v4-pro`。
- `POST https://api.deepseek.com/v1/embeddings` 使用 `deepseek-embedding`、`dimensions=1024`，返回 HTTP 404；未获得任何向量，因此无法验证 1024 维。
- 单独聊天探针通过：`deepseek-flash` 返回符合结构的 JSON、answerable=true、来源编号 [1]，回答包含测试资料里的 IT-1024。供应商报告 prompt_tokens=149、completion_tokens=26、total_tokens=175、prompt_cache_hit_tokens=0、prompt_cache_miss_tokens=149。

上述结果只证明一次聊天协议与引用探针通过，不代表检索准确率、校园问答效果或费用已经验收。下一步需要可用的 1024 维嵌入服务，再重建真实索引并运行固定问题集。没有记录密钥、认证请求头或供应商响应正文。

最新配置：用户指定聊天与嵌入 API Base 均为 `https://api.deepseek.com/v1`，已录入。聊天模型为 `deepseek-flash`（V4.1 Flash），嵌入为 `deepseek-embedding`。嵌入模型可用性及 1024 维支持尚未通过在线验证，不能将地址录入等同于服务验收通过。

2026-10-10：用户将选型改为 `deepseek-v4.1-flash` / `deepseek-embedding`。已补充 DeepSeek 参数兼容与配置模板，见 [DeepSeek 接入](deepseek-setup.md)。官方 V4.1 Flash API 名称为 `deepseek-flash`；用户指定名称对应的服务地址及嵌入模型 1024 维支持尚待确认。保持 Mock，未调用真实供应商，不能宣称已完成真实模型接入验收。

填写供应商 API 前缀（不填写密钥）、Chat/Embedding 模型、1024 维确认、文档版本与 index_key、运行日期。运行固定问题集后逐题记录答案是否被来源支持、拒答是否正确、调用失败、请求耗时、供应商提供的 Token 用量。准确率、平均延迟和成本当前均为未测量。
