# 学习大脑 v0

一个外置的“经验记忆 + 任务调度 + 验证门”。模型本身不会记住上一次会话学到的东西，所以所有学习都落在这个目录里：每次干活前先读它，干完再写回去。

## 目录

| 位置 | 内容 |
| --- | --- |
| `brain.py` | 命令行：next / recall / start / log / new-card / use / done / verify / stats |
| `cards/L*.md` | 工作方法经验（我怎么干活不出错） |
| `cards/P*.md` | 产品设计经验（我们的 AI 建站工作台该怎么做） |
| `self/能力.md`、`self/缺陷.md` | 自我认知：验证过的能力、犯过的错及防法 |
| `tasks.json` | 任务队列 |
| `journal/` | 按天的工作日志、全量扫描结果 |
| `checks/` | 把经验固化成的确定性检查脚本 |
| `evals/` | 验证门：评测用例、事实清单、测试样本 |
| `bootstrap.sh` | 新环境里恢复评测所需的仓库（只读） |

## 工作协议（每个任务都走一遍）

```
python3 brain.py next              # 取下一个任务，并自动回忆相关经验（L、P 各前 3）
python3 brain.py start T10
……干活……
python3 brain.py use L006          # 用上了哪条经验就记一次
python3 brain.py log "做了什么、发现了什么"
python3 brain.py new-card --prefix P --title "..." --trigger "..." --scope 产品
python3 brain.py verify            # 验证门：全部通过才算数
python3 brain.py done T10 "结果"
python3 brain.py stats
```

## 举一反十的四个机制在这里怎么落地

1. **抽象**：卡片写“根因 / 做法 / 反例”，不写一次性的补丁。
2. **固化**：能变成脚本的就进 `checks/`（例：许可证漏判 → `license_scan.py`）。
3. **扩散**：固化后立刻对全部对象重跑（例：157 个仓库全量重扫，发现 Easyblocks 专有子包）。
4. **验证门**：`evals/cases.json` 里的每条用例都绑定一张卡片；卡片状态由验证门自动改为 verified / failing。

## 跨会话延续

- 新会话开始时：把这个目录放回工作区，运行 `bash bootstrap.sh`，再 `python3 brain.py verify` 和 `python3 brain.py next`。
- 建议把整个目录放进一个 Git 仓库，每次会话结束提交一次，变更历史本身就是“成长记录”。
- 卡片超过约 100 张后，再考虑把检索换成向量检索（见 L013）。


## 产品图纸（product/，2026-11-18 第二轮）

AI 建站流水线里 Agent 之间交接的三份图纸，以及它们的检查工具。

| 文件 | 作用 |
| --- | --- |
| `product/schemas/brief.schema.json` | 需求简报：一句话需求 → 目标、受众、风格、功能、最多 3 个问题 |
| `product/schemas/site.schema.json` | 网站结构：页面、导航、用户流程、数据实体、谁负责产出什么 |
| `product/schemas/page.schema.json` | 页面线框：区块树（与 Puck 同构）、布局、按钮去向、动效 |
| `product/schemas/vocab*.json` | 封闭词表，由 `tools/gen_vocab.py` 从 UI UX Pro Max 数据生成，勿手改 |
| `product/tools/check_blueprints.py` | 跨文件检查，30 个错误码（错误与提醒），每条带“下一步” |
| `product/tools/mutation_test.py` | 把合格示例改坏 27 次，检查器必须全部抓到 |
| `product/tools/kb.py` / `kb_scan.py` | 知识库名称 → ID 解析（含别名、组合名、弃用跳转） |
| `product/examples/` | 咖啡馆预约、SaaS 官网、插画师作品集三套完整示例 |

运行：`python3 -I product/tools/check_blueprints.py product/examples/cafe`

## 防死循环（2026-11-18 第三轮）

| 文件 | 作用 |
| --- | --- |
| `product/tools/fix_guard.py` | 修复回路守卫：八种刹车（G01–G08），停下时回滚到最好的一版并用人话告诉用户 |
| `product/tools/fix_guard_sim.py` | 25 项模拟，含 2000 条永远修不好的随机序列 |
| `product/tools/fix_guard_mutation.py` | 逐个拆掉 11 个刹车，模拟必须发现 |
| `checks/loop_audit.py` | 大脑自查：循环要写明为什么会结束、子进程和网络命令要有超时 |
| `brain.py` 的 `run_bounded` | 验证门超时杀掉整个进程组，不会被子进程拖住 |

