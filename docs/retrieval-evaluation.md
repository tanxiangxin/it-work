# 检索质量对比

本阶段比较真实 BGE-M3 下的纯向量与 BM25 + RRF 混合检索。两种排序使用同一个查询向量和同一个权限范围，查询不会创建会话、调用聊天模型或修改线上 RETRIEVAL_MODE。

## 数据集和接口

`samples/retrieval-questions.json` 有 21 道自编问题：17 道标注相关文档的问题、2 道当前资料不支持的问题、2 道管理员文档权限检查。包括错误 809、SSID、同义表达、账号锁定和跨文档问题。相关性标注来自演示资料，按文档名识别；不要在测试知识库中创建同名的不同资料，以免标注歧义。

`POST /api/v1/retrieval/compare` 使用当前登录用户权限，输入 `{content, first_mode}`。每次只向量化一次，分别执行 vector 与 hybrid；候选上限 20、RRF 常数 60、结果最多 5 个分块，沿用当前问答的上下文长度限制。返回当前可见文档版本、索引标识、模型版本、两种排序和分阶段耗时。未登录返回 401；不可见、已删除、未发布或旧索引资料不参与检索。知识库在对比期间改变时返回 409，避免比较不同资料。

学生只获得公开资料，管理员获得其正常可见范围。实际学生评测脚本要求学生账号与真实模式；拒绝将 Mock 嵌入结果用作真实检索指标。

## 复现

先启动项目并保证演示资料的真实版本已 ready。设置 EVAL_PASSWORD 为实际学生密码，仅在本地输入，然后运行（Python 3.12；脚本和指标模块只需标准库）：

```powershell
$env:EVAL_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host '学生密码' -AsSecureString)).Password
python scripts/compare_retrieval.py --repetitions 3
Remove-Item Env:EVAL_PASSWORD
```

未安装 Python 命令时可用 `uv run --python 3.12 --no-project scripts/compare_retrieval.py --repetitions 3`，首次可能需 uv 下载 Python。`--cases` 指定其他问题集，`--output` 指定结果文件，`--base-url` 默认 `http://localhost:8080`。

默认报告写入 `work/evaluations/retrieval-<UTC时间>.json`；每题完成后原子更新，可检查中断前的结果。保存数据集 SHA-256、模型/权重版本、知识库 generation、文档版本、每次排序与耗时。若资料或模型改变，停止采样并标记 incomplete。缺少正例标注的文档时直接失败；每个结果都含采样次数。

先做一条预热请求并排除其耗时，每题默认重复三次，交替两种排序的执行顺序。保留全部重复结果，指标按第一次排序计算，同时检查排名是否稳定；各题耗时取三次中位数，再统计全题中位数/p95。失败不计入成功耗时和命中率，但必须报告失败数量与完成题数。脚本结束退出登录，遇到失败或权限泄露返回非零退出码。

## 指标边界

- Recall@1/3/5：前 k 个分块里出现的相关文档数除以该题全部相关文档数；重复分块不重复计数。只统计 17 道正例。
- MRR@5：第一个相关文档出现位置的倒数，前五未出现则为 0。按分块排序位置计算。
- 无答案问题只记录召回候选，不将“召回了无关资料”直接解释为模型回答错误或拒答失败。纯向量通常总能召回邻近资料，问答拒答应另用 `evaluate_real.py` 验证。
- 权限问题记录 forbidden_documents 命中次数，期望为 0；不进入正例 Recall/MRR 分母。
- embedding_ms 与 retrieval_ms 分开记录，排序耗时不包含模型嵌入和 HTTP 网络耗时；也不是完整问答延迟。

当前公开演示知识库很小，Recall@5 容易达到上限。应重点观察 Recall@1、MRR 和逐题排序，不据此宣称一般场景的准确率或混合检索必然优于向量检索。该报告不是答案准确率、成本评测或人工答案质量评分。后续扩充独立标注的资料及问题后再评估泛化。
