#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_dashboard.py —— 导出可视化大屏所需的数据

大屏要展示的核心事实：
1. 存了什么（7 个存储层，各自的结构）
2. 怎么用（第 N 章注入什么）
3. 为什么不是 RAG（对比）

导出成一份 JSON，HTML 直接内联。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import canon as CN
import longform as LF
import worldbuild as WB
import characters as CH
import outline as OL
import prompts as P


def build_canon() -> CN.Canon:
    """造一个真实的、覆盖 5000 章的 demo 正典。"""
    c = CN.Canon()
    c.rules = WB.WORLD_RULES[:5]

    chars = [
        ("c1", "林昭", ["小林", "昭哥"], 1, 1.0,
         {"语气": "冷硬，少废话", "口头禅": ["嗯", "走"], "禁用词": ["其实", "或许"]}),
        ("c2", "沈鹤年", ["沈老"], 1, 0.9,
         {"语气": "慢，爱用反问", "口头禅": ["你说呢"], "禁用词": ["综上所述"]}),
        ("c3", "苏见月", ["小月", "苏师姐"], 180, 0.85,
         {"语气": "短促，带刺", "口头禅": ["废话"], "禁用词": ["抱歉"]}),
        ("c4", "陆无咎", ["陆老魔"], 900, 0.7,
         {"语气": "拖长音，阴阳怪气", "口头禅": ["有意思"], "禁用词": ["谢谢"]}),
        ("c5", "白蘅", ["白姑娘"], 2100, 0.6,
         {"语气": "轻，几乎不表态", "口头禅": ["……"], "禁用词": ["我保证"]}),
        ("c6", "天枢", ["神使天枢"], 4300, 0.5,
         {"语气": "无起伏，像念判词", "口头禅": ["依律"], "禁用词": ["也许"]}),
    ]
    for cid, name, al, first, imp, voice in chars:
        c.add_entity(CN.Entity(id=cid, name=name, kind="character",
                               aliases=al, voice=voice,
                               first_appear=first, importance=imp))

    # 不可变事实
    imm = [
        ("c1", "左眉骨", "一道三厘米的旧疤", 1),
        ("c2", "右手", "缺了半截小指", 1),
        ("c3", "左耳", "耳垂上有个豁口", 180),
        ("c4", "嗓音", "被雷劈过，沙哑", 900),
    ]
    for e, k, v, ch in imm:
        c.add_fact(CN.Fact(e, k, v, ch, immutable=True, source_chapter=ch))

    # 可变事实：带有效期（核心演示点）
    mutable = [
        ("c1", "境界", "炼气初期", 1, 21, 1),
        ("c1", "境界", "炼气中期", 22, 47, 22),
        ("c1", "境界", "筑基初期", 72, 100, 72),
        ("c1", "境界", "金丹初期", 168, 205, 168),
        ("c1", "境界", "化神初期", 441, 496, 441),
        ("c1", "境界", "渡劫初期", 1313, 1405, 1313),
        ("c1", "境界", "灵徒初期", 1601, 1618, 1601),
        ("c1", "境界", "灵尊初期", 1989, 2037, 1989),
        ("c1", "境界", "散仙初期", 3001, 3015, 3001),
        ("c1", "境界", "大罗初期", 3467, 3515, 3467),
        ("c1", "境界", "神人初期", 4201, 4210, 4201),
        ("c1", "境界", "神主后期", 4953, 5000, 4953),
        ("c1", "右臂", "断，接不上了", 2100, 2400, 2100),
        ("c1", "右臂", "已愈，但阴雨天会疼", 2401, None, 2401),
        ("c1", "所在", "青牛镇", 1, 150, 1),
        ("c1", "所在", "灵界·浮屠域", 1601, 3000, 1601),
        ("c1", "所在", "神界·中枢", 4201, None, 4201),
        ("c2", "身份", "青牛镇教书先生", 1, 1200, 1),
        ("c2", "身份", "灵界·浮屠域接引使", 1601, 2800, 1601),
        ("c2", "身份", "神界·叛神", 4201, None, 4201),
        ("c3", "关系", "同门师姐", 180, 1400, 180),
        ("c3", "关系", "道侣", 1401, 2600, 1401),
        ("c3", "关系", "已死（第 2600 章）", 2601, None, 2601),
        ("c4", "状态", "敌对", 900, 2000, 900),
        ("c4", "状态", "盟友", 2001, 3300, 2001),
        ("c4", "状态", "敌对（背叛）", 3301, None, 3301),
    ]
    for e, k, v, vf, vt, sc in mutable:
        c.add_fact(CN.Fact(e, k, v, vf, vt, source_chapter=sc))

    # 数值曲线
    for cid in ("c1", "c2", "c3"):
        c.add_numeric(CN.NumericSeries(cid, "战力", [
            (1, 10), (100, 45), (300, 120), (600, 400), (1200, 1500),
            (1601, 2000), (2000, 6000), (3000, 25000),
            (3001, 26000), (3500, 90000), (4201, 100000),
            (4500, 400000), (5000, 1000000),
        ]))

    # 伏笔：跨 2900 章的承诺
    c.foreshadows = [
        CN.Foreshadow("f1", 100, "沈鹤年右手缺指，他说是年轻时被机器咬的",
                      (3000, 3100), weight=1.0),
        CN.Foreshadow("f2", 450, "母亲留下的铜镜背面刻着一行看不懂的字",
                      (1500, 1600), weight=0.8),
        CN.Foreshadow("f3", 980, "陆无咎说过「界壁不是墙，是筛子」",
                      (3300, 3400), weight=0.9),
        CN.Foreshadow("f4", 2100, "断臂后梦里总有人叫他去西边",
                      (2400, 2500), weight=0.6),
        CN.Foreshadow("f5", 4200, "天枢称林昭为「第二位」",
                      (4900, 4990), weight=1.0),
    ]

    c.timeline = [
        (1, "人界·青牛镇 · 春"),
        (441, "人界·化神 · 三年后"),
        (1601, "灵界·初临 · 界壁压制"),
        (3001, "仙界·散仙 · 百年后"),
        (4201, "神界·神人 · 劫后"),
        (4953, "神界·终局 · 神主"),
    ]
    return c


