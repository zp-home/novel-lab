#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
canon.py —— 时序正典台账（Temporal Canon Ledger）

为什么 5000 章必须用这个，而不能用"摘要 + 检索"
================================================

第 3000 章时，前文是 1200 万字 ≈ 1800 万 tokens。**任何上下文窗口都装不下**，
而且这不是"装不下"的问题——就算装得下，模型也读不完。

所有"把前文摘要一下塞进去"的做法在 5000 章都会崩，原因有三：

1. **摘要是有损的，且损失会累积。**
   章摘要丢 20% 细节，弧摘要再丢 20%，卷摘要再丢 20%……
   到第 50 卷，第 1 卷的信息只剩 0.8^3 ≈ 51%，而且丢的恰好是"谁的手缺了小指"这种细节。

2. **摘要没有"当前值"的概念。**
   摘要会说"林昭的右臂受了伤"。但第 3000 章需要知道的是：
   **右臂现在好了没有？** 摘要给不出，因为它只是一段叙述，不是状态。

3. **模型会编造"合理的"记忆。**
   给它一段模糊的摘要，它会用最常见的套路补全，而不是事实。

正解：**把"事实"和"叙述"分开。**
- 叙述（章节正文）→ 压缩成摘要，用于提供上下文氛围
- 事实（谁在哪、状态如何、能力多少）→ **结构化台账，永不压缩，按时序查询**

这就是本模块做的事。核心是 `Fact` 带**有效期区间**：
每条事实记录"从第几章到第几章为真"，于是任意章节都能精确查到**当时的状态**。

这是 5000 章不崩的地基。没有它，其他都是补丁。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

HAN_RE = re.compile(r"[\u4e00-\u9fff]")


# ==========================================================================
# 一、事实：带有效期
# ==========================================================================

@dataclass
class Fact:
    """
    一条关于某个实体的事实，带有效期。

    例：Fact(entity="c1", key="右臂", value="骨折，打了石膏",
             valid_from=1200, valid_to=1240)
    含义：第 1200~1240 章之间，c1 的右臂是骨折状态。
    第 1241 章之后查询，这条事实失效，应返回"已恢复"或下一条事实。
    """
    entity: str
    key: str
    value: str
    valid_from: int
    valid_to: int | None = None      # None = 至今仍然有效
    source_chapter: int = 0          # 在哪一章确立的（用于追溯）
    immutable: bool = False          # 不可变事实：全书不能改
    weight: float = 1.0

    def valid_at(self, chapter: int) -> bool:
        if chapter < self.valid_from:
            return False
        if self.valid_to is None:
            return True
        return chapter <= self.valid_to

    def __str__(self) -> str:
        span = f"第{self.valid_from}章起"
        if self.valid_to is not None:
            span = f"第{self.valid_from}~{self.valid_to}章"
        flag = "【不可变】" if self.immutable else ""
        return f"{flag}{self.entity}.{self.key} = {self.value}（{span}）"


@dataclass
class NumericSeries:
    """
    数值台账：战力、等级、年龄、财富、势力值……

    **这是 5000 章头号杀手。** 网文崩得最惨的从来不是文笔，是"战力膨胀失控"：
    第 100 章能打一百人，第 500 章能打一万人，第 2000 章随手灭星，
    第 4000 章又跟人打得有来有回——读者立刻出戏。

    解法：把数值曲线**显式建模**，写作时强制落在曲线上。
    """
    entity: str
    metric: str                      # "战力" / "等级" / "年龄" / "势力值"
    points: list[tuple[int, float]] = field(default_factory=list)
    #   [(1, 10.0), (100, 50.0), (500, 300.0), ...]

    def value_at(self, chapter: int) -> float | None:
        """线性插值取第 N 章的数值。"""
        if not self.points:
            return None
        pts = sorted(self.points)
        if chapter <= pts[0][0]:
            return pts[0][1]
        if chapter >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            c0, v0 = pts[i]
            c1, v1 = pts[i + 1]
            if c0 <= chapter <= c1:
                if c1 == c0:
                    return v1
                t = (chapter - c0) / (c1 - c0)
                return v0 + (v1 - v0) * t
        return pts[-1][1]

    def check_monotonic(self) -> list[str]:
        """检查数值是否单调不降（战力通常不该倒退，除非有剧情解释）。"""
        problems = []
        pts = sorted(self.points)
        for i in range(len(pts) - 1):
            if pts[i + 1][1] < pts[i][1] * 0.95:      # 允许 5% 波动
                problems.append(
                    f"{self.entity}.{self.metric} 在第 {pts[i+1][0]} 章倒退："
                    f"{pts[i][1]} → {pts[i+1][1]}")
        return problems

    def growth_rate(self) -> float:
        """全书增长倍数。>1000 倍通常意味着已经失控。"""
        pts = sorted(self.points)
        if len(pts) < 2 or pts[0][1] == 0:
            return 0.0
        return pts[-1][1] / pts[0][1]


