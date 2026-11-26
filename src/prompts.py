#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompts.py —— 分层提示词模板（整套方案的核心资产）

设计哲学
--------
普通做法：给模型一个 prompt，让它"写一篇 5000 字的小说"。
结果：模型在 300 字之后开始平均化，5000 字全是套话。

本方案把"写小说"拆成 6 个不可合并的步骤，每步只解决一个问题：

    S1 选题 → S2 设定圣经 → S3 分章大纲 → S4 场景 beat 表
    → S5 正文（分 3 段滚雪球）→ S6 去 AI 味重写 → S7 质检修复

关键约束（写进每个 prompt 里）：
1. **不允许模型自己决定"接下来写什么"**——接下来写什么由大纲决定。
2. **每段 600-800 字**，不是一次 5000 字。长输出必然平均化。
3. **负向清单**比正向要求有效 10 倍。"不要写什么"要列到词级。
4. **禁止解释性收尾**。每段必须以动作/物件/对话结束。
"""

from __future__ import annotations

# ==========================================================================
# 全局负向清单（所有环节共用）
# ==========================================================================
BANNED_WORDS = """
仿佛、似乎、不禁、不由得、缓缓、微微、轻轻、悄然、默默、一丝、一抹、一缕、
几分、些许、隐约、恍惚、如同、宛如、犹如、恰似、瞳孔骤缩、瞳孔微缩、
嘴角勾起、嘴角微微上扬、眼底闪过、眼中闪过、不易察觉、若有所思、意味深长、
深吸一口气、缓缓开口、沉默片刻、良久、叹了口气、苦笑一声、眼神复杂、
神色复杂、心中涌起、心头一震、心中一惊、五味杂陈、百感交集、如遭雷击、
难以言喻、无法言说、不知为何、与此同时、然而、尽管如此、总而言之、
换句话说、值得一提的是、命运的齿轮、冥冥之中、这一刻、就在这一刻、
终于明白、恍然大悟、一切都不一样了、无尽的、深深的、淡淡的、莫名的、
前所未有的、难以形容的、无法抗拒的、令人窒息的、如同时间静止、
仿佛时间静止、仿佛整个世界、如同一道闪电、如同一记重锤
"""

BANNED_STRUCTURES = """
1. 禁止段末总结/升华。段落的最后一句必须是具体动作、具体物件、或一句对话。
2. 禁止"不仅…而且""既…又""不是…而是"这类对仗句式。
3. 禁止三句以上连续排比。
4. 禁止用"他感到/他觉得/他心中"引出情绪，改用身体反应或动作失误。
5. 禁止解释人物为什么这么做。读者要自己看出来。
6. 禁止让配角说出主题句。主题只能由情节呈现。
7. 禁止"总结全文"式结尾。
8. 禁止每段长度相近。段落必须有长有短，最短可以只有一行。
"""

STYLE_CONTRACT_TEMPLATE = """
【写作契约·硬约束，违反任何一条都算失败】

一、句子
- 平均句长 12~18 字。每 200 字内至少出现 2 个 8 字以内的短句。
- 禁止连续 3 个长句。长句之后必须跟短句。
- 句长必须有明显起伏：最短 2 字，最长可到 50 字。

二、描写
- 只写"摄像机拍得到、录音机录得到"的东西：动作、器物、声音、气味、温度、光影。
- 不写"他感到""他心想""他意识到"。
- 抽象名词（命运、意义、救赎、灵魂、价值、本质）全篇出现不超过 3 次。

三、对话
- 对话必须口语化，允许打断、答非所问、说半句、沉默。
- 禁止解释性台词（"你知道的，自从那件事以后……"这种交代信息的句子）。
- 每个主要人物有独立的说话方式：句子长短、口头禅、避讳的词，都不同。

四、结构
- 每段结尾停在具体动作或物件上，不做总结。
- 场景转换用硬切，不用"与此同时"之类的过渡。
- 不解释因果。把因果留给读者。

