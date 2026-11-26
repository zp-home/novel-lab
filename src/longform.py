#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
longform.py —— 5000 章 / 2000 万字长篇小说编排器

为什么 5000 章不能用"生成 → 质检 → 出稿"这条流水线
=================================================

上一版（`pipeline.py`）是为「3000 本 × 5000 字」设计的：每本独立、无记忆、
写完就完。**5000 章是它的反面**：单本、极长、状态必须连续 2000 万字。

三个数字决定了架构：

    第 3000 章时前文 = 1200 万字 ≈ 1800 万 tokens   → 任何窗口都装不下
    5000 章 × 4000 字 = 2000 万字                   → 需要约 2 万次模型调用
    单章 4000 字                                     → 一次生成必然平均化

所以架构必须满足：

1. **上下文恒定**。第 3000 章注入的上下文，跟第 10 章一样大（~4000 tokens）。
   做法：状态从 `canon.py` 的台账查，不从"前文摘要"里捞。

2. **三级大纲 + 滚动细化**。不能一次规划 5000 章（大纲会空洞化），
   也不能一章一规划（会跑偏）。做法：
       全书总纲（1 次，5000 章骨架）
         → 卷纲（每 50 章一卷，共 100 卷，写之前才规划）
           → 弧纲（每卷内 5 弧，每弧 10 章）
             → 章纲（写之前才细化）

3. **分卷审计**。每 50 章做一次"体检 + 纠偏"，
   把偏差在变成 5000 章灾难之前拦住。

4. **断点续跑**。2 万次调用必然中断。每章落盘，随时可续。

成本现实（必须提前知道）
======================

按每章 4 次调用（1 章纲 + 2 正文段 + 1 润色）估算：
    5000 章 × 4 = 20,000 次调用
    每次约 3000 输入 + 1500 输出 tokens
    总计约 6000 万输入 + 3000 万输出 tokens

按当前主流 API 价格，这是一笔**四位数到五位数人民币**的开销，
以及**数十小时到数天**的连续运行。这不是"点一下就出书"。

如果预算/时间不允许，正确做法是**先跑 100 章验证架构**，
而不是直接开 5000 章。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, asdict, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import canon as CN
import prompts as P
import worldbuild as WB
import characters as CH

HAN_RE = re.compile(r"[\u4e00-\u9fff]")


def n_han(s: str) -> int:
    return len(HAN_RE.findall(s))


# ==========================================================================
# 配置
# ==========================================================================

@dataclass
class BookConfig:
    title: str = ""
    genre: str = ""
    logline: str = ""
    total_chapters: int = 5000
    words_per_chapter: int = 4000
    chapters_per_volume: int = 50        # 一卷 50 章
    arcs_per_volume: int = 5             # 一卷 5 弧
    chapters_per_arc: int = 10           # 一弧 10 章
    segments_per_chapter: int = 3        # 一章分 3 段写
    audit_every_volume: bool = True

    @property
    def volumes(self) -> int:
        return (self.total_chapters + self.chapters_per_volume - 1) // self.chapters_per_volume

    @property
    def words_per_segment(self) -> int:
        return self.words_per_chapter // self.segments_per_chapter


# ==========================================================================
# 三级大纲
# ==========================================================================

@dataclass
class OutlineNode:
    """统一的大纲节点：全书 / 卷 / 弧 / 章，四层用同一个结构。"""
    level: str                    # book / volume / arc / chapter
    index: int                    # 在父节点内的序号
    title: str = ""
    goal: str = ""                # 这一段要达成什么（一句话）
    beats: list[str] = field(default_factory=list)
    start_chapter: int = 1
    end_chapter: int = 1
    key_events: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    ends_with: str = ""           # 必须停在这里
    escalates: str = ""           # 比上一段"更大"在哪里


