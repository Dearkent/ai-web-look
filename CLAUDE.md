# 接手须知（给下一次对话里的 Claude）

这是“AI 自动建站工作台”和它的学习大脑。用户用简体中文交流，每次汇报进度和完成度。

## 先做这几步
1. `python3 brain.py progress` 看完成度；读 `tasks.json` 最后几条和 `journal/` 最新一篇，知道上次停在哪。
2. `python3 -I brain.py verify` 跑一遍验证门，全过再动手（要装 Chrome 和 Playwright 才能跑浏览器检查）。
3. 改完东西：再跑验证门 → `brain.py log` 记一笔 → `brain.py export` → 提交并推到本仓库（`main`）。

## 用户定下的规矩（不要违反）
- 两个核心：能“喂东西”持续学习；能自我纠错。防止报错/修复死循环。
- 学习第三方代码只做笔记、不直接拿来用、不运行。
- 模型密钥只从环境变量或本机 `~/.aisite/models.json`（权限 600）读，由用户自己填；模板是 `product/models/models.example.json`。不要用对话环境自带的接口通道当密钥。
- **这个仓库是公开的**：任何密钥、令牌、个人资料都不能提交（`.gitignore` 已排除 models.json、.env、压缩包）。
- 不编造评价、数据或用户没说过的话。安全检查拦下的事不要绕。

## 用户的产品决定（2026-11-19）
- 账号登录后各自接自己的模型 API（Claude / GPT / Gemini / Muse / DeepSeek 等，可选）——路线图 F3。
- 没有密钥的用户用平台公用接口，预充值按量扣；收美元、新币或 USDT；先按 Claude 官方 token 价定价——路线图 F8。
- 先在新加坡/海外上线，大陆（ICP 备案、经营许可、生成式 AI 登记）以后再说。

## 在哪看
- 看板（任务、沟通、进度）：https://claude.ai/artifact/GiWcZu6fZEud83sev3eGYE
- 演示页：https://claude.ai/artifact/UH7YqYkknY8EvPPsi9gM9s
- 调研档案：https://claude.ai/artifact/Vsr9WLssTvJjvPNaMTagdP
