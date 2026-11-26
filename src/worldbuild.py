#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
worldbuild.py —— 世界观与力量体系（5000 章的"宪法"）

为什么世界观必须最先定、而且必须是硬编码
======================================

5000 章里，大纲由模型生成。如果世界观没先钉死，会发生什么？

    第 1 卷：模型编一套境界（炼气→筑基→金丹…）
    第 20 卷：模型忘了，重新编一套（凝气→聚元→化丹…）
    第 60 卷：又一套
    → 读者第 20 卷就发现境界名对不上，弃书。

**世界观不是"设定文档"，是"编译期常量"。** 它必须在第一次调用模型之前
就完整、确定、可校验，之后模型只能引用，不能发明。

正确的生成顺序（这是本文件存在的理由）：

    ┌─ 第 0 步：世界观 + 力量体系  ← 硬编码 / 一次性生成后冻结
    │    四界、36 大境界、108 小阶、灵根、法宝、丹药、天劫…
    │    产物：world.json（之后只读，模型无权修改）
    │
    ├─ 第 1 步：人物（半硬）      ← 依赖世界观（境界决定人物强弱）
    │
    ├─ 第 2 步：全书总纲（脊柱）   ← 依赖人物 + 世界观
    │
    ├─ 第 3 步：卷纲（滚动）
    ├─ 第 4 步：弧纲（滚动）
    ├─ 第 5 步：章纲（滚动）
    └─ 第 6 步：正文

先定世界观，是因为**它是唯一不允许"随写随改"的东西**。
人物可以成长，剧情可以调整，但"境界有九层、不能跳级"这种规则一旦定下，
5000 章都不能变。

四界设计的核心难点：战力膨胀
==========================

2000 万字，主角从凡人到神主。如果战力按指数一路涨，
到第 3000 章数字已经没有意义了（读者算不过来）。

真实网文的解法是**换地图 + 界壁压制**：

    人界巅峰（渡劫）  →  进入灵界，被压制到灵界底层（灵徒）
    灵界巅峰（灵源）  →  进入仙界，被压制到仙界底层（散仙）

绝对战力仍在涨，但**相对排名会重置**。这既是经典套路，
也是解决"数字爆炸"的正确工程方案——所以本模块把它建模成
`sawtooth`（锯齿）曲线，而不是纯指数。

**这是这个文件最重要的设计决策。**
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ==========================================================================
# 一、四界 × 36 大境界 × 108 小阶
# ==========================================================================
# 设计约束：
#   1. 每界 9 大境界，命名风格要统一（不能人界叫"炼气"仙界叫"LV3"）
#   2. 每界内部必须"越来越难"，读者能感知到进步变慢
#   3. 界与界之间必须"质变"，不能只是数字变大
#   4. 108 阶对应 5000 章 → 平均 46 章/阶，节奏合理

