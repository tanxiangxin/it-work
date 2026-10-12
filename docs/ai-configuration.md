# AI 配置

登录后点击主界面右上角「AI 配置」。每个账号独立保存配置，作用于知识问答的意图识别、普通聊天、知识库回答和工单摘要。学习资料助手继续使用服务器配置，知识库向量模型及索引配置保持独立。

配置窗口直接提供自定义模型表单，填写 API 基础地址、模型名称、接口类型和 API Key。

自定义云模型只允许访问公网 HTTP(S) 地址；本机、内网、链路本地地址及解析到这些地址的域名会被拒绝。请求固定连接校验后的 IP，并保留原域名的 Host 与 HTTPS 证书校验，避免 DNS 重绑定；不跟随重定向。服务器自身配置的模型和内部向量服务不受此限制。端口必须有效，地址不能包含空白、账号密码或查询参数。

接口类型只提供 OpenAI 和 Anthropic。OpenAI 基础地址通常以 `/v1` 结尾，系统自动调用 `/chat/completions`，服务需支持 JSON 格式回复。Anthropic 可填写 `https://api.anthropic.com` 或以 `/v1` 结尾的基础地址，系统自动调用 Messages API，并使用对应鉴权头和消息格式。

Anthropic 请求格式参考 [官方 Messages API 文档](https://platform.claude.com/docs/en/api/messages/create)。

「测试连接」使用当前表单进行一次聊天请求，不保存配置；「保存配置」用于后续请求，已开始的回答继续使用原配置。密钥只在后端数据库保存，不通过读取接口回显；接口地址不变时留空保留密钥，修改接口地址后需重新填写。

接口均需登录：`GET /api/v1/ai-config`、`PUT /api/v1/ai-config`、`POST /api/v1/ai-config/test`。新增数据库表由 `alembic upgrade head` 的 `0010_ai_configuration` 迁移创建。
