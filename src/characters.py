#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
characters.py —— 人物体系（第 1 步，依赖世界观）

为什么人物必须"半硬"
==================

世界观是硬编码的（第 0 步），人物是**半硬**的：

- **境界轨迹必须是结构化的**（不能靠模型每次编）。否则第 3000 章
  沈鹤年突然从元婴变成化神，读者立刻发现。
- **声音必须是结构化的**。5000 章里如果所有角色说话一个味，
  读者分不清谁在说话——这是长篇最隐蔽的崩坏。
- **人物弧光可以交给模型**（大纲层），但弧光的**锚点**必须定死。

所以本模块产出的是 `cast.json`：每个角色的境界里程碑、灵根、声纹、
关系。模型只能引用，不能发明。

核心难点：境界轨迹怎么定
====================

主角的境界轨迹 = 世界观的 108 阶曲线（完全绑定）。
配角的轨迹必须满足三条叙事约束：

1. **师父必须比主角强**（至少强 2 个大境界），否则教不了。
2. **反派登场时必须比主角强**，否则冲突不成立。
3. **但差距不能大到绝望**（不超过 3 个大境界），否则读者觉得没法打。

这三条是网文的硬规律。本模块把它们写成可校验的规则。

另一个关键设计：**主角不是最强的**
============================

5000 章里，如果主角从第 100 章就无敌，后面 4900 章没有张力。
所以设计上保证：

    第 1~4000 章：始终有比主角强的敌人
    第 4000 章后：主角追平，进入"打不得"而非"打不过"的阶段

`power_ranking_at()` 会检查这个分布。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import worldbuild as WB


# ==========================================================================
# 一、数据结构
# ==========================================================================

@dataclass
class Milestone:
    """境界里程碑：从第 chapter 章起，达到 level_index 这一阶。"""
    chapter: int
    level_index: int
    note: str = ""


@dataclass
class Character:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    role: str = "配角"            # 主角/师父/道侣/宿敌/最终反派/亲人/引路人
    gender: str = ""
    spirit_root: str = ""          # 灵根
    origin: str = ""               # 出身
    first_appear: int = 1
    last_appear: int | None = None
    importance: float = 1.0

    # 境界轨迹（必须单调不减）
    milestones: list[Milestone] = field(default_factory=list)

    # 声纹：防 5000 章说话方式漂移
    voice: dict = field(default_factory=dict)
    #   {"语气": "...", "句长": "短/中/长", "口头禅": [...],
    #    "禁用词": [...], "自称": "..."}

    # 人物弧光（一句话，不展开）
    arc: str = ""
    #   "从只想活下去，到愿意为别人去死"

    relationships: dict[str, str] = field(default_factory=dict)
    #   {"c3": "道侣（第1401章确立）"}

    # 不可变事实（写进 canon，全书不能改）
    immutable: dict[str, str] = field(default_factory=dict)
    #   {"左眉骨": "一道三厘米的旧疤"}

    def level_at(self, chapter: int) -> int:
        """第 N 章时的境界序号（1~108）。"""
        cur = 1
        for m in sorted(self.milestones, key=lambda x: x.chapter):
            if chapter >= m.chapter:
                cur = m.level_index
            else:
                break
        return cur

    def peak(self) -> int:
        return max((m.level_index for m in self.milestones), default=1)


@dataclass
class Cast:
    book_id: str = ""
    characters: list[Character] = field(default_factory=list)

    def get(self, cid: str) -> Character | None:
        for c in self.characters:
            if c.id == cid:
                return c
        return None

    def find(self, name: str) -> Character | None:
        for c in self.characters:
            if c.name == name or name in c.aliases:
                return c
        return None

    def by_role(self, role: str) -> list[Character]:
        return [c for c in self.characters if c.role == role]

    # ---------- 序列化 ----------
    def to_json(self) -> dict:
        return {
            "book_id": self.book_id,
            "characters": [asdict(c) for c in self.characters],
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2),
                     encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Cast":
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        c = cls(book_id=d.get("book_id", ""))
        for x in d.get("characters", []):
            ms = [Milestone(**m) for m in x.pop("milestones", [])]
            ch = Character(**x)
            ch.milestones = ms
            c.characters.append(ch)
        return c