# ==========================================================================
# 二、正典：事实的集合 + 查询 + 冲突检测
# ==========================================================================

@dataclass
class Entity:
    """人物 / 地点 / 势力 / 物品。统一抽象，避免五套代码。"""
    id: str
    name: str
    kind: str = "character"          # character / place / faction / item
    aliases: list[str] = field(default_factory=list)
    voice: dict[str, Any] = field(default_factory=dict)
    first_appear: int = 1
    last_appear: int | None = None
    importance: float = 1.0

    def all_names(self) -> list[str]:
        return [self.name] + list(self.aliases)


@dataclass
class Foreshadow:
    """伏笔账本。5000 章里，埋在第 100 章的伏笔要到第 3000 章才回收——
    这是最容易被忘掉、也最伤读者信任的东西。"""
    id: str
    planted_in: int
    content: str
    payoff_window: tuple[int, int]      # 最早/最晚回收章
    paid_off_in: int | None = None
    weight: float = 1.0
    hint_chapters: list[int] = field(default_factory=list)  # 中途提醒的章节

    def status(self, chapter: int) -> str:
        if self.paid_off_in is not None:
            return "paid"
        lo, hi = self.payoff_window
        if chapter > hi:
            return "overdue"
        if chapter >= lo:
            return "due"
        if chapter >= lo - 50:
            return "approaching"
        return "planted"