REALMS = [
    {
        "id": "r1", "name": "人界", "alias": "凡俗界",
        "start": 1, "end": 1600,
        "essence": "炼精化气。修士以肉身承载灵气，寿元不过三百。",
        "power_start": 1.0, "power_end": 1.0e6,
        "levels": ["炼气", "筑基", "金丹", "元婴", "化神",
                   "炼虚", "合体", "大乘", "渡劫"],
        "level_desc": {
            "炼气": "引气入体，开辟丹田。凡人与修士的分界线。",
            "筑基": "筑就道基，灵气凝为真元。寿元增至二百。",
            "金丹": "真元结丹，可御器飞行。一方势力的话事人。",
            "元婴": "金丹化婴，神魂可离体。人间顶级战力。",
            "化神": "元婴化神，触摸法则边缘。人界顶点。",
            "炼虚": "以虚炼实，开始承受界壁压制。",
            "合体": "神与身合，人界已无对手。",
            "大乘": "大乘之境，只为渡劫而存。",
            "渡劫": "承天雷九重。过则飞升，败则身死道消。",
        },
    },
    {
        "id": "r2", "name": "灵界", "alias": "灵域",
        "start": 1601, "end": 3000,
        "essence": "炼气化神。灵界以灵根为本，无灵根者如凡人。",
        "power_start": 2.0e6, "power_end": 1.0e9,
        "levels": ["灵徒", "灵师", "灵王", "灵皇", "灵尊",
                   "灵圣", "灵帝", "灵祖", "灵源"],
        "level_desc": {
            "灵徒": "初入灵界，被界壁压制，境界跌落。",
            "灵师": "灵根觉醒，可驱使灵兽。",
            "灵王": "开辟灵域，一方霸主。",
            "灵皇": "灵域成国，号令万灵。",
            "灵尊": "灵根化道，触摸灵界本源。",
            "灵圣": "万灵朝拜，灵界巅峰之下。",
            "灵帝": "执掌一域法则。",
            "灵祖": "灵界最古老的存在。",
            "灵源": "与灵界本源合一，唯一飞升之路。",
        },
    },
    {
        "id": "r3", "name": "仙界", "alias": "仙域",
        "start": 3001, "end": 4200,
        "essence": "炼神还虚。仙界以法则为尊，仙位有限，需夺。",
        "power_start": 2.0e9, "power_end": 1.0e12,
        "levels": ["散仙", "真仙", "玄仙", "金仙", "太乙",
                   "大罗", "混元", "准圣", "天道"],
        "level_desc": {
            "散仙": "飞升而来，仙位未定，最底层的仙。",
            "真仙": "得仙位，寿与天齐。",
            "玄仙": "掌一道法则。",
            "金仙": "法则圆满，不朽不灭。",
            "太乙": "超脱时空，过去未来皆可见。",
            "大罗": "大罗金仙，一念生灭一界。",
            "混元": "万法归一。",
            "准圣": "半步圣人，只差一线。",
            "天道": "与天道同存。仙界之巅。",
        },
    },
    {
        "id": "r4", "name": "神界", "alias": "神域",
        "start": 4201, "end": 5000,
        "essence": "炼虚合道。神界以神格为基，神格唯一，不可复制。",
        "power_start": 2.0e12, "power_end": 1.0e15,
        "levels": ["神人", "神使", "神将", "神君", "神王",
                   "神皇", "神帝", "神尊", "神主"],
        "level_desc": {
            "神人": "初凝神格，神界最微末的存在。",
            "神使": "可为神界法则的代行者。",
            "神将": "统御神兵，镇守一方。",
            "神君": "一域之主。",
            "神王": "神界王座，只有十二席。",
            "神皇": "统御数域。",
            "神帝": "神界至尊之下第一人。",
            "神尊": "与神界意志并列。",
            "神主": "神界之主。全书终点。",
        },
    },
]

SUB_LEVELS = ["初期", "中期", "后期"]

# 每界内部的节奏曲线：越往后越慢（读者能感知进步变难）
# 权重 1.0 → 2.15 递增，即后期境界耗时是前期的 2 倍多
def _level_weights(n: int) -> list[float]:
    return [1.0 + 0.145 * i for i in range(n)]


# ==========================================================================
# 二、其他元素（灵根 / 法宝 / 丹药 / 天劫 / 势力）
# ==========================================================================

SPIRIT_ROOTS = {
    "单灵根": "五行之一，修炼速度最快，万中无一。",
    "双灵根": "五行之二，资质上佳。",
    "三灵根": "常见资质，中人之姿。",
    "四灵根": "资质平庸，多止步筑基。",
    "五灵根": "五行俱全，最慢，但可修五行大道。",
    "变异灵根": "雷、冰、风、暗等，罕见且强横。",
    "伪灵根": "残缺灵根，终身无望金丹。",
}

ARTIFACT_TIERS = ["凡器", "灵器", "宝器", "道器", "仙器", "神器"]

PILL_TIERS = ["一品", "二品", "三品", "四品", "五品",
              "六品", "七品", "八品", "九品"]

TRIBULATIONS = {
    "人界·渡劫": "九重天雷，一重强过一重。第九重为心魔劫。",
    "灵界·灵源": "界壁反噬，需以自身灵域承受界壁碾压。",
    "仙界·天道": "斩三尸，过去、现在、未来各斩一次。",
    "神界·神主": "神格归一，需击败前一任神主的残念。",
}

WORLD_RULES = [
    "境界共四界三十六境，每境三阶（初期/中期/后期），共一百零八阶。",
    "境界不可跳级。可以借外力短时爆发，但事后必然反噬。",
    "跨界飞升会受界壁压制，境界暂时跌落至新界底层，需重新攀升。",
    "死者不可复生。任何复活情节都是设定错误。",
    "神格唯一。同一神格不能同时存在两个持有者。",
    "灵气浓度：人界 1，灵界 100，仙界 10000，神界 1000000。",
    "凡人无法感知灵气。踏入炼气期是唯一的分界线。",
]


# ==========================================================================
# 三、数据结构
# ==========================================================================

