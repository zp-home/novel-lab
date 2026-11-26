# 01 · 长篇小说生成框架 / Agent 调研

> 调研时间：2026-11-24（star 数与"最近更新"均为当日 GitHub 页面观测值，属相对时间，仅供量级参考）
> 方法：逐项目抓取 README / 项目主页 / arXiv 摘要页原文，未抓到的一律标「未核实」，不凭记忆补。
> 结论前置：**你要的「3000 本 × 5000 字」不是长篇问题，是吞吐问题。现成框架里没有一个能直接用，但有几个的组件可以拆下来用。**

---

## 0. 一句话结论

- 5000 字/本 ≈ 2 章，**整本书塞得进一个 128K 上下文**。所有为"百万字不崩设定"设计的机制（弧预演、正史台账、分层摘要、RAG 快照、角色 Agent 决策）在这里**全是负资产**——它们把单本成本推高 10~50 倍，换来的长程一致性你根本用不上。
- 真正的瓶颈是四件事：**批量调度与重试**、**同质化（3000 本读起来像一本）**、**去 AI 味过平台审核**、**单本质检的自动化率**。
- 现成框架的默认形态全部是**单本交互式/半自动**，没有一个内置"3000 本队列 + 并发池 + 失败重入 + 去重"。
- 最值得拆的三个：**ainovel-cli**（工程骨架：确定性 Engine + Step 级 checkpoint + 七维评审）、**show-me-the-story**（单二进制、事实抽取带原文引用、可无人值守）、**Pagekin**（按章状态时间线 + 伏笔到期 + 批量创作上限 10 章，交互式质检最细）。
- 最值得抄的**文本层**：**笔巡的硬编码烂梗黑名单**（虽然项目本身是营销壳）+ **awesome-novel-agent 的 anti-ai Gate A-F 管线**。

---

## 1. 主对比表

评分：● 内置且成熟 / ◐ 有但不完整或需配置 / ○ 无 / — 不适用
「工业批量」列 = 面向"3000 本无人值守"的改造友好度。

| 项目 | 语言/栈 | 分层大纲 | 长程记忆 | 一致性校验 | 去 AI 味 | 批量并发 | 中文网文适配 | 工业批量 |
|---|---|---|---|---|---|---|---|---|
| **voocel/ainovel-cli** | Go + Bubble Tea | ● 卷/弧/章三层滚动 | ● 三级摘要+相关章推荐 | ● Editor 七维+机械自检 | ● 内置基线+可覆写 | ◐ headless 可脚本化，无队列 | ● 中文优先、CJK token 估算 | **高** |
| **Nigh/show-me-the-story** | Go + Svelte，单二进制 <5MB | ● 批量大纲 1–36 章 | ● 事实抽取带来源引用 | ● 一致性/伏笔/定稿校对 | ○ 无专门机制 | ◐ 本地多项目，无并发池 | ● 中英双语 | **高** |
| **Xiaoyangy/novel-studio** | Go，需 WSL2（Win） | ● 全书冻结+弧预演+3 章窗口 | ● RAG(BM25+向量+Qdrant) | ● exact-body 审核+SHA 绑定 | ● serial style memory 查重 | ○ 单书单 pipeline，禁并发 | ● 中文优先 | 中 |
| **PenglongHuang/chinese-novelist-skill** | JS，coding agent skill | ● 章节规划 JSON | ◐ 章节摘要+衔接记录 | ◐ 脚本查字数，Agent 审读 | ● 每章"润色去AI味"步骤 | ● 串行/子Agent并行/Agent Teams | ● 中文原生 | **高** |
| **EthanYoQ/Pagekin** | TS + Electron 桌面 | ● 蓝图逐章 | ● 按章人物状态时间线+向量检索 | ● 蓝图 AI 检查+审稿报告 | ◐ 靠导入 Skill（去 AI 味） | ◐ 批量创作一次≤10 章 | ● 中文原生 | 中 |
| **MaoXiaoYuZ/Long-Novel-GPT** | Python + Gradio/Docker | ● 大纲→章节→正文 | ● RAG 检索正文片段+剧情纲要 | ◐ 剧情纲要同步更新 | ○ | ● **多线程并行（MAX_THREAD_NUM）** | ● 中文网文 | 中 |
| **RhythmicWave/NovelForge** | Python FastAPI + Vue3/Electron | ● 雪花法+分卷/阶段/章 | ● 知识图谱(SQLite/Neo4j)+@DSL 注入 | ● 通用审核卡片 | ○ | ○ 单项目交互 | ● 中文优先 | 中低 |
| **StanleyChanH/SuperNovel** | Python FastAPI + ChromaDB | ● 架构→蓝图→章→定稿四段 | ● 向量语义检索 | ● consistency_checker | ○ | ○ | ● 中文 prompt 模板 | 低 |
| **Moosphan/novel-orchestrator** | Python 3.12 CLI | ● 总纲/卷纲/chapter brief | ● Canon 层 JSON | ● plan→draft→audit→revise | ○ | ○ 作者明确说不适合无人值守 | ● 中文优先 | 低 |
| **modoojunko/awesome-novel-agent** | Python，9 Agent skill | ● 卷纲→章纲→场景卡 | ● 动态记忆+文风蒸馏 | ● reader 10 维 60+ 细项 | ● **Gate A-F 管线+量化评分** | ◐ 单会话调度 | ● **24 套中文题材画像** | 中 |
| **wordflowlab/novel-writer-skills** | Shell/CLI + slash 命令 | ● 七步方法论 | ● tracking JSON(情节/时间线/关系) | ● 一致性检查器 | ◐ authentic-voice 插件 | ○ | ● 中文 | 低 |
| **KazKozDev/NovelGenerator** | TS，浏览器 IndexedDB | ● 因果图+章图 | ● 场景交接+rebase，抽取须引用原文 | ● 连续性检查+一次重写 | ◐ 只统计重复措辞 | ○ 单本 | ○ 英文为主 | 低 |
| **jklmgoog/笔巡 BixunAI** | 商业 SaaS | ◐ 大纲推演 | ● 号称"四维神识账本" | ◐ 号称战力/背包滚算 | ● **硬编码封杀 50+ 烂梗** | ● 号称单机 500+ 本 | ● **番茄/飞卢/起点专属** | — 闭源 |
| **NovelAI**（商业） | 闭源 Web | ○ 无大纲层 | ● **Lorebook 关键词/正则触发** | ○ | ○ | ○ | ◐ 多语言 | 低 |
| **Sudowrite**（商业） | 闭源 Web | ● Story Bible | ◐ 大纲+角色卡 | ◐ Feedback 五项 | ○ | ○ | ○ 英文向 | 低 |
| **novelcrafter**（商业） | 闭源 Web | ● 网格规划视图 | ● **Codex wiki，可跨书共享** | ◐ 规划视图查漏 | ○ | ○ | ◐ 多语言 | 低 |
| **YILING0013/AI_NovelGenerator** | Python FastAPI + Next.js + MongoDB | ● **卷→弧→场景→章纲四层** | ● 角色/势力图谱+位置化事实 | ● 章节记录变更+工作流审校 | ○ | ○ 单库多书，无并发 | ● 中文优先、中英双语 | 中高 |