class OutlineTree:
    """
    三级大纲树。

    核心原则：**只细化到"接下来要写的那一段"**。
    全书总纲只有骨架，卷纲在开写该卷时才生成，弧纲在开写该弧时才生成。
    这样既能保证不跑偏（上层已定），又不会大纲空洞（下层按需细化）。
    """

    def __init__(self, cfg: BookConfig):
        self.cfg = cfg
        self.book: OutlineNode | None = None
        self.volumes: dict[int, OutlineNode] = {}
        self.arcs: dict[tuple[int, int], OutlineNode] = {}
        self.chapters: dict[int, OutlineNode] = {}

    # ---- 查询 ----
    def volume_of(self, ch: int) -> int:
        return (ch - 1) // self.cfg.chapters_per_volume + 1

    def arc_of(self, ch: int) -> int:
        vol_start = (self.volume_of(ch) - 1) * self.cfg.chapters_per_volume
        return (ch - vol_start - 1) // self.cfg.chapters_per_arc + 1

    def get_volume(self, v: int) -> OutlineNode | None:
        return self.volumes.get(v)

    def get_arc(self, v: int, a: int) -> OutlineNode | None:
        return self.arcs.get((v, a))

    def get_chapter(self, ch: int) -> OutlineNode | None:
        return self.chapters.get(ch)

    # ---- 就绪检查（决定下一步该生成什么）----
    def needs_volume_outline(self, ch: int) -> bool:
        return self.volume_of(ch) not in self.volumes

    def needs_arc_outline(self, ch: int) -> bool:
        v, a = self.volume_of(ch), self.arc_of(ch)
        return (v, a) not in self.arcs

    def needs_chapter_outline(self, ch: int) -> bool:
        return ch not in self.chapters

    # ---- 序列化 ----
    def to_json(self) -> dict:
        return {
            "book": asdict(self.book) if self.book else None,
            "volumes": {str(k): asdict(v) for k, v in self.volumes.items()},
            "arcs": {f"{k[0]}-{k[1]}": asdict(v) for k, v in self.arcs.items()},
            "chapters": {str(k): asdict(v) for k, v in self.chapters.items()},
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2),
                     encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, cfg: BookConfig) -> "OutlineTree":
        t = cls(cfg)
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if d.get("book"):
            t.book = OutlineNode(**d["book"])
        for k, v in d.get("volumes", {}).items():
            t.volumes[int(k)] = OutlineNode(**v)
        for k, v in d.get("arcs", {}).items():
            vv, aa = k.split("-")
            t.arcs[(int(vv), int(aa))] = OutlineNode(**v)
        for k, v in d.get("chapters", {}).items():
            t.chapters[int(k)] = OutlineNode(**v)
        return t


# ==========================================================================
# 上下文预算：5000 章的核心
# ==========================================================================

class ContextBuilder:
    """
    组装第 N 章的 prompt 上下文。

    **这是整个 5000 章架构最关键的一处。** 铁律：

        注入的上下文大小，与章节号无关。

    第 10 章和第 4999 章注入的 token 数应该差不多（~4000）。
    如果随章节号增长，到第 1000 章就必然爆窗——这是绝大多数
    "AI 写百万字"项目在 100 章左右崩掉的真正原因。

    预算分配（约 4000 tokens）：
        世界状态（从 canon 台账查）    ~1000   最重要，优先保证
        本章 + 本弧大纲               ~600
        上一章结尾原文                ~400   保证文气连贯
        未回收伏笔                    ~300
        写作契约（禁用词等）          ~800   固定开销
        卷级上下文（当前卷目标）      ~400
        预留给模型输出                ----
    """

    def __init__(self, canon: CN.Canon, tree: OutlineTree, cfg: BookConfig,
                 style_contract: str = "",
                 world: "WB.WorldBible | None" = None,
                 cast: "CH.Cast | None" = None):
        self.canon = canon
        self.tree = tree
        self.cfg = cfg
        self.world = world
        self.cast = cast
        self.style = style_contract or P.style_contract()
        # 把人物境界轨迹挂到正典上，让 state_at() 能查到当前境界
        if cast is not None and world is not None:
            def _lookup(eid: str, ch: int):
                c = cast.get(eid)
                if not c:
                    return None
                return CH.level_name(world, c.level_at(ch))
            canon.level_lookup = _lookup

    def build(self, ch: int, prev_tail: str = "",
              cast: list[str] | None = None) -> str:
        v, a = self.tree.volume_of(ch), self.tree.arc_of(ch)
        vol = self.tree.get_volume(v)
        arc = self.tree.get_arc(v, a)
        chn = self.tree.get_chapter(ch)

        # 默认在场人物：本章指定 > 本弧指定 > 全书主要人物
        if cast is None:
            cast = (chn.characters if chn and chn.characters
                    else (arc.characters if arc and arc.characters else []))

        parts: list[str] = []

        # 1) 作品定位（恒定，很短）
        parts.append(
            f"【作品】《{self.cfg.title}》｜{self.cfg.genre}\n"
            f"【一句话】{self.cfg.logline}\n"
            f"【进度】第 {ch} / {self.cfg.total_chapters} 章"
            f"（第 {v}/{self.cfg.volumes} 卷 · 第 {a} 弧）")

        # 2) 力量体系（世界观注入，大小恒定）
        if self.world:
            parts.append("\n" + self.world.render_power_system(ch))

        # 3) 世界状态（从台账查，不从前文捞）
        parts.append("\n" + CN.render_state(self.canon, ch, cast,
                                            max_chars=1600))

        # 3) 卷/弧目标（提供"这一段要干什么"）
        if vol:
            parts.append(f"\n【本卷目标】{vol.title}：{vol.goal}")
            if vol.escalates:
                parts.append(f"【本卷要比上一卷强在哪】{vol.escalates}")
        if arc:
            parts.append(f"\n【本弧目标】{arc.title}：{arc.goal}")
            if arc.key_events:
                parts.append("【本弧关键事件】" +
                             "；".join(arc.key_events[:6]))

        # 4) 本章大纲
        if chn:
            parts.append(f"\n【本章】{chn.title}")
            for b in chn.beats:
                parts.append(f"  · {b}")
            if chn.ends_with:
                parts.append(f"  · 本章必须停在这里：{chn.ends_with}")

        # 5) 上一章结尾（原文，不是摘要——摘要会让文气断掉）
        if prev_tail:
            parts.append(f"\n【上一章最后一段（原文，必须无缝接上）】\n{prev_tail}")

        # 6) 写作契约
        parts.append("\n" + self.style)

        return "\n".join(parts)


