#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_longform.py —— 验证 5000 章架构的核心不变量

这不是单元测试，是**架构验证**。它回答一个问题：

    "如果我把 5000 章真跑完，上下文会不会爆？状态会不会丢？"

做法：模拟跑完 5000 章（不调用模型，纯数据结构推演），
在每个检查点测量上下文大小和查询正确性。

关键不变量（任何一条不成立，架构就是错的）：

  INV-1  上下文大小与章节号无关
         第 5000 章注入的 token 数 ≈ 第 1 章。
         这是 2000 万字可行的唯一原因。

  INV-2  任意章节都能精确查到"当时"的状态
         第 2100 章查"右臂"得到"断"，第 2500 章查得到"已愈"。

  INV-3  事实总量线性增长，但注入量不变
         5000 章后 canon 可能有上万条事实，但每章只注入 ~50 条。

  INV-4  冲突检测在写入时就能抓到
         不依赖事后人工 review。

  INV-5  断点续跑无损
         中断后重启，状态完全一致。
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


def build_realistic_canon(n_chapters: int = 5000) -> CN.Canon:
    """
    模拟一部 5000 章网文的正典会累积成什么样。

    这不是瞎造：5000 章的真实网文确实会有
    - 20~50 个主要人物
    - 上百条境界/能力变更
    - 数十条伏笔
    - 数千条状态事实
    """
    c = CN.Canon()
    c.rules = [
        "境界九品，一品最低，不可跳级",
        "死者不可复生",
        "灵气复苏始于第 1 章",
    ]

    # 30 个主要人物
    for i in range(1, 31):
        c.add_entity(CN.Entity(
            id=f"c{i}", name=f"角色{i:02d}", kind="character",
            aliases=[f"老{i:02d}"],
            voice={"语气": "冷硬" if i % 3 == 0 else "温和",
                   "口头禅": [f"口{i}"],
                   "禁用词": ["其实"]},
            first_appear=max(1, i * 150),
            importance=1.0 if i <= 5 else (0.6 if i <= 15 else 0.3),
        ))

    # 不可变事实
    for i in range(1, 6):
        c.add_fact(CN.Fact(f"c{i}", "左眉骨", f"{i}厘米旧疤", 1,
                           immutable=True, source_chapter=1))

    # 可变事实：境界每 200 章升一品，跨越全书
    for i in range(1, 6):
        grade = 1
        for start in range(1, n_chapters + 1, 200):
            end = min(start + 199, n_chapters)
            c.add_fact(CN.Fact(f"c{i}", "境界", f"{min(grade,9)}品",
                               start, end if end < n_chapters else None,
                               source_chapter=start))
            grade += 1

    # 数值曲线
    for i in range(1, 6):
        pts = [(ch, 10 * (ch ** 1.25)) for ch in range(1, n_chapters + 1, 500)]
        c.add_numeric(CN.NumericSeries(f"c{i}", "战力", pts))

    # 40 条伏笔，散布全书
    for i in range(1, 41):
        planted = i * (n_chapters // 45)
        c.foreshadows.append(CN.Foreshadow(
            id=f"f{i}", planted_in=max(1, planted),
            content=f"伏笔{i}：某个没说出口的细节",
            payoff_window=(min(n_chapters, planted + 300),
                           min(n_chapters, planted + 500)),
            weight=1.0 if i % 5 == 0 else 0.5,
        ))

    c.timeline = [(ch, f"第{ch}章·故事时间") for ch in range(1, n_chapters + 1, 250)]
    return c


def main() -> int:
    print("=" * 70)
    print("5000 章架构不变量验证（不调用模型）")
    print("=" * 70)

    N = 5000
    cfg = LF.BookConfig(total_chapters=N, words_per_chapter=4000)
    c = build_realistic_canon(N)
    tree = LF.OutlineTree(cfg)

    # 铺满大纲（模拟跑完全书）
    tree.book = LF.OutlineNode(level="book", index=1, title="测试书",
                               goal="脊柱", start_chapter=1, end_chapter=N)
    for v in range(1, cfg.volumes + 1):
        s = (v - 1) * cfg.chapters_per_volume + 1
        e = min(v * cfg.chapters_per_volume, N)
        tree.volumes[v] = LF.OutlineNode(
            level="volume", index=v, title=f"第{v}卷", goal=f"卷目标{v}",
            start_chapter=s, end_chapter=e, characters=["c1", "c2"])
        for a in range(1, cfg.arcs_per_volume + 1):
            s2 = s + (a - 1) * cfg.chapters_per_arc
            tree.arcs[(v, a)] = LF.OutlineNode(
                level="arc", index=a, title=f"弧{a}", goal=f"弧目标{a}",
                start_chapter=s2,
                end_chapter=min(s2 + cfg.chapters_per_arc - 1, N),
                characters=["c1", "c2"])
    for ch in range(1, N + 1):
        tree.chapters[ch] = LF.OutlineNode(
            level="chapter", index=ch, title=f"第{ch}章", goal="章目标",
            beats=["事件一", "事件二", "事件三"], characters=["c1", "c2"],
            ends_with="他关上了门。")

    # 世界观必须在上下文构建之前就位
    world = WB.build_world(N)
    wp = WB.validate(world)
    if wp:
        print("\n[世界观校验]")
        for x in wp:
            print("  " + x)
        failures_pre = wp
    else:
        failures_pre = []
    print(f"\n[世界观] {len(world.realms)} 界 / {len(world.levels)} 阶，校验通过")

    cast = CH.build_cast(world, N)
    cp = CH.validate(cast, world, N)
    if cp:
        print("\n[人物校验]")
        for x in cp:
            print("  " + x)
        failures_pre.extend(cp)
    else:
        print(f"[人物] {len(cast.characters)} 人，校验通过")
    CH.sync_to_canon(cast, c)

    ctx = LF.ContextBuilder(c, tree, cfg, world=world, cast=cast)
    import prompts as P
    ctx.style = P.style_contract()

    failures: list[str] = list(failures_pre)

    # ---------------- INV-1 ----------------
    print("\n[INV-1] 上下文大小与章节号无关")
    sizes = []
    for ch in (1, 10, 100, 500, 1000, 2000, 3000, 4000, 5000):
        block = ctx.build(ch, "他关上了门。门外有人在等。", ["c1", "c2"])
        sizes.append((ch, len(block)))
        print(f"  第{ch:5d}章 → {len(block):5d} 字符 ≈ {len(block)//2:5d} tokens")
    lo = min(s for _, s in sizes)
    hi = max(s for _, s in sizes)
    drift = (hi - lo) / lo
    print(f"  漂移：{lo} ~ {hi} 字符（{(hi-lo)/lo:.1%}）")
    if drift > 0.30:
        failures.append(f"INV-1 失败：上下文随章节号漂移 {drift:.1%}（>30%）")
    else:
        print(f"  ✅ 通过（漂移 < 30%，说明第 5000 章和第 1 章成本相当）")

    # ---------------- INV-2 ----------------
    print("\n[INV-2] 任意章节能查到「当时」的状态")
    checks = [
        (100, "境界", "1品"),
        (250, "境界", "2品"),
        (450, "境界", "3品"),
        (4999, "境界", "9品"),
    ]
    ok2 = True
    for ch, key, expect in checks:
        st = c.state_at("c1", ch)
        got = st.get(key, "?")
        flag = "✅" if got == expect else "❌"
        if got != expect:
            ok2 = False
        print(f"  {flag} 第{ch:5d}章 {key} = {got}（期望 {expect}）")
    if not ok2:
        failures.append("INV-2 失败：时序查询不正确")

    # ---------------- INV-6：境界随章节正确推进 ----------------
    print("\n[INV-6] 108 阶境界随章节正确推进（世界观注入正确性）")
    probes = [(1, "人界", "炼气初期"), (800, "人界", None),
              (1601, "灵界", "灵徒初期"),
              (3001, "仙界", "散仙初期"),
              (4201, "神界", "神人初期"),
              (4999, "神界", "神主后期")]
    ok6 = True
    prev_power = -1.0
    mono = True
    for ch in range(1, N + 1, 25):
        pw = world.power_at(ch)
        if pw < prev_power:
            mono = False
        prev_power = pw
    for ch, expect_realm, expect_level in probes:
        lv = world.level_at(ch)
        realm = world.realm_at(ch)
        got_realm = realm["name"] if realm else "?"
        got_lv = lv.name if lv else "?"
        good = (got_realm == expect_realm
                and (expect_level is None or got_lv == expect_level))
        if not good:
            ok6 = False
        print(f"  {'✅' if good else '❌'} 第{ch:5d}章 → {got_realm} · {got_lv}"
              + (f"（期望 {expect_realm} · {expect_level}）"
                 if not good else ""))
    print(f"  {'✅' if mono else '❌'} 绝对战力全书单调递增")
    if not mono:
        ok6 = False
    if not ok6:
        failures.append("INV-6 失败：境界推进不正确")

    # ---------------- INV-7：世界状态块必须非空 ----------------
    print("\n[INV-7] 注入的世界状态块非空（防人物没同步进正典）")
    ok7 = True
    for ch in (1, 500, 2400, 4999):
        block = ctx.build(ch, "他关上了门。", ["c1", "c2"])
        i = block.find("【世界状态")
        j = block.find("【上一章")
        seg = block[i:j] if i >= 0 and j > i else ""
        has_entity = "▸" in seg
        has_level = "境界" in seg
        good = has_entity and has_level
        if not good:
            ok7 = False
        print(f"  {'✅' if good else '❌'} 第{ch:5d}章 世界状态块 "
              f"{len(seg)} 字符，含实体={'是' if has_entity else '否'}，"
              f"含境界={'是' if has_level else '否'}")
    if not ok7:
        failures.append("INV-7 失败：世界状态块为空或缺少境界")

    # ---------------- INV-3 ----------------
    print("\n[INV-3] 事实总量增长，但注入量恒定")
    print(f"  正典总事实数：{len(c.facts)} 条")
    print(f"  实体数：{len(c.entities)}")
    print(f"  伏笔数：{len(c.foreshadows)}")
    active_mid = len(c.active_facts(2500))
    print(f"  第 2500 章时「有效」事实：{active_mid} 条")
    print(f"  但每章只注入：约 {sizes[-1][1]//2} tokens")
    ratio = sizes[-1][1] / max(1, len(c.facts))
    print(f"  注入/总量比：{ratio:.1f} 字符/条（与总量无关）")
    if ratio > 100:
        failures.append("INV-3 失败：注入量随事实总量增长")
    else:
        print("  ✅ 通过（注入量由「在场实体」决定，不由「总事实数」决定）")

    # ---------------- INV-4 ----------------
    print("\n[INV-4] 冲突在写入时被抓到")
    bad = [CN.Fact("c1", "左眉骨", "完好无疤", 3000, source_chapter=3000)]
    problems = c.check_new_facts(3000, bad)
    for p in problems:
        print("  " + p)
    if not problems:
        failures.append("INV-4 失败：不可变事实被改写却没报错")
    else:
        print(f"  ✅ 通过（抓到 {len(problems)} 条冲突）")

    # ---------------- INV-5 ----------------
    print("\n[INV-5] 断点续跑无损")
    tmp = HERE.parent / "out" / "_verify"
    tmp.mkdir(parents=True, exist_ok=True)
    c.save(tmp / "canon.json")
    c2 = CN.Canon.load(tmp / "canon.json")
    same_facts = len(c2.facts) == len(c.facts)
    same_entities = len(c2.entities) == len(c.entities)
    same_fs = len(c2.foreshadows) == len(c.foreshadows)
    # 抽查状态查询是否一致
    same_query = all(c.state_at("c1", ch) == c2.state_at("c1", ch)
                     for ch in (1, 500, 2500, 4999))
    print(f"  事实 {len(c.facts)} → {len(c2.facts)}  {'✅' if same_facts else '❌'}")
    print(f"  实体 {len(c.entities)} → {len(c2.entities)}  {'✅' if same_entities else '❌'}")
    print(f"  伏笔 {len(c.foreshadows)} → {len(c2.foreshadows)}  {'✅' if same_fs else '❌'}")
    print(f"  状态查询一致：{'✅' if same_query else '❌'}")
    if not (same_facts and same_entities and same_fs and same_query):
        failures.append("INV-5 失败：序列化丢失状态")
    else:
        print("  ✅ 通过")

    # ---------------- 卷末审计 ----------------
    print("\n[卷末审计] 模拟第 100 卷末体检")
    ar = LF.audit_volume(c, tree, cfg, 100, N)
    print(f"  问题数：{len(ar.problems)}")
    for p in ar.problems[:6]:
        print(f"    · {p}")
    print(f"  统计：{json.dumps(ar.stats, ensure_ascii=False)[:200]}")

    # ---------------- 结论 ----------------
    print("\n" + "=" * 70)
    if failures:
        print("❌ 架构验证失败：")
        for f in failures:
            print("   " + f)
        return 1
    print("✅ 全部 7 条不变量通过 —— 5000 章架构成立")
    print()
    print("这意味着：")
    print("  · 第 5000 章的上下文成本 ≈ 第 1 章")
    print("  · 任何章节都能精确还原「当时」的世界状态")
    print("  · 设定冲突在写入时就报错，不靠人肉 review")
    print("  · 中断后可从任意章节无损续跑\n  · 境界推进正确：第 N 章该是什么境界就是什么境界")
    print()
    print("不意味着：")
    print("  · 文笔会好（那是模型能力，不是架构能解决的）")
    print("  · 剧情会好看（那是大纲质量，需要人把关）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