五、禁用词（出现任何一个即判定失败）
{banned_words}

六、禁用结构
{banned_structures}
"""


# ==========================================================================
# S1 选题：从种子生成一句话故事 + 反套路约束
# ==========================================================================
S1_PREMISE = """你在为一个工业化小说生产流水线设计第 {book_id} 号选题。

【八维种子（不可更改，必须全部用上）】
题材：{genre}
空间：{setting}
核心冲突：{conflict}
叙事视角：{pov}
时间结构：{time}
结局基调：{ending}
主角处境：{protagonist}
核心意象：{motif}
语体：{register}
信息密度：{density}

【任务】
写出这部小说的一句话故事（logline）和三个"反套路"设计。

要求：
1. logline 必须是一句话，40~60 字，包含：谁 + 处于什么处境 + 想要什么 + 被什么挡住。
2. logline 里不允许出现"命运""救赎""成长""自我"这些词。
3. 三个"反套路"设计，每条形如「常见写法是 X，本书改成 Y」。必须具体到情节，
   不能是"人物更立体"这种空话。
4. 给这个故事定一个"读者读完会记住的那个画面"——一句话，具体到器物和动作。

【输出格式，严格 JSON，不要任何解释文字】
{{
  "title": "书名（4~8 字，不要副标题，不要书名号）",
  "logline": "一句话故事",
  "anti_tropes": ["常见写法是……，本书改成……", "……", "……"],
  "memorable_image": "一个具体的画面",
  "theme_implicit": "本书想说什么（这句话不会出现在正文里，只用来约束写作）"
}}
"""


# ==========================================================================
# S2 设定圣经
# ==========================================================================
S2_BIBLE = """你在为小说《{title}》建立设定圣经（Story Bible）。这本圣经将作为后续
所有章节生成的唯一事实来源，任何与它冲突的正文都会被自动判为失败。

【故事】
logline：{logline}
题材：{genre}｜空间：{setting}｜核心冲突：{conflict}
视角：{pov}｜时间结构：{time}｜结局基调：{ending}
主角处境：{protagonist}｜核心意象：{motif}
反套路设计：{anti_tropes}

【任务】建立以下 6 张表。

1. 人物表（3~5 人，不要更多）
   每个人必须有：
   - id / name / aliases（别人怎么称呼他，至少 2 种）
   - immutable：**不可变事实**。这是硬约束，全书不能改。只写身体特征、旧伤、
     胎记、口音、残疾这类。每人 1~2 条。要具体到能被摄像机拍到。
   - mutable：可变状态（职业、住处、关系、秘密），3~4 条
   - voice：说话方式。必须有：句长（短/中/长）、口头禅（1~2 个，要土、要具体）、
     语气（一句话）、禁用词（这个角色绝不会说的 2 个词）
   - knowledge：这个角色在第几章知道某件事。格式 {{"某件事": 章号}}

2. 地点表（2~3 个）
   facts 里必须包含至少一条"否定性事实"，例如"没有火车站""不通自来水"。
   否定性事实是后续制造张力的关键，也是最好检测的一致性锚点。

3. 物品表（2~4 件）
   每件物品要有 owner / location / state，以及 history 的起点。
   至少一件物品在故事中被转手或损坏。

4. 世界规则（2~3 条）
   只写"读者会记住并用来判断合理性"的规则。包括一条"本书不会揭晓什么"。

5. 伏笔账本（3~5 条）
   每条：埋在第几章、内容、最晚第几章必须回收、重要度。
   **至少一条必须是"读者会以为是闲笔、其实是关键"的类型。**

6. 分章大纲（3 章，每章 5000 字）
   每章：标题、5~7 个 beat（每个 beat 一句话，必须是事件不是状态）、
   在场人物 id、本章最后一句话（必须是一个动作）。
   第 1 章必须在 500 字内让读者知道主角想要什么。
   第 3 章必须回收第 1 章的至少 2 条伏笔。