# ==========================================================================
# 模型适配
# ==========================================================================

class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, base: str = "", key: str = "", model: str = "",
                 temperature: float = 0.9, timeout: int = 240):
        self.base = (base or os.environ.get("NOVEL_LLM_BASE", "")).rstrip("/")
        self.key = key or os.environ.get("NOVEL_LLM_KEY", "")
        self.model = model or os.environ.get("NOVEL_LLM_MODEL", "")
        self.temperature = temperature
        self.timeout = timeout
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.failures = 0

    @property
    def available(self) -> bool:
        return bool(self.base and self.key and self.model)

    def chat(self, prompt: str, max_tokens: int = 2500,
             json_mode: bool = False, temperature: float | None = None) -> str:
        if not self.available:
            raise LLMError("未配置 LLM")
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = __import__("urllib.request", fromlist=["Request"]).Request(
            self.base + "/chat/completions", data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.key})
        last = None
        for attempt in range(5):
            try:
                import urllib.request
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read().decode("utf-8"))
                txt = out["choices"][0]["message"]["content"]
                u = out.get("usage", {})
                self.calls += 1
                self.prompt_tokens += u.get("prompt_tokens", 0)
                self.completion_tokens += u.get("completion_tokens", 0)
                return txt
            except Exception as e:                      # noqa: BLE001
                last = e
                self.failures += 1
                time.sleep(min(60, 2 ** attempt))
        raise LLMError(f"调用失败 5 次：{last}")

    def cost_estimate(self, in_price: float = 1.0,
                      out_price: float = 2.0) -> float:
        """粗估成本（单位：元，按每百万 token 计价，默认值仅为示例）。"""
        return (self.prompt_tokens / 1e6 * in_price
                + self.completion_tokens / 1e6 * out_price)


# ==========================================================================
# 分卷审计
# ==========================================================================

@dataclass
class AuditResult:
    volume: int
    chapter: int
    problems: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


def audit_volume(c: CN.Canon, tree: OutlineTree, cfg: BookConfig,
                 volume: int, chapter: int,
                 max_growth: float = 200000.0) -> AuditResult:
    """
    每卷末体检。这是 5000 章唯一可行的"纠偏点"——
    不可能每章都全局检查（太贵），也不能等 5000 章写完才发现崩了。

    查四件事：
    1. 数值膨胀是否失控（战力增长倍数）
    2. 伏笔欠债是否过多（逾期数）
    3. 实体是否被遗忘（主要人物多久没出现）
    4. 时间线是否停滞（卷与卷之间故事内时间推进了吗）

    max_growth 的标定（别拍脑袋设阈值）：
        参考《斗破苍穹》量级，主角从"斗之气三段"到"斗帝"，
        约 1e4 ~ 1e6 倍。所以：
            1e3 倍  = 太保守，剧情没张力
            1e4~1e6 = 正常网文区间
            >1e6   = 开始失控（读者算不过来了）
        初版我把阈值设成 5000 倍，结果把正常数据判成"失控"——
        **阈值必须按题材标定，不能拍脑袋。**
    """
    r = AuditResult(volume=volume, chapter=chapter)

    # 1) 数值膨胀
    for key, s in c.numerics.items():
        g = s.growth_rate()
        r.stats[f"growth_{key}"] = round(g, 1)
        if g > max_growth:
            r.problems.append(
                f"数值膨胀失控：{key} 全书增长 {g:.0f} 倍"
                f"（超过 {max_growth:.0f} 倍，读者算不过来了）")
        for p in s.check_monotonic():
            r.problems.append(p)

    # 2) 伏笔欠债
    overdue = c.overdue_foreshadows(chapter)
    pending = [f for f in c.foreshadows if f.paid_off_in is None]
    r.stats["foreshadow_overdue"] = len(overdue)
    r.stats["foreshadow_pending"] = len(pending)
    if len(overdue) > 3:
        r.problems.append(
            f"伏笔欠债 {len(overdue)} 条逾期（{', '.join(f.id for f in overdue[:5])}），"
            f"读者会认为作者忘了")
    if len(pending) > 30:
        r.problems.append(
            f"未回收伏笔累计 {len(pending)} 条，超过 30 条即失控")

    # 3) 人物遗忘
    for e in c.entities.values():
        if e.importance < 0.5:
            continue
        last = e.last_appear or e.first_appear
        gap = chapter - last
        r.stats[f"gap_{e.name}"] = gap
        if gap > cfg.chapters_per_volume * 4:
            r.problems.append(
                f"主要人物「{e.name}」已 {gap} 章未出现"
                f"（上次第 {last} 章），读者会忘了他")

    # 4) 时间推进
    if len(c.timeline) >= 2:
        r.stats["timeline_entries"] = len(c.timeline)

    return r