---

## 2. 项目档案

### A. 工业流水线型（值得拆解）

#### 0. YILING0013/AI_NovelGenerator — 6.5k★（本领域最高），Python + Next.js + MongoDB，约 19 天前更新，AGPL-3.0

**star 最高、也是唯一把"四层规划"做成可视化可编辑画布的**。README 已明确标注 `main` 是重写版、旧版保留在 `old` 分支且**数据结构不兼容**（需分开的数据库）。

- 分层：**卷（volume）→ 弧（arc）→ 场景（scene）→ 章纲（chapter plan）**，逐层细化后才写正文。写作进度面板按这个顺序引导，每步生成后"先审阅再保存"。
- 人物与势力：**角色-势力关系图谱**（可筛选、缩放、拖拽节点、看详情），角色事实支持**按故事位置查看**（"Character facts can be viewed at story positions"）——这是时间线一致性的雏形。
- 变更审计："Chapter records help review changes to characters, relationships, items, and world rules"——按章记录设定变更，可回看。
- **可编辑 AI 工作流画布**：内置覆盖"小说创建 / 参考资料 / 规划 / 正文 / 章节检查"的流程，节点与连线可在 React Flow 画布上改，每个节点可单独选模型、改 prompt、定输入输出。这是它最值得拆的东西——**工作流即配置，批量生产时可按题材切不同模板**。
- 技术栈：Next.js 16 + React 19 + HeroUI + React Flow（前端）、FastAPI + PyMongo + PySide6（后端）、**MongoDB 8.0 单节点副本集（事务必需）**。
- 部署成本：需 Python 3.13 + Node 24 + Docker Desktop；后端 8200、前端 3300。
- 短板：**MongoDB 副本集是硬依赖**，且明确警告"已有 standalone 实例不能简单混用或同端口启动"——这对 3000 本的容器化批量部署是明显负担；**无并发调度**（单实例多书但需人工推进）；无去 AI 味机制；生成恢复"依赖原后端进程和页面，刷新或重启不保证恢复"（README 原文承认）；无公开鉴权，只能本地用。

#### 1. voocel/ainovel-cli — 2.4k★，Go，约 15 天前更新，MIT

最像"生产系统"的一个。核心设计一句话：**事实层确定，语义层自主**。

- 架构：一个串行确定性 Engine（读 Store → 查 Route 决策表 → 派发 Worker）+ 三个自主 LLM 循环（Architect / Writer / Editor）+ 按需唤醒的 Arbiter（单次调用出结构化裁定）。
- **Engine 主循环零 LLM 开销**，"下一个派谁"是纯函数查表，声称万级组合穷举测试钉死。这是控制成本的关键设计。
- 分层：卷 → 弧 → 章。**卷弧双层滚动规划**——初始只规划前 2 卷骨架 + 第 1 弧详细章节，后续到边界才展开，避免一次性规划 300 章导致大纲空洞。
- 上下文：三级摘要（章摘要滑窗最近 3 章 / 弧摘要+角色快照 / 卷摘要）+ 四级压缩管线（ToolResultMicrocompact → LightTrim → StoreSummaryCompact → FullSummary）+ 熔断器 + **CJK token 估算按 `runes × 1.5`**（不是 bytes/4，这点很关键）。
- 质检：Editor **七维评审**（设定一致性/角色行为/节奏/叙事连贯/伏笔/钩子/审美品质），审美维度再拆描写质感/叙事手法/对话区分度/用词质量/情感打动力，每项**必须引用原文举证**。
- 断点：每个工具成功后写 checkpoint，**Step 级恢复**（"第 7 章 draft 已落盘，请继续 check_consistency"）；章节提交用持久化 Saga；文件写入 temp+fsync+rename 原子。
- 去 AI 味：内置机械黑名单（`rules.SystemDefaults()`，commit 时确定性检查）+ 语义判据 `anti-ai-tone.md`；用户可在 `~/.ainovel/rules/` 丢任意 `.md` 大白话写偏好，系统归一化成结构化约束（字数范围/禁用词/疲劳词阈值）。
- 支持模型：OpenRouter / Anthropic / Gemini / OpenAI / DeepSeek / Qwen / GLM / Grok / Ollama / Bedrock + 任意自定义代理；可按角色分模型。
- 短板：**没有并发队列**，一个目录 = 一本书，`cd` 进去跑一本；TUI 优先，headless 靠外部脚本循环。没有跨书去重。没有 Web UI。

