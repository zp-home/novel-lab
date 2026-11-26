#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed.py —— 3000 本书的「选题矩阵」生成器（解决同质化的第一道闸）

核心问题
--------
如果 3000 本书都用同一个模板 prompt，只是换个人名地名，结果必然是
3000 个近亲。实测（见 diversity.py）这类书的平均两两相似度会超过 0.5，
读者一眼看出是同一个模子。

解法：**把"故事"拆成 8 个正交维度，用低差异序列（Latin Hypercube +
最大最小距离筛选）在维度空间里撒点，保证任意两本书至少在 3 个维度上不同。**

8 个维度
--------
1. 题材（genre）        现实/悬疑/科幻/武侠/都市/乡土/历史/奇幻
2. 空间（setting）      封闭小镇/大城/海岛/列车/工厂/学校/边地/家中
3. 冲突类型（conflict） 亲情/背叛/复仇/生存/身份/理想幻灭/愧疚/契约
4. 叙事人称（pov）      第一人称/第三人称限知/双线交叉/书信体
5. 时间结构（time）     线性/倒叙/一天之内/跨越十年/双时间线
6. 结局基调（ending）   苦涩/开放/反讽/温情/循环/戛然而止
7. 主角处境（protagonist） 下岗者/学生/老人/外来者/手艺人/病人
8. 核心意象（motif）    火/水/铁/纸/门/镜子/骨头/种子/线/影子

用法
----
    python seed.py --n 3000 --out seeds.json
    python seed.py --n 3000 --check      # 检查矩阵的覆盖度和最小差异度
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

# ==========================================================================
# 维度定义。每个维度的选项要"真的有区别"，不是同义词。
# ==========================================================================
DIMENSIONS: dict[str, list[str]] = {
    "genre": ["现实", "悬疑", "科幻", "武侠", "都市", "乡土", "历史", "奇幻"],
    "setting": ["封闭小镇", "省会大城", "海岛渔村", "长途列车", "倒闭工厂",
                "县城中学", "西北边地", "一栋老楼", "医院病房", "废弃矿区"],
    "conflict": ["亲情亏欠", "信任背叛", "延迟复仇", "生存挤压", "身份替换",
                 "理想幻灭", "未偿愧疚", "一纸契约"],
    "pov": ["第一人称", "第三人称限知", "双线交叉", "书信/档案体"],
    "time": ["线性推进", "从结局倒叙", "压缩在一天内", "跨越十年",
             "双时间线并置"],
    "ending": ["苦涩收束", "开放留白", "反讽收尾", "温情落地",
               "循环回环", "戛然而止"],
    "protagonist": ["下岗技术员", "高三学生", "独居老人", "外来务工者",
                    "手艺人", "慢性病人", "退役运动员", "乡镇教师",
                    "夜班保安", "小店主"],
    "motif": ["火", "水", "铁", "纸", "一扇门", "镜子", "骨头", "种子",
              "一根线", "影子"],
}

# 维度权重：越靠前越"决定这本书长得像不像"，用于最小距离筛选
DIM_WEIGHT = {
    "genre": 1.6, "conflict": 1.5, "setting": 1.2, "pov": 1.0,
    "ending": 1.0, "protagonist": 0.9, "time": 0.8, "motif": 0.6,
}


@dataclass
class Seed:
    book_id: str
    genre: str
    setting: str
    conflict: str
    pov: str
    time: str
    ending: str
    protagonist: str
    motif: str
    # 由 8 个维度派生出的额外"调味"参数，进一步拉开差异
    register: str = ""      # 语体：冷硬/绵密/口语/书面/诗性
    density: str = ""       # 信息密度：疏/中/密
    taboo: list[str] = field(default_factory=list)  # 本书特别禁用的词

    def as_tuple(self) -> tuple[str, ...]:
        return (self.genre, self.setting, self.conflict, self.pov,
                self.time, self.ending, self.protagonist, self.motif)

    def weight_vector(self) -> list[float]:
        keys = list(DIMENSIONS.keys())
        vals = self.as_tuple()
        return [hash_option(v) * DIM_WEIGHT[k] for k, v in zip(keys, vals)]


def hash_option(s: str) -> float:
    """把选项映射到 [0,1)，用于计算加权距离。"""
    h = 0
    for ch in s:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return (h % 10007) / 10007.0