# ==========================================================================
# 二、境界查询工具
# ==========================================================================

def level_index_by_name(world: WB.WorldBible, name: str) -> int:
    """按名字查境界序号，如 '金丹初期' → 7。"""
    for lv in world.levels:
        if lv.name == name:
            return lv.index
    raise KeyError(f"世界观里没有境界「{name}」")


def level_by_index(world: WB.WorldBible, idx: int) -> WB.Level:
    idx = max(1, min(len(world.levels), idx))
    return world.levels[idx - 1]


def realm_of(world: WB.WorldBible, idx: int) -> str:
    return level_by_index(world, idx).realm


def level_name(world: WB.WorldBible, idx: int) -> str:
    return level_by_index(world, idx).name


def chapters_of_level(world: WB.WorldBible, idx: int) -> tuple[int, int]:
    lv = level_by_index(world, idx)
    return lv.start_chapter, lv.end_chapter


# ==========================================================================
# 三、构建人物
# ==========================================================================

def build_cast(world: WB.WorldBible, total_chapters: int = 5000) -> Cast:
    """
    构建主要人物。8 个角色，覆盖全书 5000 章。

    设计原则：
    - 主角轨迹 = 世界观曲线（完全绑定）
    - 每个配角有明确的"登场/巅峰/退场"
    - 声纹两两不同（校验会检查）
    """
    L = lambda n: level_index_by_name(world, n)   # noqa: E731

    cast = Cast(book_id="sijie")

    # ---------------- c1 主角 ----------------
    # 主角轨迹完全来自世界观 108 阶曲线
    main_ms = [
        Milestone(lv.start_chapter, lv.index, lv.name)
        for lv in world.levels
    ]
    cast.characters.append(Character(
        id="c1", name="林昭", aliases=["小林", "昭哥", "林兄"],
        role="主角", gender="男", spirit_root="五灵根（后化五行大道）",
        origin="人界·青牛镇，铁匠之子",
        first_appear=1, last_appear=total_chapters, importance=1.0,
        milestones=main_ms,
        voice={
            "语气": "冷硬，少废话，情绪从不外露",
            "句长": "短",
            "口头禅": ["嗯", "走", "不用"],
            "禁用词": ["其实", "或许", "我觉得"],
            "自称": "我",
        },
        arc="从只想让家人活下去，到愿意为不相干的人去死",
        relationships={
            "c2": "师父（第 3 章拜师）",
            "c3": "同门→道侣（第 1401 章确立）",
            "c4": "宿敌→盟友→死敌",
            "c7": "妹妹",
            "c5": "仙界引路人（第3001章）",
            "c6": "审判者（第4201章）",
            "c8": "灵界大敌（第1700章）",
        },
        immutable={
            "左眉骨": "一道三厘米的旧疤，三岁时磕在铁砧上",
            "左手": "虎口有厚茧，打铁留下的",
        },
    ))

    # ---------------- c2 师父 / 引路人 / 后来的叛神 ----------------
    # 关键约束：师父在第 100/500/1000 章必须比主角高 ≥3 阶
    #   主角第100章=4阶，第500章=14阶，第1000章=21阶
    #   所以师父至少要 7 / 17 / 24 阶
    cast.characters.append(Character(
        id="c2", name="沈鹤年", aliases=["沈老", "沈先生", "老沈"],
        role="师父", gender="男", spirit_root="单灵根（水）",
        origin="人界·青牛镇教书先生，真实身份是灵界贬谪者",
        first_appear=1, last_appear=total_chapters, importance=0.95,
        milestones=[
            Milestone(1, L("合体后期"), "隐居青牛镇，压制修为"),
            Milestone(600, L("大乘后期"), "为护林昭暴露实力"),
            Milestone(1200, L("渡劫后期"), "人界巅峰"),
            Milestone(1601, L("灵尊中期"), "重返灵界，任接引使"),
            Milestone(2400, L("灵帝后期"), "掌浮屠域"),
            Milestone(3200, L("太乙中期"), "入仙界"),
            Milestone(4000, L("准圣后期")),
            Milestone(4201, L("神将中期"), "入神界"),
            Milestone(4600, L("神皇后期"), "叛神，与林昭决裂"),
            Milestone(4990, L("神尊后期")),
        ],
        voice={
            "语气": "慢，爱用反问，从不下判断句",
            "句长": "长",
            "口头禅": ["你说呢", "未必", "急什么"],
            "禁用词": ["综上所述", "必然", "一定"],
            "自称": "老夫（对外）/ 我（对林昭）",
        },
        arc="从守护者，到被自己的守护所背叛",
        relationships={
            "c1": "徒弟",
            "c4": "旧识（灵界同期）",
            "c6": "旧主",
        },
        immutable={
            "右手": "缺了半截小指，说是年轻时被机器咬的（真实原因第 3050 章揭晓）",
            "左眼": "瞳孔是灰的，看不见东西",
        },
    ))

    # ---------------- c3 道侣 ----------------
    # 主角第180章=7阶，第400章=11阶，第900章=20阶
    # 道侣应与主角接近（同门），略高或略低
    cast.characters.append(Character(
        id="c3", name="苏见月", aliases=["小月", "苏师姐", "见月"],
        role="道侣", gender="女", spirit_root="变异灵根（冰）",
        origin="人界·玄霜宗内门弟子",
        first_appear=180, last_appear=2600, importance=0.9,
        milestones=[
            Milestone(180, L("金丹初期"), "登场，比林昭高一阶"),
            Milestone(400, L("元婴后期")),
            Milestone(900, L("合体中期")),
            Milestone(1401, L("渡劫初期"), "与林昭确立道侣"),
            Milestone(2000, L("灵皇中期")),
            Milestone(2400, L("灵帝中期"), "为护林昭重伤"),
            Milestone(2600, L("灵祖中期"), "身死（不可复活）"),
        ],
        voice={
            "语气": "短促，带刺，越亲近越刻薄",
            "句长": "短",
            "口头禅": ["废话", "闭嘴", "烦"],
            "禁用词": ["抱歉", "对不起", "谢谢"],
            "自称": "我",
        },
        arc="从只信自己，到愿意把命交出去",
        relationships={
            "c1": "同门→道侣",
            "c4": "厌恶（第 3300 章后林昭才知原因）",
        },
        immutable={
            "左耳": "耳垂上有个豁口，小时候被师父打的",
        },
    ))

    # ---------------- c4 宿敌（贯穿全书的对手）----------------
    # 主角第900章=20阶，所以陆无咎登场必须 >20阶
    # 但要能一路跟到最后（第4800章主角=104阶）
    cast.characters.append(Character(
        id="c4", name="陆无咎", aliases=["陆老魔", "无咎道人"],
        role="宿敌", gender="男", spirit_root="五灵根（伪）",
        origin="人界·散修，靠夺舍续命",
        first_appear=900, last_appear=total_chapters, importance=0.85,
        milestones=[
            Milestone(900, L("大乘后期"), "登场，碾压林昭"),
            Milestone(1601, L("灵帝中期"), "在灵界重新崛起"),
            Milestone(2400, L("灵源中期")),
            Milestone(3001, L("太乙中期")),
            Milestone(3700, L("天道初期")),
            Milestone(4201, L("神皇中期")),
            Milestone(4800, L("神尊后期"), "最终对决"),
        ],
        voice={
            "语气": "拖长音，阴阳怪气，爱用敬语说狠话",
            "句长": "中",
            "口头禅": ["有意思", "请吧", "恕不奉陪"],
            "禁用词": ["谢谢", "感激"],
            "自称": "在下 / 本座",
        },
        arc="从纯粹的恶，到证明自己也曾想过善",
        relationships={
            "c1": "宿敌",
            "c2": "旧识",
            "c3": "杀她师父的人（第3300章揭晓）",
            "c8": "旧盟",
        },
        immutable={
            "嗓音": "被雷劈过，沙哑得听不出年纪",
        },
    ))

    # ---------------- c5 仙界线引路人 ----------------
    # 主角第3001章=55阶，引路人要明显更强
    cast.characters.append(Character(
        id="c5", name="白蘅", aliases=["白姑娘", "蘅娘"],
        role="引路人", gender="女", spirit_root="单灵根（风）",
        origin="仙界·散仙，被夺仙位后流落",
        first_appear=3001, last_appear=4200, importance=0.6,
        milestones=[
            Milestone(3001, L("太乙中期"), "比林昭高 13 阶"),
            Milestone(3600, L("大罗后期")),
            Milestone(4200, L("准圣后期"), "为林昭挡下天道一击，消散"),
        ],
        voice={
            "语气": "轻，几乎不表态，句子常不完整",
            "句长": "短",
            "口头禅": ["……", "也许吧"],
            "禁用词": ["我保证", "一定", "肯定"],
            "自称": "我",
        },
        arc="从不敢选，到第一次替别人做了选择",
        relationships={"c1": "引路人"},
        immutable={
            "脖子": "有一圈淡青色的痕，像被什么勒过",
        },
    ))

    # ---------------- c6 神界最终反派 ----------------
    # 主角第4201章=81阶，最终反派要高但不能高太多（≤9阶差）
    cast.characters.append(Character(
        id="c6", name="天枢", aliases=["神使天枢", "枢"],
        role="最终反派", gender="不明", spirit_root="无（神格持有者）",
        origin="神界·中枢，神界法则的执行者",
        first_appear=4201, last_appear=total_chapters, importance=0.8,
        milestones=[
            Milestone(4201, L("神将中期"), "比林昭高 7 阶"),
            Milestone(4600, L("神王后期")),
            Milestone(4900, L("神尊中期")),
            Milestone(4990, L("神尊后期")),
            Milestone(5000, L("神主后期"), "最终对决"),
        ],
        voice={
            "语气": "无起伏，像念判词，从不用第二人称",
            "句长": "中",
            "口头禅": ["依律", "此非汝所能问"],
            "禁用词": ["也许", "或许", "我想"],
            "自称": "吾",
        },
        arc="从法则的化身，到发现自己也是法则的囚徒",
        relationships={"c2": "旧主", "c1": "审判对象"},
        immutable={
            "面容": "永远看不清，看久了会头痛",
        },
    ))

    # ---------------- c7 亲人（凡人锚点）----------------
    cast.characters.append(Character(
        id="c7", name="林小满", aliases=["小满", "满儿"],
        role="亲人", gender="女", spirit_root="无（凡人）",
        origin="人界·青牛镇，林昭之妹",
        first_appear=1, last_appear=1650, importance=0.7,
        milestones=[
            Milestone(1, 1, "凡人"),
            Milestone(1650, 1, "寿终（凡人寿元）"),
        ],
        voice={
            "语气": "直白，爱抱怨，说话带青牛镇口音",
            "句长": "短",
            "口头禅": ["哥", "你别管", "真的假的"],
            "禁用词": ["在下", "本座", "道友"],
            "自称": "我",
        },
        arc="凡人的一生，是林昭修道路上永远的锚",
        relationships={"c1": "哥哥"},
        immutable={
            "右手": "小指少了一节，小时候被门夹的",
        },
    ))

    # ---------------- c8 中期强敌 ----------------
    # 主角第1700章=32阶，玄冥要高
    cast.characters.append(Character(
        id="c8", name="玄冥", aliases=["玄冥老祖"],
        role="宿敌", gender="男", spirit_root="变异灵根（暗）",
        origin="灵界·暗域之主",
        first_appear=1700, last_appear=3000, importance=0.65,
        milestones=[
            Milestone(1700, L("灵皇中期"), "比林昭高 6 阶"),
            Milestone(2400, L("灵祖初期")),
            Milestone(3000, L("灵源后期"), "被林昭斩杀"),
        ],
        voice={
            "语气": "平，慢，从不用感叹句",
            "句长": "中",
            "口头禅": ["哦", "继续"],
            "禁用词": ["啊", "呀", "呢"],
            "自称": "本尊",
        },
        arc="纯粹的强，用来量出主角走了多远",
        relationships={"c4": "旧盟", "c1": "猎物（第1700章）"},
        immutable={
            "身高": "两丈有余，站在人前像一堵墙",
        },
    ))

    return cast


