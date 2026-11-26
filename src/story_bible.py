#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
story_bible.py —— 长篇连续性引擎（"设定圣经" + 硬约束校验）

为什么需要它
------------
模型没有记忆。它每次生成只看到你塞进 context 的那几千字。
一本 5000 字的短篇可以靠"把全文塞进去"糊过去；但只要有第二篇、第三篇，
或者一本书写到第 20 章，光靠 prompt 就必然漂移：
    第 3 章写"她左眼有一道疤"，第 17 章写"她那双完好的眼睛"。
    第 5 章说"这镇子没有火车"，第 30 章主角坐火车走了。

解法不是"让模型更聪明"，而是**把记忆外置成结构化状态，每章生成前注入、
生成后回写、回写时做冲突检测**。这就是 Story Bible / Canon Ledger 模式，
也是 YILING0013/AI_NovelGenerator、novel-orchestrator 这类框架的核心。

本模块提供
----------
1. Bible 数据结构：人物 / 地点 / 物品 / 规则 / 时间线 / 伏笔账本
2. 硬约束校验器：把正文跟 Bible 对撞，找出矛盾
3. 软漂移检测：人物说话风格、称谓变化
4. 伏笔生命周期管理：埋设 -> 到期 -> 回收，未回收的自动报警
5. 存储格式：JSON（人可读、可 diff、可 git 管理）

用法
----
    from story_bible import Bible, check_chapter
    b = Bible.load("books/b0001/bible.json")
    issues = check_chapter(b, chapter_text, chapter_index=7)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

HAN_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_SPLIT_RE = re.compile(r"[。！？!?…]+")


# ==========================================================================
# 数据结构
# ==========================================================================

@dataclass
class Character:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)   # 别名/称呼，用于指代消解
    gender: str = ""                                    # 男/女/其他
    age: int | None = None
    role: str = ""                                      # 主角/对手/配角/工具人
    # 不可变事实：一旦确立就不能被后续章节改写，除非显式"改写事件"
    immutable: dict[str, str] = field(default_factory=dict)
    #   {"左眼": "有一道从眉骨到颧骨的疤", "右手": "缺了小指"}
    mutable: dict[str, str] = field(default_factory=dict)
    #   {"职业": "修车工", "所在地": "清河镇"} —— 可变，但变更必须记录
    voice: dict[str, Any] = field(default_factory=dict)
    #   {"句长": "短", "口头禅": ["行吧", "知道了"], "禁用词": ["似乎", "仿佛"],
    #    "语气": "少用形容词，多用反问"}
    knowledge: dict[str, int] = field(default_factory=dict)
    #   {"自己母亲已死": 1, "厂子倒闭": 3}  —— 第几章知道这件事
    relationships: dict[str, str] = field(default_factory=dict)
    #   {"二叔": "父亲的弟弟，欠他家三万块钱"}
    appears_in: list[int] = field(default_factory=list)

    def all_names(self) -> list[str]:
        return [self.name] + list(self.aliases)


@dataclass
class Place:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    #   {"有无火车": "无", "到镇上距离": "八里", "标志物": "一座废砖窑"}
    connected: list[str] = field(default_factory=list)   # 可直达的其他地点 id


@dataclass
class Item:
    id: str
    name: str
    owner: str = ""          # character id，空=无主
    location: str = ""       # place id
    state: str = "完好"
    facts: dict[str, str] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    #   [{"chapter": 3, "owner": "c1", "state": "完好"},
    #    {"chapter": 9, "owner": "c2", "state": "裂了一道口子"}]


@dataclass
class Rule:
    """世界规则 / 类型设定。玄幻、悬疑、现实向都需要。"""
    id: str
    statement: str            # "这个世界没有电"
    scope: str = "global"     # global / place:<id> / character:<id>
    established_in: int = 0
    exceptions: list[str] = field(default_factory=list)


