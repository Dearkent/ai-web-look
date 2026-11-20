"""模型服务商预设。只放“怎么连”（协议、地址、密钥去哪申请），不写死模型名清单——模型更新很快，
界面里可以点“获取模型列表”向服务商实时查询，或者直接填写。示例模型名仅作提示，可能已经过时。

协议只有两种：
  anthropic       Anthropic Messages API（POST {base}/v1/messages，头 x-api-key）
  openai          OpenAI 兼容的 Chat Completions（POST {base}/chat/completions，头 Authorization: Bearer）
国内主流服务商都提供 OpenAI 兼容接口，所以用同一套代码。地址核对于 2026-11（各家官方文档）。
"""
from __future__ import annotations

PRESETS = [
    {"id": "anthropic", "name": "Anthropic（Claude）", "protocol": "anthropic", "base_url": "https://api.anthropic.com",
     "key_url": "https://console.anthropic.com/", "example_model": "claude-sonnet-5-5", "needs_key": True},
    {"id": "openai", "name": "OpenAI", "protocol": "openai", "base_url": "https://api.openai.com/v1",
     "key_url": "https://platform.openai.com/api-keys", "example_model": "", "needs_key": True},
    {"id": "gemini", "name": "Google Gemini", "protocol": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "key_url": "https://aistudio.google.com/apikey", "example_model": "", "needs_key": True,
     "note": "用的是 Gemini 官方的 OpenAI 兼容接口"},
    {"id": "deepseek", "name": "DeepSeek（深度求索）", "protocol": "openai", "base_url": "https://api.deepseek.com/v1",
     "key_url": "https://platform.deepseek.com/api_keys", "example_model": "deepseek-chat", "needs_key": True},
    {"id": "qwen", "name": "通义千问（阿里云百炼·北京）", "protocol": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "key_url": "https://bailian.console.aliyun.com/", "example_model": "qwen-plus", "needs_key": True},
    {"id": "moonshot", "name": "Kimi（月之暗面）", "protocol": "openai", "base_url": "https://api.moonshot.cn/v1",
     "key_url": "https://platform.moonshot.cn/console/api-keys", "example_model": "", "needs_key": True},
    {"id": "zhipu", "name": "智谱 GLM", "protocol": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "key_url": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys", "example_model": "", "needs_key": True},
    {"id": "doubao", "name": "豆包（火山方舟）", "protocol": "openai", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
     "key_url": "https://console.volcengine.com/ark", "example_model": "", "needs_key": True,
     "note": "模型名可能要填控制台里的“接入点 ID”"},
    {"id": "openrouter", "name": "OpenRouter（多家模型聚合）", "protocol": "openai", "base_url": "https://openrouter.ai/api/v1",
     "key_url": "https://openrouter.ai/keys", "example_model": "", "needs_key": True},
    {"id": "ollama", "name": "本机 Ollama（不联网、免费）", "protocol": "openai", "base_url": "http://127.0.0.1:11434/v1",
     "key_url": "https://ollama.com/", "example_model": "", "needs_key": False},
    {"id": "custom", "name": "自定义（任何 OpenAI 兼容接口）", "protocol": "openai", "base_url": "",
     "key_url": "", "example_model": "", "needs_key": True},
]
BY_ID = {p["id"]: p for p in PRESETS}

# 用途：每个用途可以选不同的服务商和模型（例如理解用便宜快的，文案用写得好的）。
ROLES = {
    "understand": "理解需求（把一句话变成结构化需求）",
    "copy": "写文案（网站上的标题、介绍、卖点）",
    "fix": "修复（实验功能：按报错改图纸）",
}