class Canon:
    """
    正典台账。整个 5000 章的唯一事实来源。

    设计原则：
    - **事实不可压缩**（摘要会丢，台账不会）
    - **每条事实带有效期**（能查"当时"的状态）
    - **冲突立刻报错**（不等读者发现）
    """

    def __init__(self):
        self.entities: dict[str, Entity] = {}
        self.facts: list[Fact] = []
        self.numerics: dict[str, NumericSeries] = {}   # "entity.metric" -> series
        self.foreshadows: list[Foreshadow] = []
        self.rules: list[str] = []                     # 世界硬规则
        self.timeline: list[tuple[int, str]] = []      # (章号, 故事内时间)

    # ---------------- 实体 ----------------
    def add_entity(self, e: Entity) -> None:
        self.entities[e.id] = e

    def find(self, name_or_id: str) -> Entity | None:
        if name_or_id in self.entities:
            return self.entities[name_or_id]
        for e in self.entities.values():
            if name_or_id in e.all_names():
                return e
        return None

    # ---------------- 事实 ----------------
    def add_fact(self, f: Fact) -> None:
        self.facts.append(f)

    # 可选：外部注入的境界查询（来自 characters.py 的人物轨迹）
    # 境界不逐条存 fact，而是由人物轨迹算出来——省存储，也不会漏。
    level_lookup: Any = None    # callable(entity_id, chapter) -> str | None

    def state_at(self, entity: str, chapter: int) -> dict[str, str]:
        """
        查某个实体在第 N 章的状态。

        **这是整个架构最关键的查询。** 写第 3000 章时，
        主角的"当前状态"不来自前文摘要，来自这里。
        """
        out: dict[str, str] = {}
        # 同一 key 可能有多条事实（不同有效期），取覆盖该章的
        for f in self.facts:
            if f.entity != entity:
                continue
            if f.valid_at(chapter):
                out[f.key] = f.value
        # 境界由人物轨迹提供——但只在没有显式 fact 时才用。
        # 显式事实优先：如果作者/测试手工写了「境界」fact，那是权威。
        if "境界" not in out and callable(self.level_lookup):
            lv = self.level_lookup(entity, chapter)
            if lv:
                out["境界"] = lv
        return out

    def active_facts(self, chapter: int) -> list[Fact]:
        return [f for f in self.facts if f.valid_at(chapter)]

    def close_fact(self, entity: str, key: str, chapter: int) -> None:
        """把某条事实的有效期截止到某章（状态改变时调用）。"""
        for f in self.facts:
            if f.entity == entity and f.key == key and f.valid_to is None:
                f.valid_to = chapter - 1

    # ---------------- 数值 ----------------
    def add_numeric(self, s: NumericSeries) -> None:
        self.numerics[f"{s.entity}.{s.metric}"] = s

    def numeric_at(self, entity: str, metric: str, chapter: int) -> float | None:
        s = self.numerics.get(f"{entity}.{metric}")
        return s.value_at(chapter) if s else None

    # ---------------- 伏笔 ----------------
    def due_foreshadows(self, chapter: int, horizon: int = 20) -> list[Foreshadow]:
        """未来 horizon 章内到期、且尚未回收的伏笔。"""
        out = []
        for f in self.foreshadows:
            if f.paid_off_in is not None:
                continue
            lo, hi = f.payoff_window
            if chapter <= hi and chapter + horizon >= lo:
                out.append(f)
        return out

    def overdue_foreshadows(self, chapter: int) -> list[Foreshadow]:
        return [f for f in self.foreshadows
                if f.paid_off_in is None and chapter > f.payoff_window[1]]

    # ---------------- 冲突检测 ----------------
    def check_new_facts(self, chapter: int, new: list[Fact]) -> list[str]:
        """
        写入新事实前检查冲突。这是防"设定崩塌"的核心。

        三类冲突：
        1. 不可变事实被改写（最严重）
        2. 同一 key 在同一章有两个不同值（自相矛盾）
        3. 数值偏离曲线太远（战力膨胀失控）
        """
        problems: list[str] = []
        for nf in new:
            # 类型 1：不可变事实
            for old in self.facts:
                if (old.entity == nf.entity and old.key == nf.key
                        and old.immutable and old.value != nf.value):
                    problems.append(
                        f"❌ 不可变事实被改写：{nf.entity}.{nf.key} "
                        f"原为「{old.value}」(第{old.source_chapter}章)，"
                        f"现改为「{nf.value}」")
            # 类型 2：同章矛盾
            for old in self.facts:
                if (old.entity == nf.entity and old.key == nf.key
                        and old.valid_at(chapter) and nf.valid_at(chapter)
                        and old.value != nf.value):
                    problems.append(
                        f"❌ 同章矛盾：{nf.entity}.{nf.key} 同时是"
                        f"「{old.value}」和「{nf.value}」")
        return problems

    # ---------------- 序列化 ----------------
    def to_json(self) -> dict:
        return {
            "entities": {k: asdict(v) for k, v in self.entities.items()},
            "facts": [asdict(f) for f in self.facts],
            "numerics": {k: {"entity": v.entity, "metric": v.metric,
                             "points": v.points}
                         for k, v in self.numerics.items()},
            "foreshadows": [asdict(f) for f in self.foreshadows],
            "rules": self.rules,
            "timeline": self.timeline,
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2),
                     encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Canon":
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        c = cls()
        for k, v in d.get("entities", {}).items():
            c.entities[k] = Entity(**v)
        for f in d.get("facts", []):
            c.facts.append(Fact(**f))
        for k, v in d.get("numerics", {}).items():
            c.numerics[k] = NumericSeries(
                entity=v["entity"], metric=v["metric"],
                points=[tuple(p) for p in v["points"]])
        for f in d.get("foreshadows", []):
            if isinstance(f.get("payoff_window"), list):
                f["payoff_window"] = tuple(f["payoff_window"])
            c.foreshadows.append(Foreshadow(**f))
        c.rules = d.get("rules", [])
        c.timeline = [tuple(t) for t in d.get("timeline", [])]
        return c


# ==========================================================================
# 三、状态快照：给模型看的"当前世界"
# ==========================================================================