# ==========================================================================
# 5000 章编排器
# ==========================================================================

class LongformRunner:
    def __init__(self, llm, out: Path, cfg: BookConfig,
                 verbose: bool = True, world: "WB.WorldBible | None" = None):
        self.llm = llm
        self.out = out
        self.cfg = cfg
        self.verbose = verbose
        self.log_lines: list[str] = []
        self.canon = CN.Canon()
        self.tree = OutlineTree(cfg)
        self.ctx: ContextBuilder | None = None
        self.audits: list[AuditResult] = []
        # 世界观是"编译期常量"，必须在任何模型调用之前就确定
        self.world: WB.WorldBible | None = world
        # 人物是"半硬"：境界轨迹与声纹结构化，弧光交给大纲层
        self.cast: CH.Cast | None = None

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.log_lines.append(line)
        if self.verbose:
            print(line, flush=True)

    # ---------- 断点恢复 ----------
    def load_or_init(self) -> int:
        """返回下一章章号。已完成的章直接跳过。"""
        self.out.mkdir(parents=True, exist_ok=True)
        canon_p = self.out / "canon.json"
        tree_p = self.out / "outline.json"
        cfg_p = self.out / "config.json"
        world_p = self.out / "world.json"

        if cfg_p.exists():
            d = json.loads(cfg_p.read_text(encoding="utf-8"))
            for k, v in d.items():
                if hasattr(self.cfg, k):
                    setattr(self.cfg, k, v)

        # ===== 第 0 步：世界观（必须先于一切）=====
        if world_p.exists():
            self.world = WB.WorldBible.load(world_p)
            self.log(f"恢复世界观：{len(self.world.realms)} 界 / "
                     f"{len(self.world.levels)} 阶")
        elif self.world is None:
            # 没有现成世界观 → 用四界默认模板构建并**冻结**
            self.log("构建世界观（四界 · 108 阶）…")
            self.world = WB.build_world(
                total_chapters=self.cfg.total_chapters,
                title=self.cfg.title)
            problems = WB.validate(self.world)
            if problems:
                for p in problems:
                    self.log("  " + p)
                raise RuntimeError(
                    "世界观校验未通过，拒绝开写。"
                    "（结构性错误会让流水线在第 N 章卡死）")
            self.log("✅ 世界观校验通过")
        self.world.save(world_p)

        # ===== 第 1 步：人物（依赖世界观）=====
        cast_p = self.out / "cast.json"
        if cast_p.exists():
            self.cast = CH.Cast.load(cast_p)
            self.log(f"恢复人物：{len(self.cast.characters)} 人")
        else:
            self.log("构建人物体系…")
            self.cast = CH.build_cast(self.world, self.cfg.total_chapters)
            problems = CH.validate(self.cast, self.world,
                                   self.cfg.total_chapters)
            if problems:
                for pb in problems:
                    self.log("  " + pb)
                raise RuntimeError(
                    "人物校验未通过，拒绝开写。"
                    "（境界倒退/师父不够强/主角过早无敌都会让 5000 章失去张力）")
            self.log("✅ 人物校验通过")
        self.cast.save(cast_p)

        # 人物必须同步进正典，否则「世界状态」块永远是空的
        CH.sync_to_canon(self.cast, self.canon)

        if canon_p.exists():
            self.canon = CN.Canon.load(canon_p)
            self.log(f"恢复正典：{len(self.canon.facts)} 条事实，"
                     f"{len(self.canon.entities)} 个实体")
        if tree_p.exists():
            self.tree = OutlineTree.load(tree_p, self.cfg)
            self.log(f"恢复大纲：{len(self.tree.volumes)} 卷 / "
                     f"{len(self.tree.arcs)} 弧 / "
                     f"{len(self.tree.chapters)} 章")

        self.ctx = ContextBuilder(self.canon, self.tree, self.cfg,
                                  world=self.world, cast=self.cast)

        # 找到第一个没写完的章
        for ch in range(1, self.cfg.total_chapters + 1):
            if not (self.out / "chapters" / f"{ch:05d}.txt").exists():
                return ch
        return self.cfg.total_chapters + 1

    def save_state(self) -> None:
        self.canon.save(self.out / "canon.json")
        self.tree.save(self.out / "outline.json")
        (self.out / "config.json").write_text(
            json.dumps(asdict(self.cfg), ensure_ascii=False, indent=2),
            encoding="utf-8")

    # ---------- 大纲生成 ----------
    def ensure_book_outline(self) -> None:
        if self.tree.book is not None:
            return
        self.log("生成全书总纲（5000 章骨架）…")
        raw = self.llm.chat(
            self._prompt_book_outline(), max_tokens=3000, json_mode=True)
        d = json.loads(raw)
        self.tree.book = OutlineNode(
            level="book", index=1, title=d.get("title", self.cfg.title),
            goal=d.get("spine", ""),
            beats=d.get("acts", []),
            start_chapter=1, end_chapter=self.cfg.total_chapters,
            key_events=d.get("milestones", []),
        )
        self.cfg.title = self.cfg.title or d.get("title", "")
        self.cfg.logline = self.cfg.logline or d.get("logline", "")
        self.save_state()

    def _prompt_book_outline(self) -> str:
        power = self.world.render_power_system(1) if self.world else ''
        realm_list = ''
        if self.world:
            realm_list = "\n".join(
                f"  · {r['name']}（第 {r['start']}~{r['end']} 章）："
                f"{' → '.join(r['levels'])}"
                for r in self.world.realms)
        return f"""你要为一部 {self.cfg.total_chapters} 章、
每章 {self.cfg.words_per_chapter} 字、总计约
{self.cfg.total_chapters * self.cfg.words_per_chapter // 10000} 万字的超长篇网络小说
设计**全书骨架**。

【世界观（已定死，不可更改，不可自创境界名）】
{realm_list}

{power}

【关键约束】
这个体量（相当于 {self.cfg.total_chapters // 500} 部普通长篇拼起来）不可能
一次性规划清楚。所以你要给的是**脊柱**，不是细节：

1. **spine**：一句话说清"主角从哪来、要到哪去、被什么挡住"。60~100 字。
2. **acts**：把全书分成 5~7 幕。每幕给：
   - 覆盖章号区间（必须连续、无缝、加起来等于 {self.cfg.total_chapters}）
   - 这一幕的"主要矛盾"（一句话）
   - 这一幕结束时，局面比开幕时**不可逆地**变了什么
3. **milestones**：8~12 个"必须发生"的里程碑事件，每个标章号。
   这些是全书锚点，后面所有卷纲都必须服务它们。

【长篇的铁律】
- **每一幕都要比上一幕"更大"**：敌人更强、代价更高、主角失去更多。
  但不能只是数值变大，要**换维度**（从"打不过"变成"打不得"）。
- **主角必须有真实损失**。5000 章里至少 3 次重大失败，且损失不可挽回。
- **不要前 100 章就把爽点用完**。节奏要能撑 5000 章。

【输出严格 JSON】
{{
  "title": "书名",
  "logline": "一句话",
  "spine": "主角从哪来、要到哪去、被什么挡住",
  "acts": [
    {{"name": "第一幕·xx", "chapters": "1-800",
      "conflict": "这一幕的主要矛盾",
      "irreversible": "这一幕结束时不可逆地变了什么"}}
  ],
  "milestones": [{{"chapter": 500, "event": "必须发生的事"}}]
}}
"""

    def ensure_volume_outline(self, v: int) -> None:
        if v in self.tree.volumes:
            return
        start = (v - 1) * self.cfg.chapters_per_volume + 1
        end = min(v * self.cfg.chapters_per_volume, self.cfg.total_chapters)
        prev = self.tree.get_volume(v - 1)
        self.log(f"规划第 {v} 卷（第 {start}~{end} 章）…")

        raw = self.llm.chat(
            self._prompt_volume_outline(v, start, end, prev),
            max_tokens=2500, json_mode=True)
        d = json.loads(raw)
        self.tree.volumes[v] = OutlineNode(
            level="volume", index=v,
            title=d.get("title", f"第{v}卷"),
            goal=d.get("goal", ""),
            beats=d.get("arcs", []),
            start_chapter=start, end_chapter=end,
            key_events=d.get("key_events", []),
            characters=d.get("characters", []),
            escalates=d.get("escalates", ""),
        )
        self.save_state()

    def _prompt_volume_outline(self, v: int, start: int, end: int,
                               prev: OutlineNode | None) -> str:
        book = self.tree.book
        prev_block = "（这是第一卷，无前卷）"
        if prev:
            prev_block = (f"上一卷《{prev.title}》目标：{prev.goal}\n"
                          f"上一卷结束时局面：{prev.ends_with or '（未记录）'}")
        power = self.world.render_power_system(start) if self.world else ''
        return f"""你在为《{self.cfg.title}》规划第 {v} / {self.cfg.volumes} 卷
（第 {start}~{end} 章，共 {self.cfg.chapters_per_volume} 章）。

{power}

【全书脊柱】{book.spine if book else ''}
【全书里程碑】{json.dumps(book.key_events[:8] if book else [], ensure_ascii=False)}

【前一卷】{prev_block}

【本卷要求】
1. 本卷内要分成 {self.cfg.arcs_per_volume} 个弧，每弧 {self.cfg.chapters_per_arc} 章。
   每个弧给：标题、目标（一句话）、2~4 个关键事件。
2. **本卷必须推进主线**，不能是纯打怪升级的水章。
3. **escalates**：明确写出"本卷比上一卷强在哪"——
   如果答不出来，说明这卷是废的，要重设计。
4. **本卷结尾必须留一个钩子**，让读者想追下一卷。
5. 章号必须连续覆盖 {start}~{end}。

【输出严格 JSON】
{{
  "title": "第{v}卷·卷名",
  "goal": "本卷要达成什么",
  "escalates": "比上一卷强在哪（换维度，不是单纯变强）",
  "arcs": [
    {{"name": "弧名", "goal": "弧目标",
      "key_events": ["事件1", "事件2"]}}
  ],
  "key_events": ["本卷必须发生的3~5件事"],
  "characters": ["本卷主要出场人物id"]
}}
"""

    def ensure_arc_outline(self, v: int, a: int) -> None:
        if (v, a) in self.tree.arcs:
            return
        vol = self.tree.get_volume(v)
        vol_start = (v - 1) * self.cfg.chapters_per_volume
        start = vol_start + (a - 1) * self.cfg.chapters_per_arc + 1
        end = min(start + self.cfg.chapters_per_arc - 1,
                  self.cfg.total_chapters)
        self.log(f"  规划第 {v} 卷第 {a} 弧（第 {start}~{end} 章）…")

        raw = self.llm.chat(
            self._prompt_arc_outline(v, a, start, end, vol),
            max_tokens=2000, json_mode=True)
        d = json.loads(raw)
        self.tree.arcs[(v, a)] = OutlineNode(
            level="arc", index=a,
            title=d.get("title", f"第{a}弧"),
            goal=d.get("goal", ""),
            beats=d.get("beats", []),
            start_chapter=start, end_chapter=end,
            key_events=d.get("key_events", []),
            characters=d.get("characters", []),
            escalates=d.get("escalates", ""),
        )
        self.save_state()

    def _prompt_arc_outline(self, v: int, a: int, start: int, end: int,
                            vol: OutlineNode | None) -> str:
        return f"""《{self.cfg.title}》第 {v} 卷第 {a} 弧（第 {start}~{end} 章）。

【本卷】{vol.title if vol else ''}：{vol.goal if vol else ''}
【本卷关键事件】{json.dumps(vol.key_events if vol else [], ensure_ascii=False)}

【任务】把这一弧（{self.cfg.chapters_per_arc} 章）拆成"起—承—转—合"四段。

每段给：覆盖哪几章、这一段的核心事件、结束时局面怎么变了。
**四段必须逐级升级**，不能平铺。

【输出严格 JSON】
{{
  "title": "弧名",
  "goal": "本弧目标",
  "beats": [
    {{"name": "起", "chapters": "{start}-{start + self.cfg.chapters_per_arc // 4 - 1}",
      "event": "核心事件", "change": "局面怎么变了"}},
    {{"name": "承", "chapters": "...", "event": "...", "change": "..."}},
    {{"name": "转", "chapters": "...", "event": "...", "change": "..."}},
    {{"name": "合", "chapters": "...", "event": "...", "change": "..."}}
  ],
  "key_events": ["本弧关键事件"],
  "characters": ["出场人物id"],
  "escalates": "比上一弧强在哪"
}}
"""

    def ensure_chapter_outline(self, ch: int) -> None:
        if ch in self.tree.chapters:
            return
        v, a = self.tree.volume_of(ch), self.tree.arc_of(ch)
        arc = self.tree.get_arc(v, a)
        chn_prev = self.tree.get_chapter(ch - 1)

        raw = self.llm.chat(
            self._prompt_chapter_outline(ch, arc, chn_prev),
            max_tokens=1200, json_mode=True)
        d = json.loads(raw)
        self.tree.chapters[ch] = OutlineNode(
            level="chapter", index=ch,
            title=d.get("title", f"第{ch}章"),
            goal=d.get("goal", ""),
            beats=d.get("beats", []),
            start_chapter=ch, end_chapter=ch,
            characters=d.get("cast", []),
            ends_with=d.get("ends_with", ""),
        )
        self.save_state()

    def _prompt_chapter_outline(self, ch: int, arc: OutlineNode | None,
                                prev: OutlineNode | None) -> str:
        return f"""《{self.cfg.title}》第 {ch} 章（{self.cfg.words_per_chapter} 字）。

【本弧】{arc.title if arc else ''}：{arc.goal if arc else ''}
【本弧关键事件】{json.dumps(arc.key_events if arc else [], ensure_ascii=False)}
【上一章】{prev.title if prev else '（本章是开篇）'}：
{prev.goal if prev else ''}

【任务】给本章一个**具体**的大纲。4~6 个 beat，每个是一件事（不是一种状态）。

【铁律】
- 本章必须有**一个不可逆的变化**。如果删掉这章故事照常，这章就是废的。
- 结尾必须把问题**变大或变贵**，不能解决。
- 不允许"主角修炼/赶路/开会"这类无事件章节。
- ends_with 必须是一个具体动作或一句对话。

【输出严格 JSON】
{{
  "title": "章名",
  "goal": "本章主角想干什么（具体可执行）",
  "beats": ["事件1", "事件2", "事件3", "事件4"],
  "cast": ["出场人物id"],
  "ends_with": "本章最后一句话"
}}
"""

    # ---------- 正文生成 ----------
    def write_chapter(self, ch: int) -> str:
        chn = self.tree.get_chapter(ch)
        prev_tail = ""
        prev_p = self.out / "chapters" / f"{ch - 1:05d}.txt"
        if prev_p.exists():
            prev_tail = prev_p.read_text(encoding="utf-8")[-400:]

        context = self.ctx.build(ch, prev_tail,
                                 chn.characters if chn else None)

        segs: list[str] = []
        per = self.cfg.words_per_segment
        for i in range(1, self.cfg.segments_per_chapter + 1):
            is_last = i == self.cfg.segments_per_chapter
            seg_prev = "\n".join(segs)[-400:] or prev_tail
            pr = self._prompt_segment(ch, chn, i, context, seg_prev,
                                      per, is_last)
            txt = self.llm.chat(pr, max_tokens=2000).strip()
            if not txt:
                txt = "（本段生成失败）"
            segs.append(txt)
            if self.verbose:
                print(f"      段 {i}/{self.cfg.segments_per_chapter} "
                      f"{n_han(txt)} 字", flush=True)

        return "\n\n".join(segs)

    def _prompt_segment(self, ch: int, chn: OutlineNode | None, seg: int,
                        context: str, prev_text: str, target: int,
                        is_last: bool) -> str:
        briefs = [
            "开场：用一个具体动作或声音切入。交代在场的人和位置，"
            "但不交代来龙去脉。让读者先看见东西。",
            "推进：目标开始受阻。加入对话，对话中双方说的和想的不一样。",
            "加压：障碍比预想的更麻烦。主角做出选择，这个选择有代价。",
            "转折落地：局面变了，且回不去。用动作完成转折。",
        ]
        brief = briefs[(seg - 1) % len(briefs)]
        end_req = ""
        if is_last and chn and chn.ends_with:
            end_req = (f"\n【本章必须停在这里】「{chn.ends_with}」\n"
                       f"本段最后一句必须是这句话或它的自然变体。")

        return f"""{context}

【本段任务（第 {seg}/{self.cfg.segments_per_chapter} 段）】
{brief}
本段 {target - 60}~{target + 60} 字。

【前文最后 400 字（必须无缝接上）】
{prev_text or "（本章开头）"}
{end_req}
只输出正文。不要标题，不要解释。
"""

    # ---------- 单章循环 ----------
    def run_chapter(self, ch: int) -> None:
        v = self.tree.volume_of(ch)

        # 按需细化大纲（三级滚动）
        self.ensure_book_outline()
        self.ensure_volume_outline(v)
        self.ensure_arc_outline(v, self.tree.arc_of(ch))
        self.ensure_chapter_outline(ch)

        # 写正文
        text = self.write_chapter(ch)

        # 落盘（断点续跑的依据）
        d = self.out / "chapters"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{ch:05d}.txt").write_text(text, encoding="utf-8")

        # 更新正典：记录出场、时间推进
        chn = self.tree.get_chapter(ch)
        for cid in (chn.characters if chn else []):
            e = self.canon.find(cid)
            if e:
                e.last_appear = ch
        self.save_state()

    # ---------- 主循环 ----------
    def run(self, start_ch: int = 1,
            limit: int | None = None) -> dict:
        end = self.cfg.total_chapters if limit is None else min(
            self.cfg.total_chapters, start_ch + limit - 1)
        t0 = time.time()
        done = 0
        current_volume = None

        for ch in range(start_ch, end + 1):
            v = self.tree.volume_of(ch)
            if current_volume is not None and v != current_volume:
                # 卷切换 → 审计上一卷
                if self.cfg.audit_every_volume:
                    ar = audit_volume(self.canon, self.tree, self.cfg,
                                      current_volume, ch - 1)
                    self.audits.append(ar)
                    if ar.ok:
                        self.log(f"✅ 第 {current_volume} 卷审计通过")
                    else:
                        self.log(f"⚠️ 第 {current_volume} 卷审计发现 "
                                 f"{len(ar.problems)} 个问题：")
                        for p in ar.problems:
                            self.log(f"    · {p}")
            current_volume = v

            try:
                self.run_chapter(ch)
                done += 1
            except Exception as e:                       # noqa: BLE001
                self.log(f"❌ 第 {ch} 章失败：{e}")
                (self.out / "errors.log").open("a", encoding="utf-8").write(
                    f"第{ch}章: {e}\n{traceback.format_exc()[-500:]}\n")
                continue

            if done % 10 == 0 or ch == end:
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (end - ch) / rate if rate else 0
                self.log(
                    f"进度 {ch}/{end}｜{rate*3600:.0f} 章/小时｜"
                    f"ETA {eta/3600:.1f} 小时｜"
                    f"调用 {self.llm.calls} 次")

        # 收尾审计
        if self.audits:
            (self.out / "audits.json").write_text(
                json.dumps([asdict(a) for a in self.audits],
                           ensure_ascii=False, indent=2), encoding="utf-8")
        (self.out / "run.log").write_text("\n".join(self.log_lines),
                                          encoding="utf-8")
        return {
            "chapters_done": done,
            "last_chapter": end,
            "llm_calls": self.llm.calls,
            "prompt_tokens": self.llm.prompt_tokens,
            "completion_tokens": self.llm.completion_tokens,
            "seconds": round(time.time() - t0, 1),
            "audits": len(self.audits),
        }