def main() -> int:
    N = 5000
    cfg = LF.BookConfig(total_chapters=N, words_per_chapter=4000)
    world = WB.build_world(N, title="四界")
    # 用真实的人物体系（境界轨迹 + 声纹），而不是手写假数据
    cast = CH.build_cast(world, N)
    canon = build_canon()
    CH.sync_to_canon(cast, canon)

    # ===== 用真实的四层大纲 =====
    book = OL.build_outline(world, cast, N, cfg.words_per_chapter)

    tree = LF.OutlineTree(cfg)
    tree.book = LF.OutlineNode(
        level="book", index=1, title="四界",
        goal="凡人林昭从青牛镇走出，历经四界，最终成为神主。",
        start_chapter=1, end_chapter=N)
    for v in range(1, 101):
        s = (v - 1) * cfg.chapters_per_volume + 1
        e = min(v * cfg.chapters_per_volume, N)
        tree.volumes[v] = LF.OutlineNode(
            level="volume", index=v, title=f"第{v}卷",
            goal=f"卷目标{v}", start_chapter=s, end_chapter=e,
            characters=["c1", "c2"])
        if v <= 3:
            for a in range(1, cfg.arcs_per_volume + 1):
                s2 = s + (a - 1) * cfg.chapters_per_arc
                tree.arcs[(v, a)] = LF.OutlineNode(
                    level="arc", index=a, title=f"第{v}卷第{a}弧",
                    goal=f"弧目标{v}-{a}", start_chapter=s2,
                    end_chapter=min(s2 + cfg.chapters_per_arc - 1, N),
                    characters=["c1", "c2"])
    for ch in (1, 2, 3, 500, 1601, 2100, 2400, 2500, 3001, 4201, 4999, 5000):
        tree.chapters[ch] = LF.OutlineNode(
            level="chapter", index=ch, title=f"第{ch}章",
            goal=f"第{ch}章目标", beats=["事件一", "事件二", "事件三"],
            characters=["c1", "c2"],
            ends_with="他关上了门。")

    # 抽样：每个探测章的注入内容
    ctx = LF.ContextBuilder(canon, tree, cfg, world=world)
    ctx.style = P.style_contract()

    probes = [1, 21, 100, 500, 1405, 1601, 2100, 2400, 2500,
              3001, 3467, 4201, 4500, 4953, 4999]
    probe_data = []
    for ch in probes:
        lv = world.level_at(ch)
        realm = world.realm_at(ch)
        state = canon.state_at("c1", ch)
        state2 = canon.state_at("c2", ch)
        state3 = canon.state_at("c3", ch)
        due = [f for f in canon.due_foreshadows(ch, 20)]
        od = [f for f in canon.overdue_foreshadows(ch)]
        block = ctx.build(ch, "他关上了门。门外有人在等。", ["c1", "c2", "c3"])
        # 当章在场角色 + 各自境界
        cast_now = []
        for cc in cast.characters:
            if cc.first_appear > ch:
                continue
            if cc.last_appear is not None and ch > cc.last_appear:
                continue
            cast_now.append({
                "id": cc.id, "name": cc.name, "role": cc.role,
                "level": CH.level_name(world, cc.level_at(ch)),
                "level_index": cc.level_at(ch),
                "voice": cc.voice,
            })
        cast_now.sort(key=lambda x: -x["level_index"])
        chn = book.chapter(ch)
        vol = book.volume_of(ch)
        arc = book.arc_of(ch)
        act = next((a for a in book.acts if a["start"] <= ch <= a["end"]),
                   book.acts[0])
        probe_data.append({
            "cast_now": cast_now,
            "chapter_outline": {
                "no": chn.no, "title": chn.title, "goal": chn.goal,
                "level": chn.level, "words": chn.words,
                "ends_with": chn.ends_with, "turn": chn.turn,
                "beats": [{"text": b.text, "kind": b.kind}
                           for b in chn.beats],
            } if chn else None,
            "volume": {"no": vol.no, "name": vol.name,
                        "goal": vol.goal, "escalates": vol.escalates,
                        "start": vol.start, "end": vol.end} if vol else None,
            "arc": {"no": arc.no, "name": arc.name, "goal": arc.goal,
                     "escalates": arc.escalates,
                     "start": arc.start, "end": arc.end} if arc else None,
            "act": {"no": act["no"], "name": act["name"],
                     "conflict": act["conflict"],
                     "irreversible": act["irreversible"],
                     "escalates": act["escalates"]},
            "chapter": ch,
            "realm": realm["name"] if realm else "",
            "level": lv.name if lv else "",
            "level_span": f"{lv.start_chapter}~{lv.end_chapter}" if lv else "",
            "power": round(world.power_at(ch), 1),
            "rank": lv.rank if lv else 0,
            "state_c1": state, "state_c2": state2, "state_c3": state3,
            "due_foreshadow": [{"id": f.id, "content": f.content,
                                "planted": f.planted_in,
                                "window": list(f.payoff_window)} for f in due],
            "overdue": [{"id": f.id, "content": f.content,
                         "planted": f.planted_in} for f in od],
            "inject_chars": len(block),
            "inject_block": block,
        })

    # 全 108 阶曲线（画图用）
    level_curve = [
        {"i": lv.index, "name": lv.name, "realm": lv.realm,
         "s": lv.start_chapter, "e": lv.end_chapter,
         "power": lv.power, "rank": lv.rank, "chapters": lv.chapters}
        for lv in world.levels
    ]

    # 事实时间线（画甘特图用）
    fact_rows = []
    for f in canon.facts:
        fact_rows.append({
            "entity": f.entity, "key": f.key, "value": f.value,
            "from": f.valid_from, "to": f.valid_to,
            "immutable": f.immutable,
        })

    entities = [
        {"id": e.id, "name": e.name, "aliases": e.aliases,
         "voice": e.voice, "first": e.first_appear,
         "importance": e.importance}
        for e in canon.entities.values()
    ]

    foreshadow_rows = [
        {"id": f.id, "content": f.content, "planted": f.planted_in,
         "lo": f.payoff_window[0], "hi": f.payoff_window[1],
         "weight": f.weight}
        for f in canon.foreshadows
    ]

    payload = {
        "total_chapters": N,
        "words_per_chapter": 4000,
        "world": {
            "realms": [{"name": r["name"], "alias": r["alias"],
                        "start": r["start"], "end": r["end"],
                        "essence": r["essence"],
                        "levels": r["levels"],
                        "power_start": r["power_start"],
                        "power_end": r["power_end"]}
                       for r in world.realms],
            "levels": level_curve,
            "rules": world.rules,
            "spirit_roots": world.spirit_roots,
            "artifact_tiers": world.artifact_tiers,
            "pill_tiers": world.pill_tiers,
            "tribulations": world.tribulations,
        },
        "canon": {
            "entities": entities,
            "facts": fact_rows,
            "foreshadows": foreshadow_rows,
            "rules": canon.rules,
            "timeline": canon.timeline,
        },
        "cast": [
            {"id": c.id, "name": c.name, "aliases": c.aliases,
             "role": c.role, "gender": c.gender,
             "spirit_root": c.spirit_root, "origin": c.origin,
             "first_appear": c.first_appear,
             "last_appear": c.last_appear,
             "importance": c.importance, "voice": c.voice,
             "arc": c.arc, "relationships": c.relationships,
             "immutable": c.immutable,
             "milestones": [{"chapter": m.chapter,
                              "level_index": m.level_index,
                              "level": CH.level_name(world, m.level_index),
                              "note": m.note}
                             for m in sorted(c.milestones,
                                             key=lambda x: x.chapter)]}
            for c in cast.characters
        ],
        "book": {
            "title": book.title, "logline": book.logline,
            "spine": book.spine, "acts": book.acts,
            "milestones": book.milestones,
            "stats": {
                "volumes": len(book.volumes),
                "arcs": sum(len(v.arcs) for v in book.volumes),
                "chapters": len(book.all_chapters()),
            },
        },
        "probes": probe_data,
        "stats": {
            "levels": len(world.levels),
            "entities": len(canon.entities),
            "cast": len(cast.characters),
            "facts": len(canon.facts),
            "foreshadows": len(canon.foreshadows),
        },
    }

    out = HERE.parent / "out" / "dashboard_data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"已导出 {out}")
    print(f"  章节 {N}｜阶数 {len(world.levels)}｜实体 {len(canon.entities)}"
          f"｜事实 {len(canon.facts)}｜伏笔 {len(canon.foreshadows)}")
    print(f"  探测章 {len(probe_data)} 个，注入块大小 "
          f"{min(p['inject_chars'] for p in probe_data)}~"
          f"{max(p['inject_chars'] for p in probe_data)} 字符")
    return 0


if __name__ == "__main__":
    sys.exit(main())
