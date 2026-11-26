#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_flavor.py —— 中文小说「AI 味」量化体检器

设计原则
--------
1. 纯标准库，无第三方依赖，可离线跑。3000 本 × 5000 字 = 1500 万字，
   任何需要模型调用的检测都太贵，所以主力必须是**可确定性计算的统计量**。
2. 不判断"写得好不好"（那需要人），只判断"像不像机器按概率均值写出来的"。
3. 每个指标都给出「人写参考区间」，超出即报警，并给出可执行的修复建议。

用法
----
    python ai_flavor.py FILE [FILE ...] [--json out.json] [--md out.md] [--quiet]

作为库：
    from ai_flavor import analyze, compare
    r = analyze(text, name="book_0001")
    print(r["score"], r["grade"])
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# 一、词表（人工整理，可扩展；词表本身就是这份代码最有价值的部分）
# --------------------------------------------------------------------------

# 1) 中文写作圈公认的「AI 高频套话」——不是禁词，但密度过高立刻露馅
AI_CLICHE = [
    # 副词/语气词型虚词滥用
    "仿佛", "似乎", "不禁", "不由得", "缓缓", "微微", "轻轻", "悄然", "默默",
    "一丝", "一抹", "一缕", "几分", "些许", "隐约", "隐约间", "恍惚",
    # 套路比喻
    "如同", "宛如", "犹如", "恰似", "像是", "仿佛整个世界", "如同一道闪电",
    "如同一记重锤", "如同被雷击中", "仿佛时间静止", "时间仿佛静止",
    # 套路神态
    "瞳孔骤缩", "瞳孔微缩", "嘴角勾起", "嘴角微微上扬", "眼底闪过", "眼中闪过",
    "不易察觉", "若有所思", "意味深长", "深吸一口气", "缓缓开口", "沉默片刻",
    "良久", "叹了口气", "苦笑一声", "自嘲地笑了笑", "眼神复杂", "神色复杂",
    "心中涌起", "心头一震", "心中一惊", "五味杂陈", "百感交集", "如遭雷击",
    "心里五味杂陈", "说不出的滋味", "难以言喻", "无法言说", "不知为何",
    # 万能转折/收束
    "与此同时", "然而", "尽管如此", "总而言之", "换句话说", "值得一提的是",
    "命运的齿轮", "冥冥之中", "这一刻", "就在这一刻", "终于明白", "恍然大悟",
    "似乎明白了什么", "似乎有什么东西改变了", "一切都不一样了",
    # 万能形容词
    "无尽的", "深深的", "淡淡的", "淡淡的忧伤", "复杂的情绪", "莫名的",
    "前所未有的", "难以形容的", "无法抗拒的", "令人窒息的",
]

# 2) 情绪「直说」而非「呈现」——小说写作的第一大忌
EMOTION_TELLING = [
    "感到", "觉得", "心中", "心里", "内心", "情绪", "心情", "心头",
    "愤怒", "悲伤", "喜悦", "恐惧", "惊讶", "紧张", "焦虑", "绝望", "兴奋",
    "松了一口气", "心头一暖", "心如刀绞", "心如死灰", "怒火中烧", "悲从中来",
    "他很难过", "她很开心", "十分震惊", "非常愤怒", "极度恐惧",
    "充满了希望", "满怀期待", "深感不安", "无比坚定", "感到一阵",
]

# 3) 抽象大词——段末升华的重灾区
ABSTRACT_NOUN = [
    "命运", "宿命", "意义", "灵魂", "存在", "自由", "孤独", "救赎", "真相",
    "希望", "绝望", "人性", "尊严", "价值", "本质", "永恒", "虚空", "羁绊",
    "时间", "记忆", "选择", "成长", "责任", "信仰", "理想", "现实", "世界",
    "生命", "死亡", "爱", "恨", "善恶", "正义", "规则", "秩序", "文明",
]

