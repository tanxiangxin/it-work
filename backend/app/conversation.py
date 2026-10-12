"""Conservative routing overrides; ambiguous intents are classified by the chat provider."""

import re


def forced_route(question, history):
    text = re.sub(r"[\s，。！？,.!?、]", "", question.lower())
    social = (
        r"(你好|您好|嗨|hello|hi|早上好|晚上好|谢谢|谢谢你|好的|明白了|再见)+",
        r"(你好|您好|嗨)?(请问)?(你是谁|你能做什么|你可以做什么|你能帮我什么|介绍一下自己)",
    )
    if any(re.fullmatch(pattern, text) for pattern in social):
        return "general"
    if re.search(r"校园|学校|校内|校外|宿舍|寝室|统一认证|管理员|工单|admin-only|809", text):
        return "knowledge"
    # Short follow-ups to a school-specific request keep that scope, except social replies above.
    if len(text) <= 60 and re.search(r"它|这个|那个|怎么操作|在哪里|然后呢|还是不行|怎么办", text):
        prior = " ".join(item["content"] for item in history if item["role"] == "user")
        if re.search(r"校园|学校|宿舍|统一认证|VPN|809|管理员", prior, re.I):
            return "knowledge"
    return None