【输出格式，严格 JSON】
{{
  "characters": [
    {{"id": "c1", "name": "", "aliases": [], "gender": "", "age": 0, "role": "",
      "immutable": {{}}, "mutable": {{}}, "voice": {{}},
      "knowledge": {{}}, "relationships": {{}}, "appears_in": [1,2,3]}}
  ],
  "places": [{{"id": "p1", "name": "", "aliases": [], "facts": {{}}, "connected": []}}],
  "items": [{{"id": "i1", "name": "", "owner": "", "location": "", "state": "",
             "facts": {{}}, "history": []}}],
  "rules": [{{"id": "r1", "statement": "", "scope": "global", "established_in": 1,
             "exceptions": []}}],
  "foreshadows": [{{"id": "f1", "planted_in": 1, "content": "",
                   "payoff_deadline": 3, "paid_off_in": null,
                   "payoff_note": "", "weight": 1.0}}],
  "chapters": [
    {{"index": 1, "title": "", "words": 5000, "cast": ["c1"],
      "beats": ["", "", "", "", ""], "ends_with": ""}}
  ]
}}
"""


# ==========================================================================
# S3 分章 beat 表（每章写之前，把这一章拆成 4 个场景）
# ==========================================================================
S3_BEATS = """你要为《{title}》第 {chapter} 章写场景表。

【本章大纲】
{chapter_outline}

【在场人物】
{cast_block}

【上一章最后一段（原文，用来衔接）】
{prev_tail}

【未回收伏笔】
{foreshadow_block}

【任务】把本章拆成 4 个场景（scene），每个场景 1200~1300 字。

对每个场景给出：
- goal：这个场景里，主角想干什么（一句话，必须是具体可执行的事）
- obstacle：什么挡住了他（必须是具体的人或物，不能是"内心的挣扎"）
- turn：场景结束时，局面发生了**不可逆**的变化。什么变了？
  如果这个场景删掉，后面还能照常进行，就说明它没用，重写。
- sensory_anchor：这个场景里出现的一个具体物件或声音（用于开篇第一句）
- end_line：场景最后一句。必须是一个动作或一句对话，不允许总结。
- info_gap：这个场景里，谁知道了什么而谁不知道（信息差是小说张力的来源）

【本章节奏要求】
- 4 个场景的节奏不能一样：至少一个场景"慢"（对话为主），一个"快"（动作/事件为主）。
- 至少一个场景里主角失败或付出代价。
- 本章结尾不能解决问题，只能把问题变得更大或更贵。

【输出格式，严格 JSON】
{{
  "chapter": {chapter},
  "scenes": [
    {{"index": 1, "goal": "", "obstacle": "", "turn": "",
      "sensory_anchor": "", "end_line": "", "info_gap": "",
      "pace": "慢/中/快", "cast": ["c1"]}}
  ],
  "chapter_tail": "本章最后一段的第一句（用来锁死结尾走向）"
}}
"""


# ==========================================================================
# S4 正文（分段滚雪球，这是最关键的一步）
# ==========================================================================
S4_DRAFT = """你在写《{title}》第 {chapter} 章第 {scene} 场景的第 {seg} 段。

【写作契约·必须逐条遵守】
{style_contract}

【本场景任务】
目标：{goal}
障碍：{obstacle}
转折：{turn}
感官锚点：{sensory_anchor}
信息差：{info_gap}

【本段要写的内容】
{segment_brief}

【前一段的最后 200 字（原文，必须无缝接上）】
{prev_text}

【硬性要求】
1. 本段 {word_min}~{word_max} 字。少于 {word_min} 字算失败。
2. 第一句必须直接承接上文，不要重述上文。
3. 禁止出现任何禁用词。
4. 段落长度必须有变化：本段至少有一行只有一句话。
5. 本段结尾必须停在具体动作、物件或对话上，禁止总结、禁止抒情。
6. 如果本段是本章最后一段，结尾必须停在大纲指定的那句话上：
   「{end_line}」