# 4) 具象词（器物 / 身体 / 天气 / 动作）——人味文本的密度显著更高
CONCRETE_NOUN = [
    # 器物
    "碗", "筷子", "锅", "灶", "门", "窗", "墙", "砖", "瓦", "木头", "钉子",
    "绳子", "铁", "铜", "玻璃", "纸", "笔", "灯", "油", "盐", "糖", "米",
    "面", "肉", "酒", "茶", "水", "火", "烟", "灰", "土", "石头", "沙子",
    "鞋", "衣裳", "袖子", "口袋", "帽子", "伞", "车", "船", "刀", "枪",
    "血", "汗", "泪", "牙", "指甲", "头发", "骨头", "皮", "伤口", "疤",
    "床", "被", "枕头", "桌", "椅", "柜", "箱", "锁", "钥匙", "钟",
    # 天气/环境
    "雨", "雪", "风", "雾", "太阳", "月亮", "云", "雷", "冰", "霜",
    "泥", "草", "树叶", "花", "根", "石头", "河", "井", "桥", "路",
    # 动作
    "走", "跑", "坐", "站", "躺", "蹲", "爬", "推", "拉", "拽", "抱",
    "打", "踢", "咬", "抓", "握", "捏", "拍", "敲", "砸", "扔", "捡",
    "吃", "喝", "嚼", "咽", "吐", "喘", "咳", "喊", "叫", "骂", "笑", "哭",
]

# 5) 常见四字格（成语/熟语），用于测「成语堆砌」
FOUR_CHAR_IDIOM = [
    "不可思议", "不知所措", "不由自主", "不寒而栗", "不动声色", "不约而同",
    "不出所料", "不出意外", "毫无疑问", "无动于衷", "无能为力", "无与伦比",
    "小心翼翼", "心照不宣", "心血来潮", "心平气和", "心安理得", "心悦诚服",
    "若有所失", "若有所思", "如愿以偿", "如释重负", "如火如荼", "如出一辙",
    "目瞪口呆", "目不转睛", "目不暇接", "耳熟能详", "耳目一新", "前所未有",
    "翻天覆地", "翻天覆地", "惊心动魄", "惊天动地", "惊魂未定", "迫不得已",
    "迫不及待", "势在必行", "理所当然", "理直气壮", "深思熟虑", "深情款款",
    "不知所措", "毅然决然", "斩钉截铁", "坚定不移", "义无反顾", "毫不犹豫",
    "若有所思", "意味深长", "耐人寻味", "匪夷所思", "莫名其妙", "束手无策",
    "泰然自若", "从容不迫", "镇定自若", "岿然不动", "纹丝不动", "一动不动",
    "一声不吭", "一言不发", "一语不发", "一股脑儿", "一举一动", "一举两得",
    "半信半疑", "将信将疑", "深信不疑", "信誓旦旦", "郑重其事", "煞有介事",
    "莫名其妙", "不可名状", "难以名状", "难以启齿", "哑口无言", "面面相觑",
]

# 6) 逻辑连接词（书面议论腔，小说里过量即出戏）
LOGIC_CONNECTIVE = [
    "因此", "所以", "然而", "但是", "不过", "而且", "并且", "此外", "另外",
    "首先", "其次", "最后", "总之", "综上", "换言之", "也就是说", "由此可见",
    "不仅", "不但", "况且", "何况", "因而", "从而", "进而", "反之",
]

# 7) 套式排比 / 论文腔句式（正则）
# 注意：这里**不能**用「两个逗号 = 排比」这种粗暴判据。
# 实测教训：初版写了 r"[^。！？]{4,20}，[^。！？]{4,20}，[^。！？]{4,20}。"
# 来抓"三段式排比"，结果任何一句正常的中文长句都会被算成排比，
# 人写样本因此被判 62 分「严重 AI 味」。排比的核心是**结构重复**，
# 不是逗号数量——所以下面的模式都要求出现重复的语法骨架。
PARALLEL_PATTERNS = [
    (r"不仅[^。！？]{2,40}(?:而且|还|也|更)", "不仅…而且"),
    (r"既[^。！？]{2,25}又[^。！？]{2,25}", "既…又"),
    (r"不是[^。！？]{2,25}而是[^。！？]{2,25}", "不是…而是"),
    (r"(?:是|像)[^。！？]{2,20}[，,](?:也是|又像)[^。！？]{2,20}", "是…也是"),
    (r"没有[^。！？]{2,20}[，,]也没有[^。！？]{2,20}", "没有…也没有"),
    (r"(?:从|在)[^。！？]{2,15}(?:到|向)[^。！？]{2,15}[，,](?:从|在)[^。！？]{2,15}(?:到|向)", "从…到…从…到"),
    # 真正的三段式：三个分句以相同二字开头（如"他看见…他听见…他知道…"）
    (r"(?:^|[。！？\n])\s*([\u4e00-\u9fff]{2})[^。！？]{2,18}[，,]\s*\1[^。！？]{2,18}[，,]\s*\1",
     "同头三段式"),
    # 三个并列短语后接总结（"…的…，…的…，…的…"）
    (r"[^。！？]{1,10}的[^。！？]{1,6}[，,][^。！？]{1,10}的[^。！？]{1,6}[，,][^。！？]{1,10}的[^。！？]{1,6}",
     "的字结构排比"),
]