@dataclass
class Foreshadow:
    """伏笔账本。这是长篇最容易被 AI 忘掉的东西。"""
    id: str
    planted_in: int           # 埋在第几章
    content: str              # "二叔提到三年前那块地，但没说是谁推平的"
    payoff_deadline: int      # 最晚第几章必须回收
    paid_off_in: int | None = None
    payoff_note: str = ""
    weight: float = 1.0       # 重要度，主线的伏笔 weight 高

    @property
    def status(self) -> str:
        if self.paid_off_in is not None:
            return "已回收"
        return "逾期未回收" if self.paid_off_in is None else "未回收"

    def check(self, current_chapter: int) -> str:
        if self.paid_off_in is not None:
            return "ok"
        if current_chapter > self.payoff_deadline:
            return "overdue"
        if current_chapter >= self.payoff_deadline - 1:
            return "due_soon"
        return "ok"


@dataclass
class TimelineEntry:
    chapter: int
    story_time: str           # "第三天傍晚" / "1998年冬"
    duration: str = ""        # "一小时" / "三个月"
    location: str = ""


@dataclass
class Bible:
    book_id: str = ""
    title: str = ""
    genre: str = ""
    logline: str = ""
    target_words: int = 5000
    # 全局风格契约：给模型看的硬性写作约束
    style_contract: dict[str, Any] = field(default_factory=dict)
    characters: list[Character] = field(default_factory=list)
    places: list[Place] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    foreshadows: list[Foreshadow] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)
    #   [{"index": 1, "title": "...", "summary": "...", "words": 5000,
    #     "beats": ["..."], "ends_with": "..."}]

    # ---------------- 序列化 ----------------
    def to_json(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(self.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Bible":
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cls(
            book_id=d.get("book_id", ""),
            title=d.get("title", ""),
            genre=d.get("genre", ""),
            logline=d.get("logline", ""),
            target_words=d.get("target_words", 5000),
            style_contract=d.get("style_contract", {}),
            characters=[Character(**c) for c in d.get("characters", [])],
            places=[Place(**p) for p in d.get("places", [])],
            items=[Item(**i) for i in d.get("items", [])],
            rules=[Rule(**r) for r in d.get("rules", [])],
            foreshadows=[Foreshadow(**f) for f in d.get("foreshadows", [])],
            timeline=[TimelineEntry(**t) for t in d.get("timeline", [])],
            chapters=d.get("chapters", []),
        )

    # ---------------- 查询 ----------------
    def char(self, cid_or_name: str) -> Character | None:
        for c in self.characters:
            if c.id == cid_or_name or c.name == cid_or_name:
                return c
            if cid_or_name in c.aliases:
                return c
        return None

    def place(self, pid_or_name: str) -> Place | None:
        for p in self.places:
            if p.id == pid_or_name or p.name == pid_or_name or pid_or_name in p.aliases:
                return p
        return None

    def context_block(self, chapter_index: int, max_chars: int = 3000) -> str:
        """
        为第 N 章生成"必须注入 prompt"的状态块。
        这是整套方案的关键：模型每次只看这个块，而不是全部前文。
        """
        lines: list[str] = []
        lines.append(f"【作品】{self.title}｜类型：{self.genre}")
        lines.append(f"【一句话】{self.logline}")

        if self.style_contract:
            lines.append("\n【写作契约（硬约束）】")
            for k, v in self.style_contract.items():
                lines.append(f"- {k}：{v}")

        # 当前章的大纲
        cur = next((c for c in self.chapters if c.get("index") == chapter_index), None)
        if cur:
            lines.append(f"\n【本章大纲】{cur.get('title', '')}")
            for b in cur.get("beats", []):
                lines.append(f"  · {b}")
            if cur.get("ends_with"):
                lines.append(f"  · 本章必须停在这里：{cur['ends_with']}")

        # 上一章结尾原文（最有效的衔接手段，比摘要强得多）
        if chapter_index > 1:
            prev = next((c for c in self.chapters
                         if c.get("index") == chapter_index - 1), None)
            if prev:
                lines.append(f"\n【上一章摘要】{prev.get('summary', '')}")
                if prev.get("tail"):
                    lines.append(f"【上一章最后一段（原文）】\n{prev['tail']}")

        # 在场人物的当前状态
        cast = cur.get("cast", []) if cur else []
        if cast:
            lines.append("\n【在场人物·当前状态】")
            for cid in cast:
                c = self.char(cid)
                if not c:
                    continue
                bits = []
                if c.immutable:
                    bits.append("不可变：" + "；".join(
                        f"{k}={v}" for k, v in c.immutable.items()))
                if c.mutable:
                    bits.append("现状：" + "；".join(
                        f"{k}={v}" for k, v in c.mutable.items()))
                if c.voice:
                    v = c.voice
                    vs = []
                    if v.get("语气"):
                        vs.append(f"说话语气={v['语气']}")
                    if v.get("口头禅"):
                        vs.append("口头禅=" + "/".join(v["口头禅"]))
                    if v.get("句长"):
                        vs.append(f"句子偏{v['句长']}")
                    if vs:
                        bits.append("声音：" + "；".join(vs))
                known = [k for k, v in c.knowledge.items() if v < chapter_index]
                if known:
                    bits.append("已知：" + "、".join(known))
                lines.append(f"- {c.name}（{c.role}）：" + "｜".join(bits))

        # 未回收伏笔
        pending = [f for f in self.foreshadows if f.paid_off_in is None]
        if pending:
            lines.append("\n【未回收伏笔（不可遗忘）】")
            for f in pending:
                flag = "⚠️本章必须回收" if f.check(chapter_index) != "ok" else ""
                lines.append(
                    f"- 第{f.planted_in}章埋：{f.content}"
                    f"（最晚第{f.payoff_deadline}章回收）{flag}")

        # 世界规则
        if self.rules:
            lines.append("\n【世界规则（不可违反）】")
            for r in self.rules:
                lines.append(f"- {r.statement}")

        out = "\n".join(lines)
        if len(out) > max_chars:
            out = out[:max_chars] + "\n…（已截断）"
        return out


# ==========================================================================
# 校验器
# ==========================================================================

@dataclass
class Issue:
    level: str      # error / warning / info
    code: str
    message: str
    evidence: str = ""
    fix: str = ""

    def __str__(self) -> str:
        icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(self.level, "·")
        s = f"{icon} [{self.code}] {self.message}"
        if self.evidence:
            s += f"\n     证据：{self.evidence}"
        if self.fix:
            s += f"\n     修法：{self.fix}"
        return s


def _sentence_containing(text: str, pos: int, width: int = 40) -> str:
    start = max(0, pos - width)
    end = min(len(text), pos + width)
    return text[start:end].replace("\n", " ")


def check_character_immutable(b: Bible, text: str) -> list[Issue]:
    """不可变事实被改写 = 最严重的设定崩塌。"""
    issues: list[Issue] = []
    NEG_PREFIX = ["没有", "没了", "完好", "正常", "并无", "不见", "全无", "不再有"]
    for c in b.characters:
        for part, fact in c.immutable.items():
            # 正文里出现了这个部位 + 一个否定词
            for m in re.finditer(re.escape(part), text):
                seg = _sentence_containing(text, m.start(), 30)
                if any(neg in seg for neg in NEG_PREFIX):
                    # 排除"回忆/假设"语境的粗判
                    if any(w in seg for w in ("如果", "假如", "梦", "想象", "以前", "曾经")):
                        continue
                    issues.append(Issue(
                        level="error",
                        code="IMMUTABLE_BROKEN",
                        message=f"{c.name} 的不可变事实「{part}={fact}」被改写",
                        evidence=seg.strip(),
                        fix=f"要么改成符合「{fact}」的描写，要么在 Bible 里走"
                            f"「改写事件」流程（需要正文里有明确的修复情节）",
                    ))
    return issues


def check_place_facts(b: Bible, text: str) -> list[Issue]:
    issues: list[Issue] = []
    for p in b.places:
        if p.name not in text:
            continue
        for k, v in p.facts.items():
            # 例如 facts={"有无火车": "无"}，正文出现"火车"+地点名同段 => 可疑
            if v in ("无", "没有", "不存在"):
                subject = k.replace("有无", "").replace("是否有", "")
                if not subject:
                    continue
                for m in re.finditer(re.escape(subject), text):
                    seg = _sentence_containing(text, m.start(), 40)
                    if p.name in seg or any(a in seg for a in p.aliases):
                        issues.append(Issue(
                            level="error",
                            code="PLACE_RULE_BROKEN",
                            message=f"{p.name} 设定为「{k}={v}」，但正文出现了「{subject}」",
                            evidence=seg.strip(),
                            fix="删掉该描写，或先写一段设定变更的过渡",
                        ))
    return issues


def check_foreshadow(b: Bible, chapter_index: int) -> list[Issue]:
    issues: list[Issue] = []
    for f in b.foreshadows:
        st = f.check(chapter_index)
        if st == "overdue":
            issues.append(Issue(
                level="error", code="FORESHADOW_OVERDUE",
                message=f"伏笔「{f.content[:24]}…」已逾期"
                        f"（第{f.planted_in}章埋，应第{f.payoff_deadline}章前回收）",
                fix="本章立即回收，或显式延长 deadline 并说明理由"))
        elif st == "due_soon":
            issues.append(Issue(
                level="warning", code="FORESHADOW_DUE",
                message=f"伏笔「{f.content[:24]}…」下一章到期",
                fix="本章或下章安排回收场景"))
    return issues


def check_voice(b: Bible, text: str, cast: list[str]) -> list[Issue]:
    """
    人物声音漂移：从引号里抽出对话，按说话人归属（粗略：对话前后出现的人名），
    检查句长、口头禅、禁用词。
    """
    issues: list[Issue] = []
    quotes = re.findall(r"[「『“\"]([^」』”\"]{2,200})[」』”\"]", text)
    if not quotes:
        return issues

    for cid in cast:
        c = b.char(cid)
        if not c or not c.voice:
            continue
        if not any(n in text for n in c.all_names()):
            continue
        banned = c.voice.get("禁用词", [])
        tic = c.voice.get("口头禅", [])
        for q in quotes:
            for w in banned:
                if w in q:
                    issues.append(Issue(
                        level="warning", code="VOICE_BANNED_WORD",
                        message=f"{c.name} 的对话出现其禁用词「{w}」",
                        evidence=q.strip()[:60],
                        fix="换成该角色惯用的表达"))
        # 口头禅应当出现至少一次（如果本章有该角色的戏）
        if tic and not any(t in text for t in tic):
            issues.append(Issue(
                level="info", code="VOICE_TIC_MISSING",
                message=f"{c.name} 有口头禅但本章一次没用：{'/'.join(tic)}",
                fix="加一句带口头禅的对话，强化辨识度"))
    return issues


def check_timeline(b: Bible, text: str, chapter_index: int) -> list[Issue]:
    """时间线漂移：上一章说"第三天"，这一章不能回到"第二天"。"""
    issues: list[Issue] = []
    TIME_WORDS = ["第一天", "第二天", "第三天", "第四天", "第五天",
                  "第二天早上", "当晚", "次日", "翌日", "一周后", "一个月后",
                  "半年后", "三年后", "十年前", "小时候"]
    found = [w for w in TIME_WORDS if w in text]
    if not found:
        return issues
    prev = [t for t in b.timeline if t.chapter < chapter_index]
    if not prev:
        return issues
    last = max(prev, key=lambda t: t.chapter)
    for w in found:
        if w == "十年前" or w == "小时候":
            continue    # 闪回，不算漂移
        if last.story_time and w in ("第一天", "第二天") and \
                last.story_time not in ("第一天", "第二天"):
            issues.append(Issue(
                level="warning", code="TIMELINE_DRIFT",
                message=f"第{last.chapter}章时间已推进到「{last.story_time}」，"
                        f"本章出现「{w}」",
                evidence=text[:0] or "",
                fix="改为「几天后」等相对表述，或确认这是闪回并写明"))
    return issues


def check_names(b: Bible, text: str) -> list[Issue]:
    """称谓/错字漂移：Bible 里的名字在正文里出现了近似但不同的写法。"""
    issues: list[Issue] = []
    for c in b.characters:
        for n in c.all_names():
            # 2 字名做编辑距离会误伤（"陈默" vs "陈建" 都是人名），
            # 所以只对 3 字及以上的名字做近似检测
            if len(n) < 3:
                continue
            # 同姓不同名的近似串（编辑距离 1）——粗判：把最后一个字换掉
            pat = re.escape(n[:-1]) + "."
            for m in re.finditer(pat, text):
                cand = m.group(0)
                if cand == n or cand in c.all_names():
                    continue
                if any(cand in o.all_names() for o in b.characters if o.id != c.id):
                    continue
                # 只报那些"看起来像人名"的（前后不是常用词）
                if cand[-1] in "的了是在和与就都也还":
                    continue
                issues.append(Issue(
                    level="warning", code="NAME_DRIFT",
                    message=f"疑似把「{n}」写成了「{cand}」",
                    evidence=_sentence_containing(text, m.start(), 30).strip(),
                    fix=f"统一为「{n}」"))
    return issues


def check_chapter(b: Bible, text: str, chapter_index: int,
                  cast: list[str] | None = None) -> list[Issue]:
    """一次跑全部校验。返回按严重度排序的问题列表。"""
    if cast is None:
        cur = next((c for c in b.chapters if c.get("index") == chapter_index), None)
        cast = cur.get("cast", []) if cur else [c.id for c in b.characters]
    issues: list[Issue] = []
    issues += check_character_immutable(b, text)
    issues += check_place_facts(b, text)
    issues += check_foreshadow(b, chapter_index)
    issues += check_voice(b, text, cast)
    issues += check_timeline(b, text, chapter_index)
    issues += check_names(b, text)
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i.level, 3))
    return issues