#### 2. Nigh/show-me-the-story — 649★，Go+Svelte，约 14 天前更新，MIT

**单文件可执行 <5MB**，Go 标准库 + 内嵌前端，双击就跑。工程洁癖级别的轻。

- 流程：项目 → 批量大纲（一次 1–36 章）→ 逐章生成 → 逐章审核 → 定稿校对 → 导出。
- 记忆：**事实抽取带来源引用**——抽取出的设定变更/伏笔要能指回原文；"设定变更提案"和"伏笔追踪"分开管理；知识条目"选中的整条进本次请求，后续写作时检索相关条目"。
- 一致性：明确写"主要用你的故事上下文做检查，不是在线检索"，并提醒仍需作者复核——**诚实的边界声明**。
- 支持模型：任意 OpenAI 兼容端点。
- 断点：写盘用 `progress.json.rollback` 回滚日志，重启尝试恢复最后一次完整保存；明确警告"不要对同一项目跑多个 writer"。
- 短板：无并发池、无跨书调度；去 AI 味无专门机制（靠 prompt）；数据格式 v4 与旧版不兼容。

#### 3. Xiaoyangy/novel-studio — 164★，Go，约 9 月更新，Apache-2.0

学术气最重、工程最"重"的一个。适合当**参考架构**读，不适合当底座改。

- 多 Agent：Coordinator / Architect / **Character Agent**（角色只从自己可见的观察包里选行动，不读未来大纲和他人秘密）/ **World Arbiter**（只裁决结果，不改角色意图）/ Planner / Drafter / Editor / Reviewer。
- 核心机制：全书章位**先冻结**→整弧条件预演→细推**接下来至多 3 章**→角色并行决策（默认并发 4）→Arbiter 裁决→Planner 生成 POV 章节计划→**seal 封存成不可变 render packet**→逐章渲染→exact-body 审核→通过才进正史。
- RAG：BM25/embedding/Qdrant 命中 → 必须绑定 exact source ref + content-addressed receipt → Planner 转成"事实锚点"或"写法方法" → 才进 sealed render packet。**Drafter 看不到 raw hits**。这个设计比"检索了就塞进去"高明一个档次。
- 可恢复性：pipeline/弧规划/候选正文/审核/发布全有 checkpoint、租约、幂等恢复；计划/候选/审核/发布**全绑 digest + 正文 SHA-256**，防止"返工后审核了错误版本"。
- 成本：分角色记录 input/output/cache read/write 与成本，`budget.book_usd` 可设硬停止线。
- 短板：**Windows 必须 WSL2**；**明确禁止同一本书并发跑两条 pipeline**；全文 exact-book 终审只对短篇开放；作者自己承认"百万字连续性是架构目标，不等于已完成公开生产质量验证"。

#### 4. MaoXiaoYuZ/Long-Novel-GPT — 1.3k★，Python，2025-11-05 更新

**唯一把"多线程并行"写进配置的**（`MAX_THREAD_NUM=5`），也是唯一给出"怎么堆到百万字"操作手册的：

> 创作章节 50 章 × 每章 200 字 → 创作剧情扩到 1k 字 → 创作正文扩到 2k 字 = 50 × 2k = 10 万字

三步扩写（大纲→剧情→正文）本质是**分级预算分配**，比一次性生成稳。自动切分、自动加上下文、多线程同时创作。
- 机制：大纲-章节-正文自上而下扩写；LLM + RAG 检索相关正文片段和剧情纲要；改稿时同步更新剧情纲要。
- 支持模型：OpenAI/DeepSeek/文心/豆包/本地 OpenAI 兼容（Docker 需 `--add-host=host.docker.internal`）。
- 短板：Gradio UI 简陋；无去 AI 味；"自动管理上下文"无细节；README 自己承认目标是"用户监督下达到签约门槛"，不是无人值守。

### B. Agent-Skill 型（把方法论塞进 coding agent）

#### 5. PenglongHuang/chinese-novelist-skill — 5.5k★，JS，约 9 天前更新，MIT

star 最高的中文小说 skill。本质是**提示词工程 + 流程编排**，不是软件。