@dataclass
class Level:
    """一个具体的小境界，如"金丹中期"。"""
    index: int                    # 1..108，全书线性编号
    realm: str                    # 人界 / 灵界 / 仙界 / 神界
    major: str                    # 金丹
    sub: str                      # 中期
    name: str                     # 金丹中期
    start_chapter: int
    end_chapter: int
    power: float                  # 绝对战力，**全书单调递增**
    rank: float                   # 在本界内的相对地位 0~1，**每界重置**（锯齿）

    @property
    def chapters(self) -> int:
        return self.end_chapter - self.start_chapter + 1


@dataclass
class WorldBible:
    """
    世界观圣经。**这是全书唯一不允许模型修改的文件。**

    一旦生成，之后所有环节只读。任何正文/大纲与它冲突，都以它为准。
    """
    title: str = ""
    genre: str = "仙侠 / 修真"
    logline: str = ""
    realms: list[dict] = field(default_factory=list)
    levels: list[Level] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    spirit_roots: dict[str, str] = field(default_factory=dict)
    artifact_tiers: list[str] = field(default_factory=list)
    pill_tiers: list[str] = field(default_factory=list)
    tribulations: dict[str, str] = field(default_factory=dict)
    total_chapters: int = 5000

    # ---------- 查询 ----------
    def level_at(self, chapter: int) -> Level | None:
        """第 N 章时主角的境界。"""
        for lv in self.levels:
            if lv.start_chapter <= chapter <= lv.end_chapter:
                return lv
        return None

    def realm_at(self, chapter: int) -> dict | None:
        lv = self.level_at(chapter)
        if not lv:
            return None
        for r in self.realms:
            if r["name"] == lv.realm:
                return r
        return None

    def power_at(self, chapter: int) -> float:
        lv = self.level_at(chapter)
        return lv.power if lv else 0.0

    def realm_range(self, realm_name: str) -> tuple[int, int]:
        for r in self.realms:
            if r["name"] == realm_name:
                return r["start"], r["end"]
        return (0, 0)

    # ---------- 序列化 ----------
    def to_json(self) -> dict:
        return {
            "title": self.title, "genre": self.genre, "logline": self.logline,
            "total_chapters": self.total_chapters,
            "realms": self.realms,
            "levels": [asdict(lv) for lv in self.levels],
            "rules": self.rules,
            "spirit_roots": self.spirit_roots,
            "artifact_tiers": self.artifact_tiers,
            "pill_tiers": self.pill_tiers,
            "tribulations": self.tribulations,
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2),
                     encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "WorldBible":
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        w = cls(
            title=d.get("title", ""), genre=d.get("genre", ""),
            logline=d.get("logline", ""),
            total_chapters=d.get("total_chapters", 5000),
            realms=d.get("realms", []),
            rules=d.get("rules", []),
            spirit_roots=d.get("spirit_roots", {}),
            artifact_tiers=d.get("artifact_tiers", []),
            pill_tiers=d.get("pill_tiers", []),
            tribulations=d.get("tribulations", {}),
        )
        w.levels = [Level(**lv) for lv in d.get("levels", [])]
        return w

    # ---------- 渲染（注入 prompt 用）----------
    def render_power_system(self, chapter: int) -> str:
        """
        渲染第 N 章的力量体系上下文。

        **大小恒定**：不管第几章，只渲染"当前界 + 当前境界 + 下一阶"，
        不会把 108 阶全列出来。
        """
        lv = self.level_at(chapter)
        if not lv:
            return "（境界体系未定义）"
        realm = self.realm_at(chapter)
        lines = [f"【力量体系 · 第 {chapter} 章】"]
        lines.append(f"当前界：{lv.realm}（{realm['essence'] if realm else ''}）")
        lines.append(f"当前境界：{lv.name}"
                     f"（第 {lv.start_chapter}~{lv.end_chapter} 章）")

        # 下一阶（给写作提供"往哪走"）
        nxt = next((x for x in self.levels if x.index == lv.index + 1), None)
        if nxt:
            lines.append(f"下一阶：{nxt.name}（第 {nxt.start_chapter} 章起）")
        else:
            lines.append("下一阶：无（已至终点）")

        # 本界九大境界（只列名字，不展开描述，控制长度）
        if realm:
            lines.append(f"本界境界序列：{' → '.join(realm['levels'])}")

        # 规则（只给最关键的 4 条）
        lines.append("硬规则：" + "；".join(self.rules[:4]))
        return "\n".join(lines)


# ==========================================================================
# 四、构建：从四界定义生成 108 阶 + 章节分配
# ==========================================================================