规则：所有测试命令都用 `timeout N python3 -u` 运行。

## 原型：存档回滚 + 修复回路（2026-11-18 第四轮）

| 文件 | 作用 |
| --- | --- |
| `product/proto/workspace.py` | 整批预检、全有或全无写入、每轮一个 git 提交、回滚用新提交（不改写历史） |
| `product/proto/fix_loop.py` | 构建 → 报错 → 修复者 → 守卫 → 回滚；反馈写回修复者；循环自带兜底上限；写修复记录 |
| `product/proto/site_build.py` | 原型用的“构建”：静态小站的死链、缺 title、缺 alt、重复 id |
| `product/proto/proto_test.py` | 端到端 28 项：真实 git 仓库里的 7 种修复情况 |
| `product/proto/proto_mutation.py` | 逐个拆掉 8 处保护措施，测试都必须发现 |

## 看板

`python3 brain.py export` 导出六张表到 `dashboard/`，上传到看板“学习大脑 · 沟通与进度”
（https://claude.ai/artifact/GiWcZu6fZEud83sev3eGYE ，slug 7f44d303-59ba-467c-be8f-7c731ee8d477）后，
更新各数据源的文件地址即可。`python3 brain.py comm --who 用户|我 "内容"` 追加沟通记录。

## 真实构建与模型接口（2026-11-18 第五轮）

| 文件 | 作用 |
| --- | --- |
| `product/gen/generate.py` | 图纸 → 真实网站：路由、导航、面包屑、sitemap 都从网站结构生成；`custom/site.js|css` 原样带进每页 |
| `product/gen/browser_check.py` | 本机 Chrome 打开每页（桌面 1280 / 手机 375），收集 9 类问题；需要 `/usr/bin/google-chrome` 和 Python playwright |
| `product/proto/real_build.py` | 修复回路用的真实构建：图纸检查 → 生成 → 浏览器检查 |
| `product/proto/model_fixer.py` | 模型修复者：流式读取 + 复读检测 + 长度上限 + 解析回告；密钥只读 `SITE_BUILDER_API_KEY`（可选 `SITE_BUILDER_API_URL`） |
| `product/tools/repeat_guard.py` | 模型复读检测（结尾周期检测） |
| `checks/code_coverage.py` | 每个图纸错误码都必须有反例 |
| `runs/fix_runs.jsonl` | 修复记录，导出到看板“修复记录”一节，用于以后校准守卫阈值 |

真实调用模型：`export SITE_BUILDER_API_KEY=...` 后，用 `ModelFixer()`（不传 transport）替换测试里的模拟修复者。

## 文字建站（2026-11-18 第六轮）

```
python3 -I product/text2site/make_site.py "帮我做个咖啡馆网站，能在线预约，别太花哨" --out /tmp/x --preview   # 三种风格并排预览
python3 -I product/text2site/make_site.py "……" --out /tmp/x --style soft-ui-evolution                     # 选定风格生成整站
```

| 文件 | 作用 |
| --- | --- |
| `product/text2site/understand.py` + `lexicon.py` | 文字 → 需求简报（中文词表 + 知识库；最多 3 个带默认答案的问题） |
| `product/text2site/plan.py` | 简报 → 网站结构 + 页面线框 + 设计规范 + 文案 |
| `product/text2site/styles.py` | 风格 → 设计令牌；六种风格家族；三个候选观感不同；对比度自动修正 |
| `product/text2site/copywriter.py` | 文案 Agent 第一版：初稿，评价/数据/价格一律待填 |
| `product/text2site/t2s_eval.py` | 14 句评测 + 6 句留出集，整站过图纸检查和真实浏览器检查 |
| `product/text2site/demo/cafe_preview.html` | 咖啡馆一句话的三种风格对比页（已发布为 artifact） |

## 工作台与完成度（2026-11-18 第七轮）