- 流程：Phase 0 初始化（加载偏好/检测中断）→ Phase 1 三层递进问答（L1 必答 3 问 / L2 可跳过，支持随机生成和"都用默认"）→ Phase 2 规划确认 → Phase 2.5 **写作模式选择** → Phase 3 疯狂创作 → Phase 4 自动校验修复（最多 3 轮）。
- 三种模式：**串行** / **子 Agent 并行** / **Agent Teams**。这是它最有价值的一点——并行模式直接对应批量产出。
- 每章固定动作：写前分析 → 撰写（3000–5000 字）→ 润色去 AI 味 → 字数检查 → 更新摘要。
- 产物：`01-大纲.md`、`00-人物档案.md`、`02-写作计划.json`、`03-文风基准.md`（**文风指纹 + 基准段落 + AI 味负面清单**）、`99-章节摘要.md`。
- 内置 13 种结尾钩子类型、内容扩充技巧、对话写作规范等 references。
- 短板：依赖宿主 agent 能力；"连贯性和文字质量由 Agent 审读"——没有确定性质检；无并发调度层。

#### 6. modoojunko/awesome-novel-agent — 890★，Python，约 9 月更新，AGPL-3.0（商用需授权）

**9 个 Agent 分工**，是 skill 型里组织度最高的：

```
novel-agent（总指挥，只调度不写）
 ├ setup   → updater（设定写入）
 ├ outline → volume-planner（卷纲）→ chapter-planner（章纲）
 ├ draft   → prompt-crafter（提示词）→ writer（正文）
 ├ anti-ai → anti-ai（去 AI 味）
 ├ review  → reader（10 维 60+ 细项评审，可选）
 └ archive → updater（归档 + lore-keeping）
```

- 规划四维：**情绪走向 / 冲突阶梯（2–4 层逐级升高）/ 信息差（谁知道什么）/ 场景卡（每章 2–5 张，含目标·阻碍·悬念）**。这套中文网文方法论比多数框架的"章节大纲"具体得多。
- **style-distiller**：导入参考样本，提炼量化文风参数（句长/对话占比/形容词密度），写进风格主卡与分场景卡（dialogue/fight/group-scene），归档后增量校准。
- **anti-ai Gate A-F 管线 + 量化评分定级**，配 `knowledge/anti-ai/{genre}.md` 题材正反例库（❌ AI 味写法 / ✅ 真人感写法对照）。
- 24 套预置题材画像；动态记忆（作者反馈 → 高频规则自动晋升为永久记忆）。
- 支持平台：Claude Code / OpenCode / Reasonix / Codex / ZCode / **DeepSeek Harness** / Grok Build。
- 短板：纯 Markdown 编排，无代码级保证；单会话串行调度；商业使用需联系作者。

#### 7. wordflowlab/novel-writer-skills — 274★，Shell，2025-10-20 更新，MIT

七步方法论做成 slash 命令：`/constitution`（创作宪法）→ `/specify` → `/clarify` → `/plan` → `/tasks` → `/write` → `/analyze`。
追踪层是 4 个 JSON：`plot-tracker.json` / `timeline.json` / `character-state.json` / `relationships.json`，另有 `/plot-check` `/timeline` `/relations` `/world-check` 专项检查。
有价值的是 **spec-kit 式的"先写宪法再写内容"**——对批量生产意味着可以把"创作宪法"抽成模板变量化，这是规模化的前提。
短板：Claude Code 专用（另有跨平台版 novel-writer）；检查靠 Agent 主动调用，非自动。

### C. 桌面辅助型（人在环）

#### 8. EthanYoQ/Pagekin（原 AI 小说作家）— 2.8k★，TS+Electron，约 5 小时前更新，GPL-3.0

活跃度最高的一个（当天有提交）。设计上最贴近"中文网文作者真实工作流"。

- **按章人物状态时间线**：角色按章记状态和关系变化，写第 N 章时提示词里取**第 N 章时**的状态，不是最新值——补写前面的章不会剧透后文。这个细节很多框架都没做对。
- **伏笔到期提醒**：线索有到期章节，写到该章时把"要处理的线索"列为本章任务写进提示词，审稿时核对；支持"延后一章/三章"。
- **蓝图 AI 检查**：对照人物时间线查未定稿蓝图，找出关系颠倒或已死角色出场。
- 批量创作：**一次最多 10 章**，可暂停。
- 检索：有向量模型走语义检索，没有则本地全文检索（中文查询拆词）；**补写中间章时检索不返回该章及之后的正文**。
- 修稿：审稿报告逐条勾选 → 差异逐段确认，**AI 不直接覆盖原稿**；批注可多处攒起来一次交给模型改。
- 支持模型：OpenAI 兼容 / Gemini 原生 / Anthropic 协议，内置 DeepSeek、硅基流动、智谱、OpenAI、xAI、Gemini、Ollama 预设；可给规划/写稿/审稿/修稿/定稿后处理**分别指定模型**。
- 短板：桌面单机，无服务端队列；批量上限 10 章；去 AI 味靠导入外部 Skill。

#### 9. RhythmicWave/NovelForge — 1.3k★，Python+Vue3/Electron，约 9 月更新，AGPLv3 + SaaS 需商业授权

"卡片 + Schema"路线的代表。**核心不是生成，是可组合性**。