# ==========================================================================
# 三·五、同步到正典
# ==========================================================================

def sync_to_canon(cast: "Cast", canon) -> None:
    """
    把人物同步进正典的 entities，并写入不可变事实。

    **这是一个真实 bug 的修复。** 之前 ContextBuilder 里 render_state()
    遍历 cast 时调 canon.find(cid)，但 canon.entities 是空的——
    因为人物从来没被写进正典。结果「世界状态」块永远是空的，
    模型完全不知道在场的人是谁、什么境界。

    这个 bug 在空 canon 上跑不会报错，只是悄悄输出空块。
    所以 verify 必须检查「世界状态块非空」。
    """
    import canon as CN
    for c in cast.characters:
        if canon.find(c.id):
            continue
        canon.add_entity(CN.Entity(
            id=c.id, name=c.name, kind="character",
            aliases=list(c.aliases), voice=dict(c.voice),
            first_appear=c.first_appear,
            last_appear=c.last_appear,
            importance=c.importance,
        ))
        # 不可变事实写进台账（全书不能改）
        for k, v in c.immutable.items():
            canon.add_fact(CN.Fact(
                entity=c.id, key=k, value=v,
                valid_from=c.first_appear,
                valid_to=None, source_chapter=c.first_appear,
                immutable=True, weight=1.0,
            ))


