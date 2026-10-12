# DeepSeek + 本地 BGE-M3

2026-10-10 已完成本机接入：真实探针通过、四份演示资料重建索引成功、五题端到端冒烟通过，当前 `.env` 为 `MODEL_MODE=real`。详细证据见 [真实模型验证](real-results.md)。下面的步骤用于复现或新环境配置。

当前选型：聊天 `deepseek-flash` / `https://api.deepseek.com/v1`；嵌入 `BAAI/bge-m3`，运行于本地 Docker CPU 服务。BGE-M3 原生 dense 向量为 1024 维；首版只使用 dense 输出，继续与 BM25 做 RRF，不加入模型 sparse 或 ColBERT 分支。

本地服务使用官方 TEI `cpu-1.9` 镜像，模型 revision 固定为 `5617a9f61b028005a4858fdac845db406aefb181`，float32 与 CLS pooling。文件缓存持久化到 `embedding_cache` 卷，不向宿主机开放端口。首次下载与模型加载可能较慢；检查 `docker compose logs --tail 30 embedding`。CPU 的实际延迟以本机验收为准。

本机 Docker 可用内存约 8 GB，8192 token 预热配置反复重启；已将 max-batch-tokens 调至 2048，分词线程数调至 2，服务健康且实际 1024 维探针通过。该配置将 TEI 最大单条输入限制为 2048 token，超出时按服务默认策略截断；这是本地 CPU 资源配置的限制，不是 BGE-M3 模型本身的 8192 token 能力。当前分块上限 1000 字符，增大分块或导入长标题路径前需评估输入长度，或提升资源及 token 预算。

```env
COMPOSE_PROFILES=bge
EMBEDDING_API_BASE=http://embedding:80/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_REVISION=5617a9f61b028005a4858fdac845db406aefb181
EMBEDDING_DIMENSIONS=1024
EMBEDDING_SEND_DIMENSIONS=false
EMBEDDING_REQUIRES_API_KEY=false
```

不需要嵌入 API 密钥；即使本地 .env 保留旧供应商密钥，也不会发送到此服务。聊天密钥继续只保存在 .env。不要将本地无认证嵌入服务直接开放到公网。使用其他托管接口时恢复 `EMBEDDING_REQUIRES_API_KEY=true` 并配置供应商地址、密钥。

启动服务：`docker compose up -d embedding`。保持应用 Mock，通过临时容器验证真实模型：

CPU ONNX 权重文件约 2.27 GB（十进制），首次下载可能超过默认启动等待时间。Windows 一键脚本支持 `powershell -File .\scripts\start.ps1 -StartupTimeoutSeconds 3600`，缓存完成后恢复默认即可。默认只使用 Docker 分配的 CPU，无需 CUDA。

```powershell
docker compose run --rm --no-deps -e MODEL_MODE=real api python -m app.model_check --online
```

探针通过后设置 .env 的 `MODEL_MODE=real`，执行 `docker compose up -d --build --wait`。知识库管理中重新上传文档版本以重建真实索引，随后运行固定问题集和人工来源核对。原 Mock 索引不能复用；模型 revision 纳入真实 index_key，变更权重需重建索引。

依据：[BGE-M3 官方模型卡](https://huggingface.co/BAAI/bge-m3)、[TEI CPU 镜像](https://huggingface.co/docs/text-embeddings-inference/supported_models)、[TEI 部署与 OpenAI 接口](https://huggingface.co/docs/text-embeddings-inference/quick_tour)。