# 8) 结尾升华检测用的抽象词（更窄，只留"上价值"的词）
SUBLIMATION_WORDS = [
    "命运", "意义", "人生", "灵魂", "永恒", "宿命", "救赎", "人性", "尊严",
    "价值", "本质", "真相", "自由", "孤独", "成长", "选择", "希望", "未来",
    "世界", "一切", "永远", "从此", "注定", "轮回", "羁绊", "传承",
]

SENT_SPLIT_RE = re.compile(r"[。！？!?…]+")
CLAUSE_SPLIT_RE = re.compile(r"[，,、；;：:]")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
HAN_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
DASH_RE = re.compile(r"——|—")
ELLIPSIS_RE = re.compile(r"……|\.{3,}|…")
QUOTE_RE = re.compile(r"[「『“\"]([^」』”\"]*)[」』”\"]")
PUNCT_RE = re.compile(r"[，。！？；：、…—·「」『』“”‘’（）《》〈〉]")
SENT_START_RE = re.compile(r"(?:^|[。！？!?…\n]+)\s*([\u4e00-\u9fff]{2})")


# --------------------------------------------------------------------------
# 二、文本切分
# --------------------------------------------------------------------------

def split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n|\n", text)
    return [p.strip() for p in parts if p.strip()]


def split_sentences(par: str) -> list[str]:
    """按中文句末标点切句，保留长度信息。"""
    out = []
    buf = []
    for ch in par:
        buf.append(ch)
        if ch in "。！？!?…":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def han_len(s: str) -> int:
    return len(HAN_RE.findall(s))


def count_hits(text: str, words: list[str]) -> tuple[int, dict[str, int]]:
    hits: dict[str, int] = {}
    total = 0
    for w in set(words):
        c = text.count(w)
        if c:
            hits[w] = c
            total += c
    return total, hits


def count_patterns(text: str) -> tuple[int, dict[str, int]]:
    hits: dict[str, int] = {}
    total = 0
    for pat, name in PARALLEL_PATTERNS:
        c = len(re.findall(pat, text))
        if c:
            hits[name] = hits.get(name, 0) + c
            total += c
    return total, hits


def shannon_entropy(counts: list[int]) -> float:
    n = sum(counts)
    if n <= 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in counts if c > 0)


def cv(values: list[float]) -> float:
    """变异系数 = 标准差 / 均值。人写文本的句长 CV 明显更高。"""
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    if m == 0:
        return 0.0
    var = sum((v - m) ** 2 for v in values) / len(values)
    return math.sqrt(var) / m