# ==========================================================================
# 四、校验：人物能不能撑 5000 章
# ==========================================================================

def validate(cast: Cast, world: WB.WorldBible,
             total_chapters: int = 5000) -> list[str]:
    """
    校验人物体系。任何一条不通过，不该开写。

    分三类：
    A. 结构性（会让流水线崩）
    B. 叙事性（会让读者弃书）
    C. 一致性（会让设定崩塌）
    """
    problems: list[str] = []
    if not cast.characters:
        return ["❌ 人物为空"]

    main = cast.get("c1")
    if not main:
        return ["❌ 缺少主角 c1"]

    # ---------------- A. 结构性 ----------------
    n_levels = len(world.levels)
    for c in cast.characters:
        if not c.milestones:
            problems.append(f"❌ {c.name} 没有境界轨迹")
            continue
        ms = sorted(c.milestones, key=lambda m: m.chapter)
        # 境界序号必须在 1..108
        for m in ms:
            if not (1 <= m.level_index <= n_levels):
                problems.append(
                    f"❌ {c.name} 第{m.chapter}章境界序号 {m.level_index} "
                    f"越界（1~{n_levels}）")
        # 必须单调不减
        for a, b in zip(ms, ms[1:]):
            if b.level_index < a.level_index:
                problems.append(
                    f"❌ {c.name} 境界倒退：第{a.chapter}章 "
                    f"{level_name(world, a.level_index)} → 第{b.chapter}章 "
                    f"{level_name(world, b.level_index)}")
        # 章号必须在 1..total
        for m in ms:
            if not (1 <= m.chapter <= total_chapters):
                problems.append(
                    f"❌ {c.name} 里程碑章号 {m.chapter} 越界")

    # 主角必须走到 108 阶
    if main.peak() != n_levels:
        problems.append(
            f"❌ 主角巅峰只到 {level_name(world, main.peak())}（第 {main.peak()} 阶），"
            f"应到 {level_name(world, n_levels)}（第 {n_levels} 阶）")
    if main.level_at(total_chapters) != n_levels:
        problems.append(
            f"❌ 主角第 {total_chapters} 章只有 "
            f"{level_name(world, main.level_at(total_chapters))}，未达终点")

    # ---------------- B. 叙事性 ----------------
    # B1. 师父必须比主角强（在主角拜师后的一段时期内）
    master = next((c for c in cast.characters if c.role == "师父"), None)
    if master:
        gaps = []
        for ch in (100, 500, 1000):
            g = master.level_at(ch) - main.level_at(ch)
            gaps.append(g)
            if g < 3:
                problems.append(
                    f"❌ 师父「{master.name}」第{ch}章只比主角高 {g} 阶，"
                    f"教不了（应 ≥3 阶）")
        # 但差距不能太大
        for ch, g in zip((100, 500, 1000), gaps):
            if g > 30:
                problems.append(
                    f"⚠️ 师父「{master.name}」第{ch}章比主角高 {g} 阶，"
                    f"差距过大，主角像蝼蚁")

    # B2. 反派登场时必须比主角强
    for c in cast.characters:
        if c.role not in ("宿敌", "最终反派"):
            continue
        ch0 = c.first_appear
        if ch0 > total_chapters:
            continue
        g = c.level_at(ch0) - main.level_at(ch0)
        if g <= 0:
            problems.append(
                f"❌ 反派「{c.name}」第{ch0}章登场时境界"
                f"（{level_name(world, c.level_at(ch0))}）"
                f"不高于主角（{level_name(world, main.level_at(ch0))}），"
                f"冲突不成立")
        elif g > 9:
            problems.append(
                f"⚠️ 反派「{c.name}」第{ch0}章比主角高 {g} 阶，"
                f"差距过大（>9 阶），读者觉得没法打")

    # B3. 主角不能长期无敌（否则 5000 章没张力）
    #     检查：每个 500 章区间内，是否至少有一个人比主角强
    for start in range(1, 4000, 500):
        end = start + 499
        mid = (start + end) // 2
        stronger = [
            c for c in cast.characters
            if c.id != "c1"
            and c.first_appear <= mid <= (c.last_appear or total_chapters)
            and c.level_at(mid) > main.level_at(mid)
        ]
        if not stronger:
            problems.append(
                f"⚠️ 第 {start}~{end} 章期间没有任何人比主角强，"
                f"缺乏张力（主角过早无敌）")

    # B4. 死者不能复活
    dead = [c for c in cast.characters
            if c.last_appear is not None and c.last_appear < total_chapters]
    for c in dead:
        # 死亡之后不能再有里程碑
        later = [m for m in c.milestones if m.chapter > c.last_appear]
        if later:
            problems.append(
                f"❌ {c.name} 已在第 {c.last_appear} 章退场，"
                f"却还有第 {later[0].chapter} 章的里程碑（死者不可复生）")

    # ---------------- C. 一致性 ----------------
    # C1. 名字/别名不能重复
    seen: dict[str, str] = {}
    for c in cast.characters:
        for n in [c.name] + c.aliases:
            if n in seen and seen[n] != c.id:
                problems.append(
                    f"❌ 名字「{n}」同时属于 {seen[n]} 和 {c.id}")
            seen[n] = c.id

    # C2. 声纹必须两两可区分
    #     检查：不能有两个角色的口头禅 + 语气完全一致
    sigs = {}
    for c in cast.characters:
        v = c.voice
        sig = (v.get("语气", ""), tuple(v.get("口头禅", [])))
        if sig in sigs:
            problems.append(
                f"❌ {c.name} 和 {sigs[sig]} 声纹完全一致，读者分不清")
        sigs[sig] = c.name

    # C3. 每个角色必须有声纹（否则 5000 章会漂移）
    for c in cast.characters:
        if not c.voice:
            problems.append(f"❌ {c.name} 缺少声纹设定")
        elif not c.voice.get("口头禅"):
            problems.append(f"⚠️ {c.name} 没有口头禅，辨识度不足")

    # C4. 关系必须双向
    for c in cast.characters:
        for other_id in c.relationships:
            other = cast.get(other_id)
            if not other:
                problems.append(
                    f"❌ {c.name} 的关系指向不存在的角色 {other_id}")
            elif c.id not in other.relationships:
                problems.append(
                    f"⚠️ {c.name} → {other.name} 有单向关系，"
                    f"但 {other.name} 没有回指")

    return problems