- Schema-first：每种卡片定义 `json_schema`，AI 生成按结构校验；实例可覆写结构。
- **@DSL 上下文注入**：`@卡片标题`、`@type:角色卡`、`@self`、`@parent`，加过滤器 `[previous]` / `[previous:global:n]` / `[sibling]` / `[index=...]` / `[filter:content.level > 5]`。这是把"给模型喂什么"变成可编程的——批量生产时最需要的正是这个。
- 知识图谱：SQLite（默认）或 Neo4j；角色/关系/场景/组织/物品/概念六类实体带状态记忆，"先预览、后确认"写回。
- 工作流：代码式（Python 风格语句 + DSL），内置"拆书工作流""雪花创作法初始化"等模板，另有 Workflow Agent 用自然语言改工作流。
- 字数控制两模式：`提示词约束`（自然、省 token）/ `控制模式`（按目标字数切多轮预算，更稳但费 token）。
- 短板：**单项目交互式**，无批量；版本迭代剧烈（0.9.0 起旧数据库不保证兼容）；作者自述"仍处迭代早期"。

#### 10. StanleyChanH/SuperNovel — 4★，Python FastAPI，约 6 月更新

star 很少但结构清晰，适合当**最小可读样本**：

- 四段式：`architecture.py`（世界观/人物/情节架构）→ `blueprint.py`（全书章节标题/定位/钩子）→ `chapter.py`（正文，语义检索取上下文）→ `finalization.py`（更新总摘要、角色状态、向量库，字数不足则扩写）。
- 独立 `consistency_checker.py` 做设定 vs 正文的矛盾检测。
- 10+ LLM provider（含阿里云百炼、火山引擎、硅基流动）；ChromaDB 向量库。
- 短板：star 4，单人项目，无并发，无断点恢复（Step 3–4 要手动一章章点）。

#### 11. Moosphan/novel-orchestrator — 3★，Python 3.12 CLI，约 5 月更新，PolyForm Noncommercial（**禁止商用**）

设计文档写得最规范（JSON Canon 设计、SQLite schema、YAML frontmatter、portable skill runtime 都有独立文档）。

- 分层：Story Assets（`story/*.md`）→ **Canon Layer**（`canon/*.json` 客观记忆）→ Skill & Rule Layer（`.agent/skills`）→ Workflow Engine（planner/writer/auditor/reviser/context compiler）→ SQLite State。
- 闭环：`plan -> draft -> audit -> revise -> canon-sync`。
- 有 `novel models scan` 扫本机 `~/.codex/config.toml`、`~/.claude/settings.json` 自动路由。
- **作者自己写死了边界**：「当前不建议直接把它当作'整本书无人干预自动生产器'来使用，更合适的方式是短批次、多复核、持续迭代」。这是全样本里最诚实的一句。
- 短板：许可证禁止商用（工业化产出直接出局）；无并发；star 3。

#### 12. KazKozDev/NovelGenerator — 160★，TS，约 10 月更新，**BSL 1.1（非 OSI 开源）**

机制上最"较真"的一个，值得抄它的记忆设计：

- **场景交接（scene handoff）+ rebase**：每个场景先折叠进 story memory 再写下个场景；交接单明确"读者已知什么 / 实际变了什么 / 哪个问题还开着 / 下个场景必须做到什么不同"；下个场景的因果计划**基于交接单 rebase** 之后才写正文。这样第 7 章承接的是书已经确立的事实，而不是第 1 章的意图。
- **抽取必须引用原文**：每条记忆记录要 cite 证明它的段落，"引用指向不存在的地方会被拒绝并重问"。
- 双模型双角色：writer 出正文，editor 规划/审阅/抽记忆/终审（"没有独立 editor 就是 writer 自评，这是本引擎允许的最弱配置"）。
- 实测数据：7 章 / 15,390 词 / 122 次模型调用 / 约 40 分钟（Ollama cloud）。
- 短板：BSL 1.1 非开源；**只在 macOS 验证过，无 CI**；只测重复措辞，不测句法节奏；JSON Schema 不合规的模型直接卡死。

### D. 商业产品

#### 13. jklmgoog/AI-Novel-Writer-Fanqie（笔巡 BixunAI）— 3★，闭源 SaaS

**必须点明：这个 README 是营销文案，不是技术文档。** 3 个 star 配一篇满是"45 秒 3000 字""单机 500+ 本""四维神识账本 v3.2""三界认知物理隔离算法"的话术，且大量伪造风格的用户证言（"笔名：九天神豪"）。技术可信度**未核实**。

但它的**问题清单值得抄**，因为它精准命中了中文网文 AI 写作的痛点：
- 50 章后吃设定、战力倒挂、女主蒸发
- "深吸了一口气""眼中闪过一丝冰冷""嘴角勾起一抹玩味的弧度""恐怖如斯"式烂梗
- 配角全知视角剧透
- 番茄首秀前三章手机端留存（段落太长视觉窒息）
- 旧书烂尾续写

声称的机制：四维状态差分账本（战力阶梯/背包/好感度滚算）、客观事实与角色视野隔离、**硬编码封杀 50+ 高频烂梗**、番茄呼吸排版（单段 1–3 句、对白独立成行）、1200s SSE 保活、旧稿逆向萃取账本。

**可用结论**：把"50+ 烂梗硬黑名单"和"手机端排版规则"当需求输入，不要指望这个产品。

#### 14. NovelAI — 闭源，订阅制