def summarize(issues: list[Issue]) -> str:
    if not issues:
        return "✅ 无连续性问题"
    n_err = sum(1 for i in issues if i.level == "error")
    n_warn = sum(1 for i in issues if i.level == "warning")
    out = [f"共 {len(issues)} 个问题（error {n_err} / warning {n_warn}）", ""]
    out += [str(i) for i in issues]
    return "\n".join(out)


# ==========================================================================
# 示例：构造一个可跑的 Bible（演示用）
# ==========================================================================

def demo_bible() -> Bible:
    return Bible(
        book_id="b0001",
        title="清河镇的最后一班车",
        genre="现实向 / 家庭",
        logline="一个倒闭工厂的技术员回村给母亲上坟，发现三年前推平他家地的厂子，是二叔签的字。",
        target_words=5000,
        style_contract={
            "视角": "第三人称限知，全程只跟男主角，不写别人心里想什么",
            "句子": "平均 12-18 字，允许 3-6 字短句；禁止连续三个长句",
            "描写": "只写可被摄像机拍到的：动作、器物、声音、气味。禁止直接写情绪词",
            "对话": "口语，可打断、可答非所问、可沉默。禁止解释性台词",
            "禁用": "仿佛/似乎/不禁/缓缓/微微/一丝/命运/救赎/这一刻/心中涌起",
            "结尾": "必须停在一个具体动作上，不解释意义",
        },
        characters=[
            Character(
                id="c1", name="陈默", gender="男", age=38, role="主角",
                immutable={"左眉骨": "有一道三厘米的旧疤"},
                mutable={"职业": "原机床厂技术员（已下岗）", "所在地": "清河镇"},
                voice={"句长": "短", "口头禅": ["嗯"], "语气": "少形容词，多用短句反问",
                       "禁用词": ["仿佛", "似乎"]},
                knowledge={"母亲已去世": 1, "厂子倒闭": 2},
                relationships={"c2": "二叔，父亲的弟弟"},
            ),
            Character(
                id="c2", name="陈建国", aliases=["二叔"], gender="男", age=61,
                role="对手/亲属",
                immutable={"右手": "缺了半截小指"},
                mutable={"身份": "村会计", "秘密": "三年前在征地协议上签了字"},
                voice={"句长": "短", "口头禅": ["行吧"], "语气": "回避，答非所问"},
            ),
        ],
        places=[
            Place(id="p1", name="清河镇",
                  facts={"有无火车站": "无", "到县城": "四十里"},
                  connected=["p2"]),
            Place(id="p2", name="废砖窑", facts={"状态": "已废弃"},
                  connected=["p1"]),
        ],
        items=[
            Item(id="i1", name="征地协议", owner="", location="p1",
                 facts={"签名人": "陈建国", "日期": "三年前"}),
        ],
        rules=[
            Rule(id="r1", statement="清河镇没有火车站，出镇只能坐中巴或骑摩托",
                 established_in=1),
            Rule(id="r2", statement="母亲的死因在全文不揭晓，只能通过细节暗示",
                 established_in=1),
        ],
        foreshadows=[
            Foreshadow(id="f1", planted_in=1,
                       content="二叔说「那块地，说要建厂，三年了」，但没说谁签的字",
                       payoff_deadline=4, weight=1.0),
            Foreshadow(id="f2", planted_in=1,
                       content="二叔右手缺半截小指，他解释说是年轻时被机器咬的",
                       payoff_deadline=3, weight=0.5),
        ],
        timeline=[
            TimelineEntry(chapter=1, story_time="第一天傍晚", duration="两小时",
                          location="p1"),
        ],
        chapters=[
            {"index": 1, "title": "回村", "words": 5000,
             "cast": ["c1", "c2"],
             "beats": ["陈默开车回村，停在村口没熄火",
                       "二叔迎上来，说坟上的草割了",
                       "提到厂子关了，二叔重复了一遍",
                       "远处被推平的地和锈钢筋",
                       "陈默熄了火——决定留下来"],
             "ends_with": "他熄了火。"},
            {"index": 2, "title": "坟", "words": 5000, "cast": ["c1", "c2"],
             "beats": ["上坟", "发现坟前有新烧的纸，不是二叔烧的",
                       "回村路上遇到老工友", "工友说漏嘴：征地签字的人姓陈"],
             "ends_with": "工友把烟头摁在鞋底上，说：「你问你二叔去。」"},
        ],
    )


if __name__ == "__main__":
    b = demo_bible()
    here = Path(__file__).resolve().parent.parent
    b.save(here / "out" / "demo_bible.json")
    print("已写出", here / "out" / "demo_bible.json")
    print("\n===== 第 1 章应注入的上下文块 =====")
    print(b.context_block(1))
    print("\n===== 故意写错的一章，看校验能不能抓到 =====")
    bad = """陈默站在村口，仿佛时间静止了一般。
　　他看见二叔走过来，二叔的右手完好无损，接过化肥袋子。
　　"回来了？"二叔问。
　　陈默心中涌起一阵复杂的情绪，他感到难以言喻的酸楚。
　　他说："我明天坐火车回城里。"
　　远处是清河镇，镇子边上就是火车站。
　　这一刻，他终于明白了命运的意义。"""
    issues = check_chapter(b, bad, 1)
    print(summarize(issues))