# ==========================================================================
# 五、分析：主角是不是太强 / 太弱
# ==========================================================================

def power_ranking_at(cast: Cast, chapter: int) -> list[tuple[str, int, bool]]:
    """
    第 N 章时，所有在场角色的境界排名。

    返回 [(名字, 境界序号, 是否主角), ...] 按境界降序。
    这是检验"主角不是最强"的核心工具。
    """
    out = []
    for c in cast.characters:
        if c.first_appear > chapter:
            continue
        if c.last_appear is not None and chapter > c.last_appear:
            continue
        out.append((c.name, c.level_at(chapter), c.id == "c1"))
    out.sort(key=lambda x: -x[1])
    return out


def report(cast: Cast, world: WB.WorldBible,
           total_chapters: int = 5000) -> dict:
    main = cast.get("c1")
    out = {
        "角色数": len(cast.characters),
        "主角巅峰": level_name(world, main.peak()) if main else "",
        "主角终点": level_name(world, main.level_at(total_chapters)) if main else "",
    }
    # 主角排名变化
    ranks = {}
    for ch in (100, 1000, 2000, 3000, 4000, 4500, 4999):
        r = power_ranking_at(cast, ch)
        pos = next((i + 1 for i, x in enumerate(r) if x[2]), None)
        ranks[ch] = {"排名": pos, "同场人数": len(r),
                     "最强": r[0][0] if r else ""}
    out["主角排名"] = ranks
    return out


