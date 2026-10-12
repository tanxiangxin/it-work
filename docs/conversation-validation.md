# 普通对话与知识库问答

修复前所有问题都经过检索，且可回答结果必须有来源，导致“你好，你能做什么”被拒答。现在根据意图区分普通交流与校园知识库问答：普通回复不查询向量服务，不要求引用；校园专属问题保留检索、权限和引用校验。页面与历史记录都标记回答类型。

## 验证与复现

2026-10-10 已完成：PostgreSQL/pgvector 与 Redis 环境下 62 项后端测试通过；前端 TypeScript 与生产构建通过；真实 DeepSeek 六题全部完成，回答类型与可回答预期均为 6/6，VPN 引用来源检查 1/1，无不可访问引用；Chrome Playwright 普通对话与刷新历史测试 1/1 通过。未测量通用回答准确率或成本。

后端回归覆盖问候、通用概念、上下文、混合问题、校园追问、无公开资料、禁止普通回复携带引用、空输出、模型网络失败及历史类型持久化。Playwright `conversation.spec.ts` 检查问候正常回复、类型标识和页面刷新后的历史。

真实服务用例保存在 `samples/conversation-questions.json`，记录保存于 [真实六题记录](evaluations/20261010-conversation-smoke.json)。包含问候、感谢、VPN 概念、Python 概念、校园 VPN 故障及未知机房开放时间。前四题应为无引用普通回复；VPN 故障应引用 `vpn-809.md`；未知校园政策应拒答。用例需要演示资料已导入并发布真实索引。

```powershell
# 设置为现有学生账号的实际密码，不覆盖数据库账号
$env:EVAL_PASSWORD = '<学生实际密码>'
python scripts/evaluate_real.py --cases samples/conversation-questions.json --output work/evaluations/conversation-smoke.json
Remove-Item Env:EVAL_PASSWORD
docker compose --profile test run --build --rm tests
cd frontend
pnpm exec playwright test conversation.spec.ts
```

报告区分协议完成、回答类型、可回答预期和引用来源检查。这些是小样本功能检查，不能作为通用回答准确率。普通回复来自模型通用知识，不代表学校政策；意图分类也可能出错，应持续扩充多轮、混合意图与对抗用例。学校具体信息应通过知识库引用核对。

数据库迁移 `0003_message_answer_kind` 为旧回答默认设置 knowledge；更新容器时 Alembic 自动执行。旧的拒答历史保留原样，重新提问会使用新逻辑。