- `python3 -m product.app.server --port 8765`：本机工作台（只监听 127.0.0.1）。四步：一句话 → 确认理解/回答追问 → 三种风格预览 → 选定后生成整站并在真实 Chrome 里检查。
- `product/app/app_test.py`：端到端 21 项（流程、选择学习、路径穿越、伪造会话、超长输入、超大请求体）。对应用例 E42。
- `product/text2site/prefs.py`：记录每次选了哪种风格（只存文字指纹）。同行业 ≥2 票且过半 → 下次排第一。
- `roadmap.json` + `python3 brain.py progress`：按证据计算完成度；“已完成”项的证据用例有一条没过就自动降为“部分”。`export` 同时导出 roadmap 表给看板。
- 浏览器检查新增“首屏内容看不见”（用例 E43，夹具 evals/fixtures/badsite2）。
- 当前完成度 63%（上一轮 56%），验证门 43/43。

## 喂养学习与自我纠错（2026-11-18 第八轮，两项核心要求）

**喂养**（product/text2site/feed.py、learned.py；知识存 knowledge/learned.json，喂养记录存 knowledge/feeds.jsonl）
- `python3 -I product/text2site/feed.py add "猫咖是咖啡馆，要放猫咪照片。律所别用深色。花店要用复古风格"`
- `python3 -I product/text2site/feed.py add --html 喜欢的网站.html --for 咖啡馆`（只静态解析样式，不运行脚本、不联网、不存文字）
- `feed.py list | undo K003 | audit`
- 只抽三类封闭字段：新说法、纠正、参考网站观感。必须指向具体行业；全局指令、代词一律不学。
- 试跑三关：评测集里无关句子不许变 / 自测 / 已学知识仍成立；参考网站还要真的生成一个网站并过检查。
- 复核：单独不成立的停用；和老知识矛盾的，停用较新的那条。这一次用户说的话永远优先。

**自我纠错**（product/text2site/autofix.py；纠错记忆存 knowledge/fix_memory.json）
- 工作台选定风格后自动走：生成 → 检查 → 按诊断从封闭清单（gen/generate.py 的 FIX_CSS）选修补 → 复查；FixGuard 刹车。
- 修补带来新问题或没效果就撤回；不认识的问题不瞎修，记进待学清单。
- 修好的记成“病因 → 修补”，先只用于同行业同风格；后台对照实验（另外两个行业 × 风格：不加出问题、加了就好）通过后推广，下次生成前（含预览）提前避开。
- 预防屡次失手就停用；多行业多次成功会建议写进生成器默认样式（不自动改代码）。
- `python3 -I product/text2site/autofix.py memory | generalize | suggest`

测试：`selflearn_test.py`（E44，34 项）、`checks/feed_injection.py`（E45）、工作台端到端 37 项（E42）。
评测（t2s_eval、styles_test）默认用空知识库，测的是代码，不受用户喂过的东西影响。

## 对话式修改与视觉审查（2026-11-18 第九轮）

**对话式修改**（product/text2site/edit.py；工作台 /api/edit；测试 edit_test.py，E48）
- 网站生成后，在“想改哪里？直接说”里输入，例如：按钮换成绿色，再加一个相册 / 去掉博客 / 换成复古风格 / 名字改成 Blue Bottle Coffee / 撤销。
- 只认六种操作；看不懂的原样交回，并记进待学清单（knowledge/edit_backlog.jsonl）。
- 做不出来的功能不假装加；目标必需的页面不删；改完问题变多就保留上一版。每个版本都保留，可撤销。
- 去功能、换风格会给出“以后同行业都这样？”的建议句，点一下就走喂养流程。

**视觉审查**（product/gen/browser_check.py；样本 evals/fixtures/badsite3，E49）
- 手机宽度下量：文字对比度（正文 4.5:1、大字 3:1）、点按区域（≥ 24×24px）、字号（≥ 12px）。背景是图、渐变或毛玻璃时不判。
- 第一次量就发现三类老问题，已在生成器默认样式里修好：链接颜色单独算到 4.5:1；导航和面包屑链接 44px 高；卡片文字用前景色（以前大色块家族里白底白字）。
- 自我纠错新增修补 tap-targets（点按区域太小 → 加大）；对比度问题只报告、不打补丁。

## 一键运行、导出与模型接入（2026-11-19 第十轮）