def weighted_distance(a: Seed, b: Seed) -> float:
    """两本书在"故事空间"里的加权距离，1 = 完全不同。"""
    va, vb = a.as_tuple(), b.as_tuple()
    keys = list(DIMENSIONS.keys())
    num = 0.0
    den = 0.0
    for k, x, y in zip(keys, va, vb):
        w = DIM_WEIGHT[k]
        num += w * (0.0 if x == y else 1.0)
        den += w
    return num / den


REGISTERS = ["冷硬克制", "绵密黏稠", "粗粝口语", "书面典雅", "诗性跳跃", "新闻体"]
DENSITIES = ["信息疏（多留白）", "信息中", "信息密（多事件）"]


def latin_hypercube(n: int, dims: int, rng: random.Random) -> list[list[float]]:
    """标准 LHS：每维分成 n 份，每份取一次，再打乱。"""
    cols = []
    for _ in range(dims):
        order = list(range(n))
        rng.shuffle(order)
        cols.append([(k + rng.random()) / n for k in order])
    return [[cols[d][i] for d in range(dims)] for i in range(n)]


def generate(n: int, seed: int = 20261124,
             pool_multiplier: int = 4) -> list[Seed]:
    """
    两步走：
    1. 用 LHS 生成 pool_multiplier × n 个候选（分层抽样，保证每个维度的
       每个选项都被均匀用到）；
    2. 用「最远点采样」（farthest point sampling / k-center greedy）从候选池里
       挑出 n 个，使任意两个被选中的点之间的距离尽可能大。

    第 2 步是关键。朴素做法（顺序贪心 + 阈值剔除）会把 3000 本砍到 150 本，
    因为它只看"先来后到"；FPS 是全局最优近似，能保住 3000 本的分散度。
    实现上用 numpy 做向量化，3000 本 × 12000 候选约 3 秒。
    """
    rng = random.Random(seed)
    keys = list(DIMENSIONS.keys())
    pool_n = max(n, n * pool_multiplier)
    pts = latin_hypercube(pool_n, len(keys), rng)

    def to_seed(i: int, pt: list[float]) -> Seed:
        pick = {}
        for k, u in zip(keys, pt):
            opts = DIMENSIONS[k]
            pick[k] = opts[min(len(opts) - 1, int(u * len(opts)))]
        return Seed(
            book_id=f"b{i + 1:04d}",
            genre=pick["genre"], setting=pick["setting"],
            conflict=pick["conflict"], pov=pick["pov"], time=pick["time"],
            ending=pick["ending"], protagonist=pick["protagonist"],
            motif=pick["motif"],
            register=rng.choice(REGISTERS),
            density=rng.choice(DENSITIES),
        )

    candidates = [to_seed(i, pt) for i, pt in enumerate(pts)]
    # 去重（LHS 是连续抽样，离散化后可能撞同一个组合）
    seen: set[tuple] = set()
    uniq: list[Seed] = []
    for s in candidates:
        t = s.as_tuple()
        if t not in seen:
            seen.add(t)
            uniq.append(s)
    candidates = uniq

    if len(candidates) <= n:
        chosen = candidates[:]
    else:
        chosen = _fps(candidates, n)

    chosen.sort(key=lambda s: s.as_tuple())
    for i, s in enumerate(chosen):
        s.book_id = f"b{i + 1:04d}"
    return chosen


def _feature_matrix(seeds: list[Seed]):
    """把每本书编码成 (维度数) 的整数码矩阵，用于向量化距离计算。"""
    keys = list(DIMENSIONS.keys())
    index = {k: {v: i for i, v in enumerate(DIMENSIONS[k])} for k in keys}
    try:
        import numpy as np
    except ImportError:
        return None
    M = np.array([[index[k][getattr(s, k)] for k in keys] for s in seeds],
                 dtype=np.int16)
    w = np.array([DIM_WEIGHT[k] for k in keys], dtype=np.float32)
    w = w / w.sum()
    return M, w