def bigram_ttr(text: str) -> tuple[float, float]:
    """中文按 2-gram 计算类型/形符比 + 最高频 bigram 集中度。"""
    chars = HAN_RE.findall(text)
    if len(chars) < 4:
        return 0.0, 0.0
    grams = [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    freq: dict[str, int] = {}
    for g in grams:
        freq[g] = freq.get(g, 0) + 1
    ttr = len(freq) / len(grams)
    top = max(freq.values()) / len(grams)
    return ttr, top


# --------------------------------------------------------------------------
# 三、指标定义
# --------------------------------------------------------------------------
# 每个指标: key, label, 计算值, human_ref(人写参考), ai_ref(AI 典型值), weight, advice
# subscore: 0 = 完全像人, 1 = 完全像 AI
# 方向由 human_ref / ai_ref 的相对大小自动决定。

@dataclass
class Metric:
    key: str
    label: str
    value: float
    human_ref: float
    ai_ref: float
    weight: float
    unit: str = ""
    advice: str = ""
    # 该指标需要多少字才有统计意义。低于此长度的文本不参与打分——
    # 否则 294 字的样本会因为"标点种类少"被判成严重 AI 味（实测踩过）。
    min_chars: int = 0
    sub: float = 0.0
    status: str = "ok"          # ok / warn / bad / n/a
    detail: dict = field(default_factory=dict)

    def score(self) -> float:
        h, a = self.human_ref, self.ai_ref
        v = self.value
        if abs(a - h) < 1e-9:
            return 0.0
        t = (v - h) / (a - h)
        t = max(0.0, min(1.0, t))
        return t

    def grade(self) -> str:
        s = self.sub
        if s < 0.35:
            return "ok"
        if s < 0.65:
            return "warn"
        return "bad"


def analyze(text: str, name: str = "") -> dict:
    paras = split_paragraphs(text)
    full = "\n".join(paras)
    n_han = han_len(full)
    if n_han < 200:
        raise ValueError(f"文本太短（{n_han} 汉字），至少 200 字才有统计意义")

    per_1k = n_han / 1000.0

    sents: list[str] = []
    for p in paras:
        sents.extend(split_sentences(p))
    sent_lens = [han_len(s) for s in sents if han_len(s) > 0]
    para_lens = [han_len(p) for p in paras]

    # --- 句法节奏 ---
    sent_cv = cv([float(x) for x in sent_lens])
    short_ratio = sum(1 for x in sent_lens if x <= 8) / max(1, len(sent_lens))
    long_ratio = sum(1 for x in sent_lens if x >= 45) / max(1, len(sent_lens))
    avg_sent = sum(sent_lens) / max(1, len(sent_lens))
    para_cv = cv([float(x) for x in para_lens])

    # --- 词汇 ---
    cliche_n, cliche_hits = count_hits(full, AI_CLICHE)
    emo_n, emo_hits = count_hits(full, EMOTION_TELLING)
    abs_n, abs_hits = count_hits(full, ABSTRACT_NOUN)
    con_n, con_hits = count_hits(full, CONCRETE_NOUN)
    idiom_n, idiom_hits = count_hits(full, FOUR_CHAR_IDIOM)
    conn_n, conn_hits = count_hits(full, LOGIC_CONNECTIVE)
    para_n, para_hits = count_patterns(full)

    cliche_d = cliche_n / per_1k
    emo_d = emo_n / per_1k
    abs_d = abs_n / per_1k
    con_d = con_n / per_1k
    idiom_d = idiom_n / per_1k
    conn_d = conn_n / per_1k
    parallel_d = para_n / per_1k
    con_abs = con_d / max(0.1, abs_d)

    # --- 标点 ---
    dash_d = len(DASH_RE.findall(full)) / per_1k
    ell_d = len(ELLIPSIS_RE.findall(full)) / per_1k
    de_d = full.count("的") / (n_han / 100.0)          # 每百字"的"数

    punct_counts = {}
    for m in PUNCT_RE.findall(full):
        punct_counts[m] = punct_counts.get(m, 0) + 1
    punct_entropy = shannon_entropy(list(punct_counts.values()))

    # --- 对话 ---
    dlg_chars = sum(han_len(m) for m in QUOTE_RE.findall(full))
    dialogue_ratio = dlg_chars / max(1, n_han)
    dlg_sents = []
    for m in QUOTE_RE.findall(full):
        dlg_sents.extend(split_sentences(m))
    dlg_avg = sum(han_len(s) for s in dlg_sents) / max(1, len(dlg_sents)) if dlg_sents else 0.0
    dlg_cv = cv([float(han_len(s)) for s in dlg_sents if han_len(s) > 0])

    # --- 词汇丰富度 ---
    ttr, top_bigram = bigram_ttr(full)

    # --- 4-gram 重复率（对应 M20）---
    # 这是抓"机器复读"最有效的一个指标，几乎不会误伤。
    # 人写 5000 字中文，4-gram 重复率通常在 0.5% 以下；
    # 模板化生成的文本会到 5%~40%。
    chars_all = HAN_RE.findall(full)
    if len(chars_all) >= 8:
        g4 = [chars_all[i] + chars_all[i+1] + chars_all[i+2] + chars_all[i+3]
              for i in range(len(chars_all) - 3)]
        from collections import Counter as _C
        c4 = _C(g4)
        n4 = len(g4)
        g4_dup = sum(v - 1 for v in c4.values() if v > 1) / n4
        g4_top = max(c4.values()) / n4
    else:
        g4_dup, g4_top = 0.0, 0.0

    # --- 句首多样性 ---
    starts = SENT_START_RE.findall(full)
    start_div = len(set(starts)) / max(1, len(starts))

    # --- 结尾升华（末段 & 每段末句） ---
    def is_sublimating(s: str) -> bool:
        return any(w in s for w in SUBLIMATION_WORDS) and han_len(s) <= 40

    para_end_sublim = sum(
        1 for p in paras
        if (ss := split_sentences(p)) and is_sublimating(ss[-1])
    ) / max(1, len(paras))
    tail = "\n".join(paras[-2:]) if len(paras) >= 2 else full
    tail_sublim = 1.0 if any(w in tail for w in SUBLIMATION_WORDS) else 0.0

    # --- 比喻密度 ---
    simile_d = sum(full.count(w) for w in ("像", "如同", "仿佛", "宛如", "犹如", "好似")) / per_1k

    metrics: list[Metric] = [
        # key, label, value, human_ref, ai_ref, weight, unit, advice
        Metric("sent_cv", "句长变异系数", sent_cv, 1.05, 0.45, 3.0, "",
               "句子长度过于整齐。人为制造 3~8 字的极短句，把长句拆成短句+插入语。"),
        Metric("short_ratio", "短句占比(≤8字)", short_ratio, 0.36, 0.09, 2.5, "",
               "缺少短句。每 200 字至少放 2 个 8 字以内的句子，用于砸节奏。"),
        Metric("long_ratio", "长句占比(≥45字)", long_ratio, 0.09, 0.02, 0.8, "",
               "长句偏少不是硬伤，但如果全程无长句，说明作者不敢写复杂句。", min_chars=800),
        Metric("para_cv", "段落长度变异系数", para_cv, 0.72, 0.30, 2.0, "",
               "段落长度太均匀。让某些段落只有一行，某些段落十几行。", min_chars=600),
        Metric("cliche", "AI 套话密度", cliche_d, 2.5, 14.0, 3.5, "处/千字",
               "套话超标。按命中清单逐个替换成具体动作或直接删除。"),
        Metric("emotion", "情绪直说密度", emo_d, 3.0, 15.0, 3.0, "处/千字",
               "情绪在'说'而不是'演'。改为身体反应、动作失误、对话内容。"),
        Metric("abstract", "抽象大词密度", abs_d, 4.0, 13.0, 2.0, "词/千字",
               "抽象词过多。把'命运''意义'换成具体的物和事。"),
        Metric("concrete", "具象词密度", con_d, 26.0, 11.0, 2.0, "词/千字",
               "具象细节不足。加器物、身体、天气、动作的具体名词。"),
        Metric("con_abs", "具象/抽象比", con_abs, 6.0, 0.9, 2.5, "",
               "具象/抽象比过低。这是'空转'最直接的信号。"),
        Metric("idiom", "四字格密度", idiom_d, 2.0, 9.0, 1.5, "个/千字",
               "成语堆砌。每千字控制在 2 个以内，其余改成白话。"),
        Metric("connective", "逻辑连接词密度", conn_d, 3.0, 11.0, 1.5, "词/千字",
               "议论腔过重。删掉'因此''然而''此外'，用事件直接推进。"),
        Metric("parallel", "套式排比密度", parallel_d, 0.6, 4.5, 2.5, "处/千字",
               "排比/对仗过密。保留最有力量的一处，其余打散。"),
        Metric("dash", "破折号密度", dash_d, 1.5, 6.0, 1.0, "个/千字",
               "破折号滥用。多数可换成句号或逗号。"),
        Metric("ellipsis", "省略号密度", ell_d, 1.0, 4.0, 0.8, "个/千字",
               "省略号滥用，显得含糊。"),
        Metric("de", "'的'字密度", de_d, 4.0, 8.0, 1.5, "个/百字",
               "'的'过多=定语堆叠。删掉形容词性修饰，缩短定语。"),
        Metric("ttr", "bigram 类型/形符比", ttr, 0.93, 0.86, 1.5, "",
               "词汇重复度高。同义词替换 + 增加具体名词。", min_chars=1200),
        Metric("start_div", "句首多样性", start_div, 0.88, 0.68, 1.5, "",
               "句首重复。避免连续以'他/她/我/这'开头。", min_chars=1500),
        Metric("para_end_sublim", "段末升华率", para_end_sublim, 0.06, 0.42, 2.5, "",
               "段末爱升华。删掉每段最后那句总结性议论。", min_chars=800),
        Metric("tail_sublim", "结尾升华标记", tail_sublim, 0.0, 1.0, 1.0, "",
               "结尾在'上价值'。用具体画面收尾，不要总结主题。", min_chars=800),
        Metric("simile", "比喻词密度", simile_d, 6.0, 16.0, 1.5, "个/千字",
               "比喻过多且同质。删掉一半，剩下的一半换成非常规喻体。"),
        Metric("dialogue_ratio", "对话占比", dialogue_ratio, 0.35, 0.14, 1.0, "",
               "对话偏少。小说靠对话承载信息差和性格。"),
        Metric("dlg_cv", "对话句长变异", dlg_cv, 0.85, 0.45, 1.0, "",
               "对话长度太均匀，像轮流念台词。", min_chars=400),
        Metric("punct_entropy", "标点多样性(熵)", punct_entropy, 2.3, 1.8, 0.8, "",
               "标点单调。加入分号、顿号、引号内标点变化。", min_chars=1200),
        Metric("g4_dup", "4-gram 重复率", g4_dup, 0.004, 0.06, 3.5, "",
               "复读率高。这是模板化生成最硬的指纹，必须重写而非润色。",
               min_chars=800),
        Metric("g4_top", "最高频 4-gram 占比", g4_top, 0.0004, 0.012, 3.0, "",
               "单个短语反复出现。删掉重复句式，换说法。",
               min_chars=800),
    ]

    for m in metrics:
        if m.min_chars and n_han < m.min_chars:
            # 文本太短，该指标的统计意义不足，直接排除出打分
            m.sub = 0.0
            m.status = "n/a"
        else:
            m.sub = m.score()
            m.status = m.grade()

    scored = [m for m in metrics if m.status != "n/a"]
    total_w = sum(m.weight for m in scored)
    score = (sum(m.sub * m.weight for m in scored) / total_w * 100.0
             if total_w else 0.0)

    # ---- 打分与门禁必须分开 ----
    # 加权平均天然会稀释单项灾难：一段 854 句几乎全是「他没动。」的复读文本，
    # 只有 2 项指标爆表，其余"正常"，加权后只有 20 分。
    # 但也不能简单给分数设下限——实测发现那会让一个权重 1.0 的噪声指标
    # （对话占比）把一段正常文本判成 62 分。
    #
    # 正确做法：score 老实做加权平均（用于排序/对比），
    # 另出一组 fatal 布尔标记（用于流水线门禁）。
    # 只有**高权重**且**严重超标**的指标才有资格一票否决。
    FATAL_WEIGHT = 2.0
    fatal = [
        {"key": m.key, "label": m.label, "value": round(m.value, 3),
         "human_ref": m.human_ref, "ai_ref": m.ai_ref,
         "severity": round(m.sub, 3), "advice": m.advice}
        for m in scored
        if m.sub >= 0.90 and m.weight >= FATAL_WEIGHT
    ]

    if score < 25:
        grade = "A 人味充足"
    elif score < 40:
        grade = "B 轻度 AI 味"
    elif score < 55:
        grade = "C 明显 AI 味"
    elif score < 70:
        grade = "D 严重 AI 味"
    else:
        grade = "F 纯机器感"

    # 有致命项时，等级至少要压到 C，避免"平均分好看但单项已崩"
    if fatal and grade in ("A 人味充足", "B 轻度 AI 味"):
        grade = "C 明显 AI 味（单项致命）"

    worst = max(scored, key=lambda m: m.sub) if scored else None

    # 归因：把权重*偏差最大的几项挑出来
    ranked = sorted(
        (m for m in scored if m.sub > 0.5),
        key=lambda m: m.sub * m.weight,
        reverse=True,
    )

    return {
        "name": name,
        "chars": n_han,
        "paragraphs": len(paras),
        "sentences": len(sent_lens),
        "score": round(score, 2),
        "fatal": fatal,
        "passed": len(fatal) == 0,
        "worst_metric": ({"key": worst.key, "label": worst.label,
                          "value": round(worst.value, 3),
                          "severity": round(worst.sub, 3)}
                         if worst else None),
        "grade": grade,
        "metrics": [asdict(m) for m in metrics],
        "top_issues": [
            {"key": m.key, "label": m.label, "value": round(m.value, 3),
             "human_ref": m.human_ref, "ai_ref": m.ai_ref,
             "severity": round(m.sub, 3), "advice": m.advice}
            for m in ranked[:8]
        ],
        "hits": {
            "cliche": dict(sorted(cliche_hits.items(), key=lambda kv: -kv[1])[:15]),
            "emotion": dict(sorted(emo_hits.items(), key=lambda kv: -kv[1])[:15]),
            "abstract": dict(sorted(abs_hits.items(), key=lambda kv: -kv[1])[:12]),
            "concrete": dict(sorted(con_hits.items(), key=lambda kv: -kv[1])[:12]),
            "idiom": dict(sorted(idiom_hits.items(), key=lambda kv: -kv[1])[:12]),
            "connective": dict(sorted(conn_hits.items(), key=lambda kv: -kv[1])[:12]),
            "parallel": para_hits,
        },
    }


def compare(a: dict, b: dict) -> str:
    """两个文本的指标对照表（markdown）。"""
    rows = ["| 指标 | " + a["name"] + " | " + b["name"] + " | 人写参考 |",
            "|---|---|---|---|"]
    bm = {m["key"]: m for m in b["metrics"]}
    for m in a["metrics"]:
        o = bm[m["key"]]
        rows.append(
            f"| {m['label']} | {m['value']:.2f} | {o['value']:.2f} | {m['human_ref']} |"
        )
    return "\n".join(rows)


# --------------------------------------------------------------------------
# 四、CLI
# --------------------------------------------------------------------------

def render_md(reports: list[dict]) -> str:
    out = ["# AI 味体检报告", ""]
    out.append("评分含义：0 = 完全人写，100 = 完全机器。")
    out.append("")
    out.append("| 文本 | 字数 | 句数 | 得分 | 等级 |")
    out.append("|---|---|---|---|---|")
    for r in reports:
        out.append(f"| {r['name']} | {r['chars']} | {r['sentences']} | "
                   f"{r['score']} | {r['grade']} |")
    out.append("")
    for r in reports:
        out.append(f"## {r['name']} —— {r['score']} 分 / {r['grade']}")
        out.append("")
        out.append("| 指标 | 实测 | 人写参考 | AI 典型 | 严重度 |")
        out.append("|---|---|---|---|---|")
        for m in r["metrics"]:
            flag = {"ok": " ", "warn": "!", "bad": "!!", "n/a": "–"}[m["status"]]
            out.append(f"| {flag} {m['label']} | {m['value']:.2f}{m['unit']} | "
                       f"{m['human_ref']} | {m['ai_ref']} | {m['sub']:.2f} |")
        out.append("")
        if r["top_issues"]:
            out.append("**主要问题与修法**")
            out.append("")
            for i, it in enumerate(r["top_issues"], 1):
                out.append(f"{i}. **{it['label']}** = {it['value']}"
                           f"（人写 {it['human_ref']} / AI 典型 {it['ai_ref']}，"
                           f"严重度 {it['severity']:.2f}）")
                out.append(f"   - {it['advice']}")
            out.append("")
        ch = r["hits"]
        if ch["cliche"]:
            top = "、".join(f"{k}×{v}" for k, v in list(ch["cliche"].items())[:10])
            out.append(f"**套话命中**：{top}")
            out.append("")
        if ch["parallel"]:
            out.append("**套式句式命中**：" +
                       "、".join(f"{k}×{v}" for k, v in ch["parallel"].items()))
            out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="中文小说 AI 味量化体检")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    reports = []
    for f in args.files:
        p = Path(f)
        text = p.read_text(encoding="utf-8-sig")
        r = analyze(text, name=p.stem)
        reports.append(r)
        if not args.quiet:
            print(f"{p.stem}: {r['score']} 分  {r['grade']}  "
                  f"({r['chars']} 字 / {r['sentences']} 句)")
            for it in r["top_issues"][:5]:
                print(f"    ! {it['label']}={it['value']}  -> {it['advice']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render_md(reports), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