def build_world(total_chapters: int = 5000,
                title: str = "", logline: str = "") -> WorldBible:
    """
    从 REALMS 常量生成完整的境界体系。

    章节分配逻辑：
    - 每界拿到固定的章号区间（REALMS 里的 start/end）
    - 区间内按 _level_weights 分配到 9 大境界 × 3 小阶 = 27 阶
    - 权重递增 → 后期境界占更多章节（进步变慢）

    这样保证：108 阶无缝覆盖 1~5000 章，不重叠、不留空。
    """
    w = WorldBible(
        title=title or "四界",
        logline=logline,
        realms=REALMS,
        rules=WORLD_RULES,
        spirit_roots=SPIRIT_ROOTS,
        artifact_tiers=ARTIFACT_TIERS,
        pill_tiers=PILL_TIERS,
        tribulations=TRIBULATIONS,
        total_chapters=total_chapters,
    )

    levels: list[Level] = []
    idx = 0
    for r in REALMS:
        n_major = len(r["levels"])
        n_sub = len(SUB_LEVELS)
        n_levels = n_major * n_sub          # 27
        span = r["end"] - r["start"] + 1

        # 按递增权重分配章节数
        wts = _level_weights(n_levels)
        tot_w = sum(wts)
        alloc = [max(1, round(span * x / tot_w)) for x in wts]

        # 修正舍入误差，让总和精确等于 span
        diff = span - sum(alloc)
        i = len(alloc) - 1
        while diff != 0:
            if diff > 0:
                alloc[i] += 1
                diff -= 1
            elif alloc[i] > 1:
                alloc[i] -= 1
                diff += 1
            i = (i - 1) % len(alloc)

        # 生成 27 阶
        cur = r["start"]
        k = 0
        for major in r["levels"]:
            for sub in SUB_LEVELS:
                span_lv = alloc[k]
                # 绝对战力：在本界 [power_start, power_end] 间按进度指数插值。
                # **全书单调递增**——飞升后战力是涨的，不是跌的。
                t = k / max(1, n_levels - 1)
                power = r["power_start"] * ((r["power_end"] / r["power_start"]) ** t)
                idx += 1
                levels.append(Level(
                    index=idx, realm=r["name"], major=major, sub=sub,
                    name=f"{major}{sub}",
                    start_chapter=cur, end_chapter=cur + span_lv - 1,
                    power=round(power, 2),
                    rank=round(t, 4),
                ))
                cur += span_lv
                k += 1

    # 最后一阶必须精确收尾
    if levels and levels[-1].end_chapter != total_chapters:
        levels[-1].end_chapter = total_chapters

    w.levels = levels
    return w


# ==========================================================================
# 五、校验：这个世界观能不能撑 5000 章
# ==========================================================================