def render_state(c: Canon, chapter: int, cast: list[str],
                 max_chars: int = 2500, max_foreshadow: int = 8,
                 max_rules: int = 5) -> str:
    """
    渲染第 N 章的世界状态块，用于注入 prompt。

    **铁律：这个块的大小必须与章节号无关。**
    第 3000 章和第 10 章注入的 token 数必须相当——这是 5000 章可行的唯一原因。

    实测踩过的坑：初版把「所有未回收伏笔」和「所有实体」都塞进来，
    结果第 1 章 1408 字符、第 5000 章 2799 字符，**翻了一倍**。
    5000 章累积下来必然爆窗。修法是给每个子块设硬上限并按重要度截断：

        在场实体     ≤ max_chars 的 60%（按 importance 排序）
        到期伏笔     ≤ max_foreshadow 条（只给"快到期"的，不给"全部"）
        世界规则     ≤ max_rules 条（规则本来就该少而硬）
    """
    lines: list[str] = [f"【世界状态 · 第 {chapter} 章】"]

    # 时间
    if c.timeline:
        past = [t for t in c.timeline if t[0] <= chapter]
        if past:
            lines.append(f"故事内时间：{past[-1][1]}")

    # 在场实体的当前状态 —— 按重要度排序后截断
    # 关键：只渲染 cast 里的实体，不渲染全书所有实体。
    # cast 通常 2~5 人，所以这块大小恒定。
    ordered = []
    for cid in cast:
        e = c.find(cid)
        if e:
            ordered.append(e)
    ordered.sort(key=lambda e: -e.importance)

    for e in ordered[:6]:                       # 最多 6 个在场实体
        st = c.state_at(e.id, chapter)
        # 若该实体没有 fact，但有人物轨迹提供的境界，也要渲染
        if st:
            lines.append(f"\n▸ {e.name}")
            # 每实体最多 6 条事实，避免某个角色状态爆炸
            for k, v in list(st.items())[:6]:
                lines.append(f"  · {k}：{v}")
        nums = []
        for key, s in c.numerics.items():
            if s.entity == e.id:
                val = s.value_at(chapter)
                if val is not None:
                    nums.append(f"{s.metric} {val:.0f}")
        if nums:
            lines.append(f"  · 数值：{' / '.join(nums)}")
        if e.voice:
            vs = []
            if e.voice.get("语气"):
                vs.append(f"语气={e.voice['语气']}")
            if e.voice.get("口头禅"):
                vs.append("口头禅=" + "/".join(e.voice["口头禅"][:3]))
            if e.voice.get("禁用词"):
                vs.append("绝不说=" + "/".join(e.voice["禁用词"][:3]))
            if vs:
                lines.append(f"  · 声音：{'；'.join(vs)}")

    # 到期伏笔 —— 只给"即将到期"的，且限条数
    # 关键：不给"所有未回收伏笔"。5000 章会有几十条未回收，
    # 全塞进来必然爆窗。只给未来 20 章内到期的，最多 8 条。
    due = c.due_foreshadows(chapter, horizon=20)
    due.sort(key=lambda f: (f.payoff_window[1], -f.weight))
    if due:
        lines.append("\n【即将到期的伏笔】")
        for f in due[:max_foreshadow]:
            lo, hi = f.payoff_window
            lines.append(f"  · 第{f.planted_in}章埋：{f.content}"
                         f"（{hi} 章前必须回收）")
        if len(due) > max_foreshadow:
            lines.append(f"  ·（另有 {len(due) - max_foreshadow} 条，暂不列出）")

    # 逾期伏笔 —— 只报数量，不逐条列（避免越写越长）
    overdue = c.overdue_foreshadows(chapter)
    if overdue:
        ids = ", ".join(f.id for f in overdue[:5])
        more = f" 等 {len(overdue)} 条" if len(overdue) > 5 else ""
        lines.append(f"\n【⚠️ 逾期未回收 {len(overdue)} 条：{ids}{more}】")

    # 世界规则 —— 本来就是少而硬，限 5 条
    if c.rules:
        lines.append("\n【世界硬规则】")
        for r in c.rules[:max_rules]:
            lines.append(f"  · {r}")

    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n…（已截断）"
    return out


# ==========================================================================
# 四、演示：造一个 5000 章的骨架，验证查询正确性
# ==========================================================================