7. 不解释人物动机。让读者从动作和对话里看出来。

【自检（写完后在心里过一遍，不要输出自检过程）】
- 有没有出现"他感到""他心想"？
- 有没有连续三个长句？
- 有没有哪一段是在总结？
- 有没有哪个词是禁用词？
- 如果把最后一句删掉，这段是不是更好了？如果是，说明最后一句是废话。

只输出正文，不要标题，不要任何解释。
"""

S4_SEGMENT_BRIEFS = [
    "开场：用一个具体动作或声音切入场景。交代在场的人和位置，但不要交代来龙去脉。"
    "让读者先看见东西，再知道发生了什么。",
    "推进：目标开始受阻。加入一段对话，对话中双方说的和想的不一样。"
    "至少一次答非所问或沉默。",
    "加压：障碍比预想的更麻烦。主角做出一个选择，这个选择有代价。"
    "写清楚代价是什么，但不要写他后悔。",
    "转折落地：局面变了，而且回不去。用动作完成转折，不要用叙述宣布转折。"
    "结尾停在具体动作上。",
]


# ==========================================================================
# S5 去 AI 味重写（这一步单独跑，比在生成时要求更有效）
# ==========================================================================
S5_DEROBOTIZE = """下面是一段小说初稿。它读起来"像 AI 写的"。你的任务是把它改成人写的。

【诊断结果（系统自动测出来的问题，按严重度排序）】
{diagnosis}

【初稿】
{draft}

【改写规则】
1. **只改语言，不改情节。** 事件顺序、人物说的话的意思、场景起止，全部保留。
2. 逐条处理上面的诊断问题。每个问题都要有对应的修改动作。
3. 具体手法：
   - 套话 → 换成具体动作。例："他深吸一口气" → "他把烟摁灭在鞋底"。
   - 情绪直说 → 换成身体反应或动作失误。例："他很难过" → "他把碗放回桌上，放偏了，汤洒出来一点"。
   - 排比 → 只留一句，其余拆成独立短句。
   - 段末升华 → 整句删掉。
   - 长句堆叠 → 拆成短句，中间插一个逗号停顿。
   - 成语 → 换成白话。
   - 逻辑连接词（因此/然而/此外）→ 删掉，靠事件顺序衔接。
4. **句长要制造起伏**：改写后的句子长度标准差必须明显大于原文。
   方法是：插入 3~6 字的极短句，把长句拆开。
5. **不要改得更"文学"。** 目标是像一个具体的人在讲一件具体的事，
   不是像散文。宁拙勿巧。
6. 改完后字数允许 ±10%。

只输出改写后的正文。不要输出修改说明，不要输出对比。
"""


# ==========================================================================
# S6 质检（用模型做"读者视角"检查，配合规则检测）
# ==========================================================================
S6_CRITIQUE = """你是一个苛刻的文学编辑。下面是一篇小说的第 {chapter} 章。

【这一章应该做到的事】
{chapter_outline}

【设定圣经摘要（用于查一致性）】
{bible_block}

【正文】
{text}

【任务】只做诊断，不修改。逐项回答：

1. 一致性：正文里有没有任何地方跟设定圣经冲突？列出原文片段。
   （人物外貌、称谓、地点特征、物品状态、时间、谁知道什么）
2. 无用到场景：有没有哪个段落删掉之后故事完全不受影响？指出来。
3. 假冲突：有没有哪里的冲突是"作者安排的"而不是"人物必然的"？指出来。
4. 人物声音：遮住人名，能不能分辨出是谁在说话？如果不能，说明哪几句混了。
5. 信息差：这一章有没有让读者比某个角色多知道一点？如果没有，这章是平的。
6. 结尾：这一章的结尾有没有把问题变大？还是把问题解决了（这是错的）？
7. 最像 AI 的三句话：原文引用，并说明为什么像。
8. 打分：0~10 分。6 分以下必须重写。