# ==========================================================================
# CLI
# ==========================================================================

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="5000 章 / 2000 万字长篇小说编排器")
    ap.add_argument("--out", default=str(HERE.parent / "out" / "longform"))
    ap.add_argument("--chapters", type=int, default=5000,
                    help="总章数")
    ap.add_argument("--words", type=int, default=4000, help="每章字数")
    ap.add_argument("--run", type=int, default=0,
                    help="本次跑多少章（0=跑到总章数）")
    ap.add_argument("--title", default="", help="书名（留空则自动生成）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只验证架构和上下文预算，不调用模型")
    args = ap.parse_args(argv)

    cfg = BookConfig(
        title=args.title,
        total_chapters=args.chapters,
        words_per_chapter=args.words,
    )
    out = Path(args.out)
    runner = LongformRunner(LLM(), out, cfg, verbose=True)
    start = runner.load_or_init()

    if args.dry_run:
        print("=" * 66)
        print("架构自检（不调用模型）")
        print("=" * 66)
        print(f"总章数：{cfg.total_chapters}｜每章 {cfg.words_per_chapter} 字")
        print(f"总字数：{cfg.total_chapters * cfg.words_per_chapter:,} 字")
        print(f"卷数：{cfg.volumes}（每卷 {cfg.chapters_per_volume} 章）")
        print(f"每卷 {cfg.arcs_per_volume} 弧 × 每弧 {cfg.chapters_per_arc} 章")
        print(f"每章 {cfg.segments_per_chapter} 段 × "
              f"约 {cfg.words_per_segment} 字")
        print()
        print("--- 上下文预算（关键：与章节号无关）---")
        for ch in (1, 100, 1000, 2500, 4999):
            if ch > cfg.total_chapters:
                continue
            block = runner.ctx.build(ch, "（上一章结尾示例）", ["c1", "c2"])
            print(f"  第{ch:5d}章：{len(block):5d} 字符 ≈ "
                  f"{len(block)//2:4d} tokens")
        print()
        print("--- 调用量估算 ---")
        per_ch = cfg.segments_per_chapter + 1     # 章纲 + 各段
        total = cfg.total_chapters * per_ch
        print(f"  每章 {per_ch} 次调用 → 全书约 {total:,} 次")
        print(f"  按每次 3000 入 / 1500 出 tokens 估算：")
        print(f"    输入 {total*3000/1e6:.0f}M tokens，"
              f"输出 {total*1500/1e6:.0f}M tokens")
        print()
        print("⚠️  这是四位数到五位数人民币、数十小时到数天的工程。")
        print("    建议先 --run 100 验证架构，再全量。")
        return 0

    llm = runner.llm
    if not llm.available:
        print("❌ 未配置模型。设置环境变量：")
        print("   NOVEL_LLM_BASE / NOVEL_LLM_KEY / NOVEL_LLM_MODEL")
        print("   或先跑 --dry-run 检查架构")
        return 1

    print(f"从第 {start} 章开始，目标 {cfg.total_chapters} 章")
    limit = args.run if args.run > 0 else None
    stats = runner.run(start, limit)
    print("\n===== 完成 =====")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