**在你自己的电脑上运行**
- macOS / Linux：`sh start.sh`；Windows：双击 `start.bat`；或 `python3 product/app/start.py`（`--check` 只自检）。
- 需要 Python 3.9+。浏览器检查需要 `pip install playwright` 和本机 Chrome（找不到就跳过这一道检查并说明，不影响生成）。
- 只听本机 127.0.0.1；每次启动换新令牌，别的网页不能偷偷调用；Host 只认本机。
- 生成的网站可以“下载第 N 版网站（压缩包）”：双击里面的 index.html 就能离线浏览，整个文件夹可直接上传任意静态托管；压缩包里有中文上线说明。

**模型设置**（工作台里的“模型设置”；代码在 product/models/）
- 服务商：Anthropic、OpenAI、DeepSeek、通义千问、Kimi、智谱、豆包、OpenRouter、本机 Ollama、自定义（任何 OpenAI 兼容接口）。
- 填密钥 → 测试连接 / 获取模型列表 → 给“理解需求”“写文案”“修复”分别选服务商和模型。
- 密钥存在 ~/.aisite/models.json（权限 600，不在 brain 文件夹里，打包导出都不会带走）；也可用环境变量 AISITE_KEY_<服务商ID大写>。
- 安全：地址必须 https（本机可 http）；不跟随跳转；限流/出错最多再试一次；每次建站最多调用 N 次（可设）；错误信息里抹掉密钥。
- 模型的输出只当草稿：理解只收清单里的值、名字必须出现在原话里；文案逐处查字数、数字、极限词、评价、网址；不合格的退回规则版，界面写明用了什么、丢了什么。
- 测试：models_test.py（E51）、llm_test.py（E52）都用本机假服务，没有对真实服务商验证过。

## 第十一轮（2026-11-19）：补完对话修改、上线前体检、国内合规、发布测试

- 依赖：`requirements.txt`（必需 jsonschema；可选 playwright）。`start.sh` / `start.bat` 首次运行会自动装必需依赖。支持 Python 3.9 及以上（已在 3.9 / 3.11 / 3.13 的全新环境里测过）。
- 对话修改新增：标题 / 介绍 / 号召改成…、字大一点 / 小一点、圆角大一点 / 改成直角、间距宽松 / 紧凑。
- 上线前体检（product/gen/site_audit.py）：SEO、性能、无障碍、合规四项打分，工作台里选定网站后显示。
- 导出时可填域名（生成 sitemap.xml 和规范网址）和 ICP 备案号（加到每页页脚，链接到工信部备案网站）。
- 表单提交前要勾选同意隐私政策；隐私政策页按“收集什么、做什么用、保存多久、怎么删除”给出待填模板。
- 发布测试：`python3 -I product/release_test.py <压缩包> <python>`；旧版 Python 兼容检查：`python3 -I checks/py_compat.py`。

## 第十二轮（2026-11-19）：工作台界面改版

- 分成三个标签页：**建站**（主流程）、**教它**（喂知识、喂喜欢的网站、撤回）、**模型**（填密钥、按用途选模型）。标签页可用左右方向键切换。
- 顶上 1–4 步的步骤条，只亮当前这一步。网站生成后，读懂的需求和三个预览自动收起，点“换一种风格或改回答”可以展开。
- 网站占主区域，可切电脑 / 手机宽度；右边一列是修改框（回车提交）、上线前体检、下载、自我纠错。
- 界面文字全部改成用户的话（行业、目标、风格中文名、推荐理由）；“规则版”只在顶栏说一次。
- 页面高度：电脑 4421→1372px，手机 7308→2149px。前后对比见演示页第 16 节（product/app/demo.html）。

### 模型填写模板（11-19 补）

- `product/models/models.example.json`：复制成 `~/.aisite/models.json`，只填你有的那家密钥，在 `roles` 里给用途选服务商和模型名；全部留空也能用（规则版）。
- 新增 Google Gemini（官方 OpenAI 兼容接口）。Meta Muse 目前只对美国开发者公开预览，拿到后用“自定义”填它的地址和密钥。
- 以后上线账号系统时：登录后各自填自己的密钥（F3）；没有密钥的用平台公用接口、预充值按量扣（F8，收美元 / 新币 / USDT，先按 Claude 官方 token 价）。