【输出格式，严格 JSON】
{{
  "score": 0,
  "consistency_issues": [{{"quote": "", "problem": ""}}],
  "useless_passages": [{{"quote": "", "reason": ""}}],
  "fake_conflicts": [{{"quote": "", "reason": ""}}],
  "voice_problems": [""],
  "info_gap_present": true,
  "ending_escalates": true,
  "most_ai_sentences": [{{"quote": "", "why": ""}}],
  "rewrite_required": false,
  "top_fix": "如果只能改一处，改哪里"
}}
"""


# ==========================================================================
# 组装函数
# ==========================================================================

def style_contract() -> str:
    return STYLE_CONTRACT_TEMPLATE.format(
        banned_words=BANNED_WORDS.strip().replace("\n", " "),
        banned_structures=BANNED_STRUCTURES.strip(),
    )


def s1(seed) -> str:
    return S1_PREMISE.format(
        book_id=seed.book_id, genre=seed.genre, setting=seed.setting,
        conflict=seed.conflict, pov=seed.pov, time=seed.time,
        ending=seed.ending, protagonist=seed.protagonist, motif=seed.motif,
        register=seed.register, density=seed.density,
    )


def s2(premise: dict, seed) -> str:
    return S2_BIBLE.format(
        title=premise["title"], logline=premise["logline"],
        genre=seed.genre, setting=seed.setting, conflict=seed.conflict,
        pov=seed.pov, time=seed.time, ending=seed.ending,
        protagonist=seed.protagonist, motif=seed.motif,
        anti_tropes="；".join(premise.get("anti_tropes", [])),
    )


def s3(bible, chapter: int, prev_tail: str, cast_block: str,
       foreshadow_block: str) -> str:
    cur = next((c for c in bible.chapters if c.get("index") == chapter), {})
    outline = f"{cur.get('title', '')}\n" + "\n".join(
        f"  · {b}" for b in cur.get("beats", []))
    outline += f"\n  本章必须停在这里：{cur.get('ends_with', '')}"
    return S3_BEATS.format(
        title=bible.title, chapter=chapter, chapter_outline=outline,
        cast_block=cast_block or "（沿用上一章）",
        prev_tail=prev_tail or "（本章是第一章，无前文）",
        foreshadow_block=foreshadow_block or "（无）",
    )


def s4(bible, chapter: int, scene: dict, seg: int, prev_text: str,
       end_line: str, word_min: int, word_max: int) -> str:
    return S4_DRAFT.format(
        title=bible.title, chapter=chapter, scene=scene.get("index", 1),
        seg=seg, style_contract=style_contract(),
        goal=scene.get("goal", ""), obstacle=scene.get("obstacle", ""),
        turn=scene.get("turn", ""), sensory_anchor=scene.get("sensory_anchor", ""),
        info_gap=scene.get("info_gap", ""),
        segment_brief=S4_SEGMENT_BRIEFS[(seg - 1) % len(S4_SEGMENT_BRIEFS)],
        prev_text=prev_text[-400:] if prev_text else "（这是本章开头）",
        end_line=end_line, word_min=word_min, word_max=word_max,
    )


def s5(diagnosis: str, draft: str) -> str:
    return S5_DEROBOTIZE.format(diagnosis=diagnosis, draft=draft)


def s6(bible, chapter: int, text: str, bible_block: str) -> str:
    cur = next((c for c in bible.chapters if c.get("index") == chapter), {})
    outline = f"{cur.get('title', '')}\n" + "\n".join(
        f"  · {b}" for b in cur.get("beats", []))
    return S6_CRITIQUE.format(
        chapter=chapter, chapter_outline=outline,
        bible_block=bible_block, text=text,
    )