def validate(w: WorldBible) -> list[str]:
    """
    检查世界观是否"可运行"。任何一条不通过，就不该开始写。

    这比"设定写得好不好"重要得多——设定可以改，
    但**结构性错误**（比如章号有空洞）会让整个流水线在第 N 章卡死。
    """
    problems: list[str] = []

    if not w.levels:
        return ["❌ 境界体系为空"]

    # 1) 章号必须无缝覆盖
    if w.levels[0].start_chapter != 1:
        problems.append(f"❌ 第一阶不从第 1 章开始"
                        f"（实际 {w.levels[0].start_chapter}）")
    for a, b in zip(w.levels, w.levels[1:]):
        if b.start_chapter != a.end_chapter + 1:
            problems.append(
                f"❌ 章号断裂：{a.name} 结束于 {a.end_chapter}，"
                f"{b.name} 开始于 {b.start_chapter}")
    if w.levels[-1].end_chapter != w.total_chapters:
        problems.append(
            f"❌ 末阶结束于 {w.levels[-1].end_chapter}，"
            f"应为 {w.total_chapters}")

    # 2) 每阶至少 1 章
    for lv in w.levels:
        if lv.chapters < 1:
            problems.append(f"❌ {lv.name} 只有 {lv.chapters} 章")

    # 3) 节奏检查：单阶不能占太多章（否则读者会觉得卡关）
    max_span = w.total_chapters // len(w.levels) * 4
    for lv in w.levels:
        if lv.chapters > max_span:
            problems.append(
                f"⚠️ {lv.name} 占 {lv.chapters} 章，超过上限 {max_span}"
                f"（读者会觉得卡在一个境界里）")

    # 4) 绝对战力必须全书单调递增（飞升是变强，不是变弱）
    for a, b in zip(w.levels, w.levels[1:]):
        if b.power <= a.power:
            problems.append(
                f"❌ 战力倒退：{a.name}({a.power:.3g}) → {b.name}({b.power:.3g})")

    # 5) 界内相对地位必须每界重置（这是防"数字爆炸"的关键机制）
    #
    #    踩过的坑：初版我把「界壁压制」实现成"飞升后战力下降"，
    #    结果 validate() 同时报"战力倒退"和"界壁压制不足"——两条规则互相打架。
    #
    #    正确的仙侠逻辑是：**绝对战力只涨不跌，但相对排名会重置。**
    #    渡劫大能飞升灵界，绝对战力仍高于人界，但在灵界只是最底层灵徒。
    #    这就是 `rank` 字段：每界 0→1 重新走一遍。
    for i, r in enumerate(REALMS):
        first = next((lv for lv in w.levels if lv.realm == r["name"]), None)
        if not first:
            continue
        if first.rank > 0.05:
            problems.append(
                f"❌ {first.name} 的界内地位 rank={first.rank}，"
                f"应为 0（每界从底层开始）")
        if i > 0:
            prev_realm = REALMS[i - 1]["name"]
            prev_last = [lv for lv in w.levels if lv.realm == prev_realm][-1]
            # 绝对战力必须涨
            if first.power <= prev_last.power:
                problems.append(
                    f"❌ 跨界的绝对战力没有提升："
                    f"{prev_last.name}({prev_last.power:.3g}) → "
                    f"{first.name}({first.power:.3g})")
            # 但界内排名必须掉回底部
            if first.rank >= prev_last.rank:
                problems.append(
                    f"❌ 界壁压制失效：{first.name} 的界内地位 "
                    f"{first.rank} 未低于 {prev_last.name} 的 {prev_last.rank}")

    # 6) 境界数必须够（太少撑不住 5000 章）
    if len(w.levels) < 50:
        problems.append(
            f"⚠️ 只有 {len(w.levels)} 阶，撑 5000 章太勉强"
            f"（建议 ≥100 阶）")

    return problems


def stats(w: WorldBible) -> dict:
    out = {
        "总章数": w.total_chapters,
        "总阶数": len(w.levels),
        "界数": len(w.realms),
        "平均每阶章数": round(w.total_chapters / max(1, len(w.levels)), 1),
        "最终战力": f"{w.levels[-1].power:.3g}" if w.levels else "0",
        "战力总增长": f"{w.levels[-1].power / max(1e-9, w.levels[0].power):.3g} 倍"
                      if w.levels else "0",
    }
    for r in w.realms:
        n = sum(1 for lv in w.levels if lv.realm == r["name"])
        out[f"{r['name']}"] = f"第 {r['start']}~{r['end']} 章 / {n} 阶"
    return out


# ==========================================================================
# 六、CLI
# ==========================================================================

if __name__ == "__main__":
    import sys

    w = build_world(5000, title="四界", logline="")
    out = Path(__file__).resolve().parent.parent / "out" / "world.json"
    w.save(out)

    print("=" * 70)
    print("四界 · 力量体系")
    print("=" * 70)
    for r in REALMS:
        print(f"\n【{r['name']}】第 {r['start']}~{r['end']} 章")
        print(f"  {r['essence']}")
        print(f"  境界：{' → '.join(r['levels'])}")

    print("\n" + "=" * 70)
    print("108 阶章节分配（抽样）")
    print("=" * 70)
    print(f"{'阶':<12}{'章号区间':<18}{'章数':<8}{'战力':<14}")
    print("-" * 70)
    for lv in w.levels:
        if lv.sub == "初期":          # 每大境界只看初期，避免刷屏
            print(f"{lv.name:<12}{f'{lv.start_chapter}~{lv.end_chapter}':<18}"
                  f"{lv.chapters:<8}{lv.power:<14.3g}")

    print("\n" + "=" * 70)
    print("统计")
    print("=" * 70)
    for k, v in stats(w).items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 70)
    print("校验")
    print("=" * 70)
    problems = validate(w)
    if problems:
        for p in problems:
            print("  " + p)
    else:
        print("  ✅ 世界观可运行：章号无缝、战力单调、界壁压制有效、节奏合理")

    print("\n" + "=" * 70)
    print("注入 prompt 的样子（大小恒定）")
    print("=" * 70)
    for ch in (1, 500, 2000, 3500, 4999):
        block = w.render_power_system(ch)
        print(f"\n--- 第 {ch} 章（{len(block)} 字符）---")
        print(block)