核心可抄的是 **Lorebook** 的上下文注入机制（这是业界做得最细的）：
- 每条 entry 有**激活键**，出现在最近上下文窗口就注入；键支持**正则**（`/.../`，标志 i/s/m/u）、**`&` 组合**（`NovelAI & Anlatan` 需两者都在窗口内）、**Always On**。
- 注入控制：Search Range（最大 10000 字符）、Key-Relative Insertion（正数插在键后/负数插在键前）、**Cascading activation**（在非故事上下文里继续找键）、Prefix/Suffix、**Token Budget**（可填 0–1 小数表示上下文百分比）、**Reserved Tokens**（先于所有 entry 预留）、Insertion Order、Insertion Position（0=顶部，-1=底部）、Trim Direction。
- **Phrase Bias**：按 entry 激活状态加减某些词/短语的生成概率，支持 token ID、`Ensure Completion After Start`、`Unbias When Generated`。
- 短板：无大纲分层、无一致性校验、无批处理；是"写作时的上下文引擎"，不是"出书流水线"。

#### 15. Sudowrite — 闭源，$10/月起

功能面最"面向小说家"：**Story Bible**（idea → outline → beat out chapters → 上千字）、**Write**（预测下 300 词，给多选项）、**Describe / Expand / Rewrite / Feedback（五项可执行建议）/ Canvas（情节/角色秘密/反转头脑风暴）/ Brainstorm / Visualize**，1000+ 插件（模拟读者、和角色对话、小说转剧本）。
短板：英文向；无批量；无中文网文概念；闭源不可改。

#### 16. novelcrafter — 闭源，订阅制

**Codex**（角色/地点/设定的 wiki，自动互相链接）+ 多种规划视图（网格/场景卡）+ **Codex 可跨书共享（系列级）** + 自定义提示词语法支持变量。
模型完全自带：OpenAI / Anthropic / Google / Meta / Mistral / OpenRouter(300+) / LM Studio / Ollama。
短板：无自动化产出、无并发、无中文网文适配；是给人类作者的 IDE，不是生产管线。

### E. 早期/参考实现

#### 17. jackaduma/Recurrent-LLM（RecurrentGPT 开源实现）— Python + Gradio

用自然语言模拟 LSTM 的长短时记忆：每步生成一段文本，同时更新**存在硬盘上的长期记忆**和**在 prompt 里的短期记忆**。因为记忆是人类可读可编辑的自然语言，所以**可解释、可交互修改**。
支持 openai / vicuna / chatglm / baichuan / aquila / falcon。MIT。
价值：这是"外部状态机替代上下文窗口"的祖师爷设计，后来所有"分层摘要 + 台账"都是它的变体。短板：2023 年的项目，无工程化。

#### 18. BlinkDL/AI-Writer — 3.9k★，RWKV 中文网文小模型

不是框架，是**中文网文预训练小模型**（RWKV，类 GPT-2，上下文仅 512 字）。README 自己标注"下面都是过时的信息！过时的模型！"，并指向 RWKV-Runner 的 1.5B/3B/7B 网文模型。
价值：证明"网文语料微调的小模型"在**文风地道度**上可以超过通用大模型（生成示例确实像人写的）。对工业化的启发是：**如果 3000 本要统一文风，微调一个小模型比 3000 次 prompt 调教便宜得多**。

---

## 3. 学术侧：每个解决了什么"长篇"问题

| 论文 | 出处 | 一句话：解决了什么 |
|---|---|---|
| **LongWriter**（2408.07055，THUDM） | ICLR 2025 | 证明**模型的有效生成长度被 SFT 数据里的长输出样本卡死**，不是能力问题。用 AgentWrite 把超长生成拆成子任务，配 LongWriter-6k（6k 条 2k–32k 词输出）微调，把输出拉到 **10,000+ 词**；9B 模型加 DPO 后在 LongBench-Write 上超过大得多的闭源模型。 |
| **RecurrentGPT**（2305.13304） | 2023 | Transformer 固定上下文导致无法生成长文本。用自然语言模拟 LSTM：每步生成一段 + 更新硬盘上的长期记忆与 prompt 里的短期记忆，实现**任意长度不遗忘**，且记忆可读可编辑 → 可交互生成。 |
| **Re3**（2210.06774） | EMNLP 2022 | 2000+ 词故事的长程情节连贯。四步：构造结构化总纲 → 反复把"计划 + 当前故事状态"注入 prompt 生成段落 → **对多个续写重排序**（情节连贯性 + 前提相关性）→ 对最佳续写做事实一致性编辑。人类评测：整体情节连贯 **+14%**、贴合初始前提 **+20%**。 |
| **DOC**（2212.10077） | ACL 2023 | 大纲不够细，正文就会跑偏。**detailed outliner**（更细的分层大纲，把创作负担前移到规划阶段）+ **detailed controller**（生成时强制段落对齐大纲细节）。相对 Re3：情节连贯 **+22.5%**、大纲相关性 **+28.2%**、有趣度 **+20.7%**。 |
| **CONCOCT**（2311.04459） | EMNLP Findings 2023 | **节奏失控**——该详写的略过、该略过的狂写。训一个"具体度评估器"判断两个事件哪个更具体，用它在分层大纲生成里做 **vaguest-first 扩展**（追求均匀节奏）+ 过滤新大纲项。57% 的情况下人类认为节奏更一致。 |
| **Agents' Room**（2410.02603） | ICLR 2025 | 靠复杂 prompt 写不出好小说。按叙事理论把写作**拆成专门 Agent 的子任务**协作完成；配套 Tell Me A Story 数据集和长叙事评测框架。专家评审优于基线。 |
| **StoryWriter**（2506.16445） | 2025 | 话语连贯 + 叙事复杂度两难。三模块：**outline agent**（事件级大纲，含角色与事件-事件关系）→ **planning agent**（细化事件并分配到各章，保证交织感）→ **writing agent**（按当前事件**动态压缩故事历史**再生成）。产出 LongStory 数据集（约 6000 篇，均长 8000 词），微调出 StoryWriter_GLM。 |
| **DOME**（2412.13575） | 2024 | 刚性大纲 + 缺宏观规划。**Dynamic Hierarchical Outline**（把小说理论引入大纲规划，且**计划与写作阶段融合**，随生成过程自适应调整）+ **Memory-Enhancement Module**（基于**时序知识图谱**存取已生成内容）+ **Temporal Conflict Analyzer**（用时序知识图谱自动评估上下文一致性）。 |
| **ConWriter**（2608.05169） | EMNLP Findings 2026 | 长故事里时间/事实/角色/常识/文风错误会累积。训练-free：场景级增量写作，维护演进中的故事状态，**检查新场景是否满足必需的叙事转移**，用**不确定性感知的风险信号**优先验证和局部修复——在错误传播到后续场景之前拦住。明确报告在叙事一致性上超过 DOME。 |
| **Long Story Generation via KG and Literary Theory**（2508.03137） | 2025 | 大纲式生成的两个通病：**主题漂移**（忘了前面的大纲）和**情节乏味逻辑不通**。多 Agent + 记忆存储（长期记忆挑最重要的、短期记忆留最近几轮大纲）+ 基于叙事学理论的"故事主题障碍框架"（引入不确定因素和评价标准）+ 知识图谱加新节点 + **模拟作者-读者对话**来修订。 |

