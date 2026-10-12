# DeepSeek 接入（当前选型）

当前嵌入已改为本地 Docker CPU `BAAI/bge-m3`，请按 [BGE-M3 接入步骤](bge-m3-setup.md) 操作。以下 deepseek-embedding 内容保留为失败选型的历史记录。

在线验证结果：聊天 `deepseek-flash` 探针通过；用户提供的 `/v1/embeddings` 返回 HTTP 404，未获得向量。当前保留 Mock，需要更换或修正嵌入服务，再进行完整验收。详细结果见 [在线验证记录](real-results.md)。

用户指定聊天与嵌入 API Base 均为 `https://api.deepseek.com/v1`，已写入配置。V4.1 Flash 按官方 API ID 配置为 `deepseek-flash`，嵌入保留用户指定的 `deepseek-embedding`。嵌入模型可用性及 1024 维支持尚未通过在线请求验证。配置模板为 `.env.deepseek.example`，将其中模型配置合并到已有 `.env`，保留数据库、账号密码等配置。

## 先确认服务

DeepSeek 官方 V4.1 Flash 的 API ID 是 `deepseek-flash`，官方聊天 API Base 为 `https://api.deepseek.com`。用户指定的 `deepseek-v4.1-flash` 可能是兼容网关别名，不能保证官方接口接受它。使用官方直连时应明确将 `LLM_MODEL` 改为 `deepseek-flash`；使用网关时保留网关提供的准确 ID 和地址。

目前未核实 `deepseek-embedding` 的官方可用接口、原生维度或降维参数支持。用户提供的嵌入地址已录入，但不代表 `POST /embeddings` 或该模型已验证可用。密钥分别填写到本地 `.env`。原 OpenAI 密钥不能当作 DeepSeek 密钥使用。

## 参数与检查

- `LLM_API_STYLE=deepseek` 使用 DeepSeek Chat Completions 参数：`max_tokens`、`thinking` 和 JSON 输出。`LLM_MAX_COMPLETION_TOKENS=4096` 在这个模式下映射为 `max_tokens=4096`。
- 默认 `LLM_THINKING_ENABLED=false`，发送 `thinking.type=disabled` 和 `temperature=0`，不发送 reasoning_effort。开启思考时可配置推理强度，不能同时设置 `none`。
- `EMBEDDING_SEND_DIMENSIONS=true` 发送 `dimensions=1024`。仅当供应商原生返回 1024 维且不接受该参数时改为 false。返回其他维度会明确报错，不截断或补零。
- `LLM_API_STYLE=openai` 保留原有 OpenAI 参数兼容。更换网关时应确认它接受 DeepSeek 扩展参数。

当前保留 `MODEL_MODE=mock`，两个地址已填写。补齐本地密钥后，运行离线检查；嵌入服务和 1024 维支持由后续在线探针验证：

```powershell
docker compose up -d --build --wait
docker compose exec -T api python -m app.model_check
```

离线检查只验证配置，不确认模型可用。准备好实际服务后设置 `MODEL_MODE=real`，重新创建 API、Worker、Scheduler，再执行在线探针（会产生少量模型费用）：

```powershell
docker compose up -d --build --wait
docker compose exec -T api python -m app.model_check --online
```

探针验证两条嵌入、1024 维和一条带引用 JSON 回答。通过后在知识库管理为文档上传新版本，重建真实索引；Mock 索引不能复用。再运行 `scripts/evaluate_real.py` 的固定问题集并人工核对来源，结果记录在 `docs/real-results.md`。探针成功不能代替问答效果验收。

依据：[官方模型名称](https://api-docs.deepseek.com/updates/)、[Chat Completions 参数](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)。