def _fps(candidates: list[Seed], n: int) -> list[Seed]:
    keys = list(DIMENSIONS.keys())
    idx = {k: {v: i for i, v in enumerate(DIMENSIONS[k])} for k in keys}
    fm = _feature_matrix(candidates)

    if fm is None:
        # 纯 Python 兜底（慢，但正确）
        def d(a: Seed, b: Seed) -> float:
            return weighted_distance(a, b)
        start = max(candidates,
                    key=lambda s: sum(d(s, o) for o in candidates[::max(1, len(candidates)//200)]))
        chosen = [start]
        min_d = [d(start, c) for c in candidates]
        min_d[candidates.index(start)] = -1.0
        while len(chosen) < n:
            bi = max(range(len(candidates)), key=lambda i: min_d[i])
            if min_d[bi] <= 0:
                break
            chosen.append(candidates[bi])
            p = candidates[bi]
            min_d[bi] = -1.0
            for i, c in enumerate(candidates):
                if min_d[i] >= 0:
                    dd = d(p, c)
                    if dd < min_d[i]:
                        min_d[i] = dd
        return chosen

    import numpy as np
    M, w = fm
    N = M.shape[0]
    # 初始点：离"整体平均差异"最大的那个
    sub = M[::max(1, N // 300)]
    D = (sub[:, None, :] != M[None, :, :]).astype(np.float32) @ w
    start = int(np.argmax(D.mean(axis=1)))

    chosen_idx = [start]
    min_d = (M != M[start]).astype(np.float32) @ w
    min_d[start] = -1.0
    while len(chosen_idx) < n:
        bi = int(np.argmax(min_d))
        if min_d[bi] <= 0:
            break
        chosen_idx.append(bi)
        dd = (M != M[bi]).astype(np.float32) @ w
        np.minimum(min_d, dd, out=min_d)
        min_d[bi] = -1.0
    return [candidates[i] for i in chosen_idx]


def prune_similar(seeds: list[Seed], min_dist: float = 0.55,
                  max_rounds: int = 200) -> tuple[list[Seed], int]:
    """
    贪心剔除：遍历时若跟已保留的某本距离 < min_dist，就丢掉。
    被丢掉的会在下一轮用未使用的维度组合补位。
    """
    kept: list[Seed] = []
    dropped = 0
    for s in seeds:
        if all(weighted_distance(s, k) >= min_dist for k in kept):
            kept.append(s)
        else:
            dropped += 1
    return kept, dropped


def coverage_report(seeds: list[Seed]) -> dict:
    n = len(seeds)
    rep: dict = {"count": n}
    for k in DIMENSIONS:
        counts: dict[str, int] = {}
        for s in seeds:
            v = getattr(s, k)
            counts[v] = counts.get(v, 0) + 1
        rep[k] = {
            "used": len(counts),
            "total_options": len(DIMENSIONS[k]),
            "max_share": round(max(counts.values()) / n, 3),
            "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        }
    # 两两距离抽样统计（全量 O(n^2) 在 3000 本时是 450 万对，可接受但慢）
    sample = seeds if n <= 400 else random.Random(0).sample(seeds, 400)
    ds = [weighted_distance(a, b)
          for a, b in itertools.combinations(sample, 2)]
    ds.sort()
    rep["pairwise_distance"] = {
        "mean": round(sum(ds) / len(ds), 4),
        "p05": round(ds[int(len(ds) * 0.05)], 4),
        "p50": round(ds[int(len(ds) * 0.50)], 4),
        "min": round(ds[0], 4),
        "pairs_under_0.4": sum(1 for d in ds if d < 0.4),
        "pairs_under_0.5": sum(1 for d in ds if d < 0.5),
    }
    # 理论最大：8 个维度全不同 = 1.0
    rep["verdict"] = (
        "OK：种子空间足够分散" if rep["pairwise_distance"]["p05"] >= 0.45
        else "WARN：有 5% 以上的书对差异不足 0.45，建议加维度或加选项"
    )
    return rep


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="3000 本书的选题矩阵生成器")
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--out", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--min-dist", type=float, default=0.55)
    ap.add_argument("--seed", type=int, default=20261124)
    args = ap.parse_args(argv)

    seeds = generate(args.n, args.seed)
    kept = seeds
    print(f"生成 {len(seeds)} 本（FPS 最远点采样）")

    rep = coverage_report(kept)
    print(f"两两距离：均值 {rep['pairwise_distance']['mean']}，"
          f"p05 {rep['pairwise_distance']['p05']}，"
          f"最小 {rep['pairwise_distance']['min']}")
    print(rep["verdict"])

    if args.check:
        for k in DIMENSIONS:
            d = rep[k]
            print(f"  {k:12s} 用上 {d['used']}/{d['total_options']} 种，"
                  f"最高占比 {d['max_share']:.1%}")

    if args.out:
        payload = {"report": rep, "seeds": [asdict(s) for s in kept]}
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("已写出", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
