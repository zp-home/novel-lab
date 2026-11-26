# novel-lab

面向超长篇网文（以 **5000 章 × 3600 字 ≈ 1800 万字**《四界》为基准）的 Agent 工程实验仓：解决 AI 长篇写作中的**上下文膨胀、设定遗忘、时间线串味、AI 腔调与流水账**问题。

> 在线静态演示（GitHub Pages）：<https://zp-home.github.io/novel-lab/>
> - 记忆架构大屏（7 个交互面板：四界天梯 / 7 层存储 / 时序正典甘特图 / 恒定上下文注入 vs RAG）
> - 《四界》5000 章大纲浏览器（6 幕 / 100 卷 / 500 弧 / 前 200 章节拍）
> - 正文生成进度快照 & 文体质量控制台（只读静态体验版）

---

## 核心设计（不用 RAG）

传统 RAG 用向量相似度在历史文本里捞片段，在超长篇小说里会退化：**同一人物在不同章节的境界、生死、道具归属不同，语义相近但事实互斥**。`novel-lab` 的做法是：

1. **时序正典账本（`src/canon.py`）**：所有事实带 `[valid_from, valid_to)` 区间与不可变约束，任意章节通过 `Canon.state_at(entity, chapter)` 精确还原“当时”状态，冲突在写入时即报错。
2. **恒定上下文注入（`src/verify_longform.py`）**：每段只注入「当前章纲要点 + 在场人物（≤6）+ 有效伏笔（≤8）+ 规则（≤5）+ 前文最后 400 字」，实测第 1 章与第 5000 章上下文成本漂移仅 **10.0%**（约 828～911 tokens）。
3. **四界 108 阶锯齿战力模型（`src/worldbuild.py`）**：人界 / 灵界 / 仙界 / 神界各 9 大境界 × 3 阶，绝对战力单调递增，飞升时因界壁压制重置相对阶位，避免战力通胀。
4. **四层确定性大纲（`src/outline.py`）**：零模型调用生成 `6 幕 → 100 卷 → 500 弧 → 5000 章 × 4 节拍`，结合 splitmix64 哈希终结器与材质-动作语义约束。
5. **两层文体门禁与独立评审（`src/style_contract.py`、`src/prose_judge.py`）**：
   - 生成时单段只拦结构性硬伤（字数、英文污染、模板病句、复读、套话刷屏）；
   - 整章落盘后计算 15+ 项可读性指标（`的` 字密度、超长句占比 ≥35 字、纯静物句、代称滥用、解释句、碎动作链等）。
6. **零第三方依赖 Web 控制台（`web/server.py`）**：纯 Python 标准库 + 原生 JS/CSS，支持项目管理、逐章阅读、质量榜单与后台运行控制。

---

## 目录结构

```text
novel-lab/
├── src/
│   ├── worldbuild.py        # 四界 108 阶世界观与战力曲线
│   ├── characters.py        # 8 位核心人物声线、里程碑与正典同步
│   ├── canon.py             # 时序正典账本与恒定上下文裁剪
│   ├── outline.py           # 6 幕 / 100 卷 / 500 弧 / 5000 章大纲生成器
│   ├── verify_longform.py   # 7 条架构不变量自动化验证
│   ├── style_contract.py    # 写作契约与整章文体评分器
│   ├── prose_judge.py       # 15 项可读性独立裁判（含人类样本对照）
│   ├── write.py             # 分段续写、清洗、截断与 429 退避引擎
│   ├── runner.py            # 项目断点续跑调度与 manifest 生成
│   ├── project.py           # TOML 项目配置解析
│   ├── build_dashboard.py   # 记忆大屏一键构建脚本
│   └── progress.py          # 生成进度快照生成器
├── web/                     # 本地 Web 控制台（标准库 HTTP 服务 + 纯前端）
├── projects/                # 项目配置（如 sijie.toml）
├── docs/                    # 调研、架构设计、踩坑复盘与质量标准（00~10）
├── out/                     # 静态大屏页面与评审报告
├── samples/                 # 人类样本与对比基线
└── tools/                   # 大屏 DOM 验证脚本等辅助工具
```

---

## 快速开始

> 全项目核心代码仅使用 **Python 3.11+ 标准库**（无需额外 `pip install`）。

### 1. 验证 5000 章架构不变量（不调用大模型）

```bash
python src/verify_longform.py
```

### 2. 生成大纲与记忆大屏

```bash
python src/outline.py --chapters 5000 --out out/outline_full.json
python src/build_dashboard.py
# 生成 out/dashboard.html，直接浏览器打开即可
```

### 3. 启动本地 Web 控制台

```bash
python web/server.py --port 8770
# 打开 http://127.0.0.1:8770/
```

### 4. 批量写正文（需兼容 OpenAI 接口的网关）

配置环境变量或 `~/.dsh/.env` 中的 `MAGPIE_GATEWAY_KEY`，然后运行：

```bash
python src/runner.py --project sijie --from 1 --to 200 --workers 4
```

### 5. 对生成章节跑可读性独立评审

```bash
python src/prose_judge.py out/sijie/chapters
```

---

## 开源协议

[MIT License](LICENSE)