**学术侧对工程的三条硬结论**：
1. **单次输出长度是训练问题不是提示问题**（LongWriter）——指望 prompt 让模型一次吐 5000 字中文，不如分两次各 2500 字再衔接。
2. **大纲越细，正文越不跑偏**（DOC），但**大纲必须能随写随改**（DOME），刚性大纲会僵死。
3. **记忆要用结构化状态（时序知识图谱/状态机），不要用"摘要文本堆"**（DOME、ConWriter、novel-studio 的 sealed packet 都在往这个方向收敛）。

---

## 4. 工业化结论：3000 本 × 5000 字

### 4.1 先纠正一个前提

5000 字/本，按中文网文 2000–3000 字/章算是 **1.5–2.5 章**。总量 3000 × 5000 = **1500 万字**。

这意味着：
- 单本**不需要跨会话记忆**。5000 字 ≈ 7500 tokens 输出，加设定/大纲/风格锚点也就 20k–30k tokens 输入，**一次请求能装下整本书**。
- 所有框架的核心卖点——弧预演、正典台账、分层摘要、角色 Agent 独立决策、RAG 快照、SHA 绑定审核链——**在这个规模上是纯开销**。novel-studio 跑一本 5000 字的书要过 architect/zero-init/preplan/rehearse-arc/project-all/seal/promote/render/review 十几道关，单本模型调用可能在 30–60 次量级；而"一次性生成 + 一次质检 + 一次去味"只要 3–5 次。**成本差 10 倍以上，质量差不到 10%。**
- 真正需要跨书的是**去重**：3000 本同一题材，开局、金手指、打脸桥段会高度同质。

### 4.2 能直接改造的

| 来源 | 拆什么 | 怎么用 |
|---|---|---|
| **ainovel-cli** | 确定性 Engine + Route 决策表的**分层思想**；Step 级 checkpoint 与幂等重放；`temp+fsync+rename` 原子写；CJK token 估算 `runes×1.5`；七维评审的**"每项必须引用原文举证"** | 把"一本书的 pipeline"换成"3000 本的队列 + 单本 5 步流水线"，Engine 层几乎不用改结构 |
| **show-me-the-story** | 单二进制部署形态；事实抽取**带来源引用**的校验思路；"不跑多 writer 对同一项目"的锁 | 单本产物自包含、可打包、可迁移，适合当 worker 镜像 |
| **AI_NovelGenerator** | **可编辑 AI 工作流画布**（节点级选模型/改 prompt/定 IO）+ **卷→弧→场景→章纲四层** + 角色/势力图谱 | 按题材切不同工作流模板 = 批量生产的多形态出书；但 MongoDB 副本集依赖要换成 SQLite/PG |
| **Pagekin** | 按章**状态时间线取值**（写第 N 章取第 N 章状态）；**伏笔到期章节**；蓝图 AI 检查（已死角色出场/关系颠倒）；批量创作 ≤10 章的分批节奏 | 短书用不到时间线，但"伏笔到期 + 蓝图矛盾检查"是 5000 字也要的质检项 |
| **Long-Novel-GPT** | **多线程并行 + 分级预算扩写**（200 字大纲 → 1k 剧情 → 2k 正文） | 直接对应"一次出稿不稳，分两级扩写更稳更省" |
| **chinese-novelist-skill** | 三种写作模式（串行/子 Agent 并行/Agent Teams）；`03-文风基准.md` 的**文风指纹 + 基准段落 + AI 味负面清单** | 文风基准文件 = 3000 本的"统一声音"锚点；并行模式 = 吞吐 |
| **笔巡 README（当需求文档）** | **50+ 烂梗硬黑名单**、番茄呼吸排版（单段 1–3 句、对白独立成行） | 确定性可执行的后处理规则，比"让模型别写 AI 味"有效得多 |
| **awesome-novel-agent** | **anti-ai Gate A-F 管线 + 量化评分定级**；`knowledge/anti-ai/{genre}.md` 正反例库格式（❌/✅ 对照） | 建 3000 本共用的质检门禁 |
| **novelcrafter / NovelAI** | NovelAI Lorebook 的 **Token Budget / Reserved Tokens / Insertion Order / Phrase Bias** 思路 | 短书用不到复杂注入，但 **Phrase Bias 可以当"禁用词硬约束"** 用 |
| **LongWriter / DOC / CONCOCT** | 分级大纲 + 具体度控制 | 5000 字的"分层"只需 3 层：一句话 premise → 5–8 个 beat → 正文，且每 beat 的字数预算要显式分配（CONCOCT 的均匀节奏） |

