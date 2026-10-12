# OpenAI 接入与 M6 验收

当前项目选型已改为 DeepSeek，见 [当前接入说明](deepseek-setup.md)。本文保留 OpenAI 兼容配置；切换到本方案时须设置 `LLM_API_STYLE=openai`。

选定模型：回答 `gpt-6.1-sol`，嵌入 `text-embedding-3-small`。嵌入显式请求 1024 维，不改变现有 pgvector schema。当前保持 Mock，真实服务尚未验收。

已按 [OpenAI 官方 GPT-6 文档](https://developers.openai.com/api/docs/guides/latest-model) 修正参数：Sol 使用 reasoning_effort=low，不发送 temperature；结构化 JSON 仍通过 Chat Completions 返回。当前不用模型工具调用。嵌入 dimensions 的支持见 [官方 Embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)。

## 配置与离线检查

`.env.openai.example` 只提供模型配置片段，不要用它覆盖完整 .env。实际 .env 中已填写非敏感模型设置，数据库与账号配置保留。仅补齐 LLM_API_KEY 和 EMBEDDING_API_KEY；可使用同一把有对应权限的 OpenAI API 密钥。不要将密钥发送到聊天、前端或 Git。

```dotenv
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-6.1-sol
LLM_REASONING_EFFORT=low
LLM_MAX_COMPLETION_TOKENS=4096
EMBEDDING_API_BASE=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1024
EMBEDDING_SEND_DIMENSIONS=true
PROVIDER_TIMEOUT=60
```

检查将来要使用的模型配置，无网络调用、无自动模式切换：

```powershell
docker --context desktop-linux compose run --rm --no-deps api python -m app.model_check
```

退出码 0 表示配置完整，2 表示配置缺失或无效。输出只包含模式、模型标识、索引标识和缺失字段名，不输出密钥、地址或账号密码。配置完整不证明模型账号权限、网络或真实回答效果。

## 在线探针与真实索引

填写密钥后将 MODEL_MODE 改为 real。先构建最新镜像，再运行探针；使用一次性容器时不会切换仍运行的 Mock 服务：

```powershell
docker --context desktop-linux compose build api
docker --context desktop-linux compose run --rm --no-deps api python -m app.model_check --online
```

探针会产生两条短文本的 Embedding 和一次 Chat Completions 请求，可能产生费用。检查 1024 维、结构化回答及固定证据引用，并输出实际调用次数、耗时和供应商提供的用量。429/5xx/网络错误仍遵循有限重试；失败不自动改用 Mock，也不写入知识库。

探针通过后：

```powershell
docker --context desktop-linux compose up -d --build api worker scheduler
```

通过管理页面为每份公开演示资料重新上传版本，在任务变为 ready 后确认发布。管理员专用资料保持管理员可见。真实版本发布前旧 Mock 版本仍保存，但不进入真实检索。不要删除旧资料或数据库卷。相同原始文件在不同 index_key 下能够产生新版本。

## 固定问题集与人工评审

使用学生账号运行脚本。EVAL_PASSWORD 是该账号当前实际密码，初始 .env 值未必等于已存在数据库密码。

```powershell
$env:EVAL_PASSWORD='当前学生账号密码'
python scripts/evaluate_real.py
# 可指定 --base-url、--email、--cases、--output。
```

脚本在 Mock 模式下于登录前拒绝执行；在线评测会创建五个学生会话并调用真实模型。每题结束即原子保存结果，默认输出 work/evaluations/real-UTC时间.json，不覆盖历史记录。模型失败与证据不足拒答分开记录；检查 SSE 完成事件、真实模式、回答编号、来源访问权限与版本一致性。

自动汇总仅报告回答/拒答预期匹配、期望文档是否被引用、调用失败、引用打开失败，以及成功案例耗时的中位数与 p95。耗时包括创建会话、问答和引用检查，不是模型单次生成延迟。失败不会被当成正确拒答，失败耗时不进入成功案例分布。

**这些指标不是答案准确率。** 人工逐题打开 source，判断结论是否被资料支持，在结果里的 human_supported_answer 填写判断；人工评审前 human_answer_accuracy 与 measured_accuracy 均为 null。费用未结合实际账单测量时保持 null。供应商实际用量仍保存在后台 request_traces。

五题仅用于首次冒烟验收，不代表校园真实流量或检索准确率；记录真实索引版本后再扩充问题集。模型访问、网络或重建索引未完成时，M6 继续标记待验收。