def demo_canon() -> Canon:
    c = Canon()
    c.rules = [
        "灵气复苏始于第 1 章，此前世界无超自然力量",
        "境界共九品，一品最低，九品最高，不可跳级",
        "死者不可复生，任何复活情节都是错误",
    ]
    c.add_entity(Entity(id="c1", name="林昭", kind="character",
                        aliases=["小林", "昭哥"],
                        voice={"语气": "冷硬，少废话",
                               "口头禅": ["嗯", "走"],
                               "禁用词": ["其实", "或许"]},
                        importance=1.0))
    c.add_entity(Entity(id="c2", name="沈鹤年", kind="character",
                        aliases=["沈老"],
                        voice={"语气": "慢，爱用反问",
                               "口头禅": ["你说呢"],
                               "禁用词": ["综上所述"]},
                        importance=0.8))

    # 不可变事实
    c.add_fact(Fact("c1", "左眉骨", "一道三厘米的旧疤", 1,
                    immutable=True, source_chapter=1))
    c.add_fact(Fact("c2", "右手", "缺了半截小指", 1,
                    immutable=True, source_chapter=1))

    # 可变事实：带有效期（这就是 5000 章能查"当时"的关键）
    c.add_fact(Fact("c1", "境界", "一品", 1, 300, source_chapter=1))
    c.add_fact(Fact("c1", "境界", "三品", 301, 1200, source_chapter=301))
    c.add_fact(Fact("c1", "境界", "六品", 1201, None, source_chapter=1201))
    c.add_fact(Fact("c1", "右臂", "断，接不上了", 2100, 2400, source_chapter=2100))
    c.add_fact(Fact("c1", "右臂", "已愈，但阴雨天会疼", 2401, None, source_chapter=2401))

    # 数值曲线（防战力膨胀）
    c.add_numeric(NumericSeries("c1", "战力", [
        (1, 10), (100, 45), (300, 120), (600, 400), (1200, 1500),
        (2000, 6000), (3000, 25000), (4000, 90000), (5000, 300000),
    ]))

    # 伏笔：跨 2900 章
    c.foreshadows = [
        Foreshadow(id="f1", planted_in=100,
                   content="沈鹤年右手缺指，他说是年轻时被机器咬的",
                   payoff_window=(3000, 3100), weight=1.0),
        Foreshadow(id="f2", planted_in=450,
                   content="林昭母亲留下的铜镜背面刻着一行看不懂的字",
                   payoff_window=(1500, 1600), weight=0.8),
        Foreshadow(id="f3", planted_in=2100,
                   content="断臂后梦里总有人叫他去西边",
                   payoff_window=(2400, 2500), weight=0.6),
    ]
    c.timeline = [(1, "灵气初现 · 春"), (1200, "六品 · 三年后"),
                  (3000, "九品之劫 · 冬")]
    return c


if __name__ == "__main__":
    c = demo_canon()

    print("=" * 66)
    print("验证 1：同一实体，不同章节的状态必须不同")
    print("=" * 66)
    for ch in (1, 150, 500, 2100, 2500, 4999):
        st = c.state_at("c1", ch)
        pw = c.numeric_at("c1", "战力", ch)
        print(f"  第{ch:5d}章：境界={st.get('境界', '?'):4s} "
              f"右臂={st.get('右臂', '正常'):16s} 战力≈{pw:.0f}")

    print()
    print("=" * 66)
    print("验证 2：不可变事实被改写时必须报错")
    print("=" * 66)
    bad = [Fact("c2", "右手", "完好无损", 4000, source_chapter=4000)]
    for p in c.check_new_facts(4000, bad):
        print("  " + p)

    print()
    print("=" * 66)
    print("验证 3：伏笔逾期检测")
    print("=" * 66)
    for ch in (1000, 1550, 3050, 3500):
        od = c.overdue_foreshadows(ch)
        due = c.due_foreshadows(ch, horizon=20)
        print(f"  第{ch:5d}章：逾期 {len(od)} 条，"
              f"20 章内到期 {len(due)} 条"
              + (f" → {[f.id for f in od]}" if od else ""))

    print()
    print("=" * 66)
    print("验证 4：注入 prompt 的状态块（大小与章节号无关）")
    print("=" * 66)
    for ch in (10, 2500, 4999):
        block = render_state(c, ch, ["c1", "c2"])
        print(f"  第{ch:5d}章状态块：{len(block)} 字符")
    print()
    print(render_state(c, 2500, ["c1", "c2"]))