### 4.3 现成框架集体缺的（必须自建）

1. **任务队列与并发池**。所有 19 个样本里，只有笔巡（闭源营销）和 Long-Novel-GPT（5 线程配置）提到并发。没有一个是"提交 3000 个 job、自动重试、断点续跑、限速、按 provider 分池"的系统。这是最大的空白，也是最容易自建的部分。
2. **跨书去重 / 多样性控制**。没有任何框架有。3000 本同题材必须做：开局类型轮换、金手指类型轮换、桥段指纹去重（对生成结果做 n-gram 或 embedding 相似度拦截）、prompt 模板变量化（题材 × 主角身份 × 冲突类型 × 结局类型做正交组合表）。
3. **自动质检的"过/不过"判定**。现有框架的审核全是"输出一份评审报告给人看"。工业化要的是**确定性可判定的门禁**：字数区间、禁用词命中数、段落长度分布、对话占比、句长方差、重复 n-gram 率、伏笔回收率。报告要能直接触发重跑，不是给人读。
4. **成本与限速治理**。只有 novel-studio（`budget.book_usd` 硬停止）和 ainovel-cli（按角色分模型）有雏形。3000 本必须做：单本预算上限、provider 配额池、失败重试的退避与熔断、token 用量台账。
5. **确定性后处理链**。去 AI 味目前全靠 prompt 或 Agent 自觉。要变成**流水线后处理**：正则替换黑名单 → 段落切分重排 → 句长/标点规范化 → 敏感词过筛 → 平台排版格式（番茄/起点各自的段落与空行规则）。这一步不该花模型调用。
6. **中文短篇的"完本感"**。5000 字要收尾，而所有框架的规划层都是为"连载"设计的（滚动展开、卷弧、章末钩子）。需要一个**闭环结构模板**（起-承-转-合的字数配额），否则 3000 本会全部烂尾。

### 4.4 建议架构（一句话版）

```
任务表(3000) → 调度器(并发池/重试/限速/预算)
   → 单本 5 步：① 组合参数采样(去重) ② 三层大纲(含字数配额)
                ③ 分级扩写(2 次生成，非 1 次长生成)
                ④ 确定性后处理(黑名单/排版/规范化)
                ⑤ 确定性门禁(字数/禁用词/重复率/段落分布) → 不过则重跑
   → 产物落盘(单本自包含) + 用量台账
```

模型只出现在 ②③，其余全是确定性代码。这个架构里，**上面 19 个项目一个都不能直接用**，但 ainovel-cli 的 Engine 分层、Long-Novel-GPT 的并行与分级扩写、笔巡的黑名单与排版规则、awesome-novel-agent 的 Gate 管线，四样拼起来就是完整答案。

---

## 5. 核实状态

**已抓原文核实**（README / 项目主页 / arXiv 摘要页）：
AI_NovelGenerator、ainovel-cli、show-me-the-story、novel-studio、chinese-novelist-skill、Pagekin、NovelForge、SuperNovel、novel-orchestrator、awesome-novel-agent、novel-writer-skills、KazKozDev/NovelGenerator、Long-Novel-GPT、笔巡 README、Recurrent-LLM、AI-Writer、NovelAI 文档、Sudowrite、novelcrafter、LongWriter、RecurrentGPT、Re3、DOC、CONCOCT、Agents' Room、StoryWriter、DOME、ConWriter、KG+Literary Theory。

**未核实 / 存疑**：
- 笔巡（BixunAI）全部技术声明：README 为营销文案，3★，无代码可查，所有性能数字（45 秒 3000 字、单机 500+ 本、四维神识账本 v3.2）均**未核实**。
- 商业产品（NovelAI / Sudowrite / novelcrafter）的功能细节来自官网/文档，**价格与版本未核实**，且均为闭源不可改造。
- 各项目"最近更新"为 2026-11-24 页面相对时间，未取 commit 时间戳。
- 任务描述中提及的 `Xiaoyangy/novel-studio` 以外几个候选——`Shine8592/novel-writer-skills`（16★，搜到但未抓正文）、`hzhang092/novel-agent`（4★，未抓正文）、`mazzzystar/N-Grams-novel`（未搜到，可能不存在）——star 过低或无法确认，未纳入正文分析。
- `MuMuMu1/MuMuAINovel` 返回 404，不存在。