# ==========================================================================
# 六、CLI
# ==========================================================================

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    world = WB.build_world(5000, title="四界")
    cast = build_cast(world, 5000)

    out_p = here.parent / "out" / "cast.json"
    cast.save(out_p)

    print("=" * 72)
    print("人物体系（8 个角色）")
    print("=" * 72)
    for c in cast.characters:
        print(f"\n【{c.name}】{c.role}｜{c.spirit_root}｜第 {c.first_appear} 章登场")
        print(f"  弧光：{c.arc}")
        print(f"  声音：{c.voice.get('语气','')}"
              f"｜口头禅 {'/'.join(c.voice.get('口头禅',[]))}"
              f"｜绝不说 {'/'.join(c.voice.get('禁用词',[]))}")
        ms = sorted(c.milestones, key=lambda m: m.chapter)
        print(f"  轨迹：" + " → ".join(
            f"第{m.chapter}章 {level_name(world, m.level_index)}"
            for m in ms[:6])
            + ("…" if len(ms) > 6 else ""))

    print("\n" + "=" * 72)
    print("主角排名变化（关键：不能过早无敌）")
    print("=" * 72)
    rep = report(cast, world)
    print(f"{'章号':<8}{'排名':<10}{'同场人数':<10}{'当场最强'}")
    print("-" * 72)
    for ch, d in rep["主角排名"].items():
        print(f"{ch:<8}{d['排名']}/{d['同场人数']:<8}{'':2}{d['同场人数']:<8}"
              f"{d['最强']}")

    print("\n" + "=" * 72)
    print("校验")
    print("=" * 72)
    problems = validate(cast, world)
    if problems:
        for p in problems:
            print("  " + p)
    else:
        print("  ✅ 人物体系可运行：境界单调、师父够强、反派够强、")
        print("     主角未过早无敌、死者未复活、声纹可区分、关系双向")

    print(f"\n已写出 {out_p}")
