#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diversity.py —— 跨书同质化检测（3000 本规模的头号杀手）

问题
----
同一套 prompt 采样 3000 次，会得到 3000 本"长相相似"的书：
同一个转折、同一种开头、同一批意象、同一套句式。单本检测（ai_flavor.py）
看不出来，因为每一本单独看都合格。**只有横向比对才能发现模式坍缩。**

做法
----
1. 每本书抽 3 个指纹：
   - 字符 4-gram 的 MinHash 签名（128 维）——抓"逐句相似"
   - 意象/名词集合的 Jaccard——抓"用同一批词写不同的书"
   - 结构指纹（场景功能序列、情绪曲线拐点位置）——抓"同一套骨架"
2. 两两比对，输出相似度最高的 top-N 对，以及"这本书跟全库的平均相似度"。
3. 阈值：平均相似度 > 0.35 说明 prompt 空间太窄，必须换种子策略。

用法
----
    python diversity.py corpus_dir --json report.json --md report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HAN_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_SPLIT_RE = re.compile(r"[。！？!?…]+")

# 结构功能词：用来抽"场景功能序列"，判断两本书是不是同一套骨架
FUNC_LEXICON = {
    "开场": ["天", "早", "醒", "车", "门", "站", "走"],
    "冲突": ["争", "吵", "骂", "打", "拒", "逼", "抢", "拦"],
    "揭示": ["原来", "才知", "发现", "明白", "真相", "其实"],
    "转折": ["突然", "却", "没想到", "不料", "谁知"],
    "代价": ["血", "伤", "死", "痛", "赔", "卖", "丢", "失"],
    "收束": ["走", "离开", "回", "关", "熄", "合", "放"],
}


# ---------------------------------------------------------------- MinHash
def _ngrams(chars: list[str], n: int = 4) -> list[str]:
    return [("".join(chars[i:i + n])) for i in range(max(0, len(chars) - n + 1))]


def _h64(s: str, seed: int) -> int:
    d = hashlib.blake2b((str(seed) + "|" + s).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(d, "big")


class MinHash:
    def __init__(self, num_perm: int = 128):
        self.num_perm = num_perm

    def signature(self, text: str) -> list[int]:
        chars = HAN_RE.findall(text)
        grams = set(_ngrams(chars, 4))
        if not grams:
            return [0] * self.num_perm
        sig = []
        for seed in range(self.num_perm):
            sig.append(min(_h64(g, seed) for g in grams))
        return sig

    @staticmethod
    def jaccard(a: list[int], b: list[int]) -> float:
        if len(a) != len(b):
            return 0.0
        return sum(1 for x, y in zip(a, b) if x == y) / len(a)


# ---------------------------------------------------------------- 特征
def imagery_set(text: str) -> set[str]:
    """意象词集合：抽 2-4 字的名词性片段，粗但够用。"""
    chars = HAN_RE.findall(text)
    out: set[str] = set()
    for i in range(len(chars) - 1):
        out.add(chars[i] + chars[i + 1])
    return out


def structure_fingerprint(text: str) -> list[str]:
    """把文本按 1/8 切段，每段判一个主导功能，得到 8 位功能序列。"""
    sents = [s for s in SENT_SPLIT_RE.split(text) if HAN_RE.search(s)]
    if not sents:
        return ["空"] * 8
    k = max(1, len(sents) // 8)
    seq = []
    for i in range(0, len(sents), k):
        chunk = "".join(sents[i:i + k])
        best, best_n = "平", 0
        for func, words in FUNC_LEXICON.items():
            n = sum(chunk.count(w) for w in words)
            if n > best_n:
                best, best_n = func, n
        seq.append(best if best_n else "平")
        if len(seq) == 8:
            break
    while len(seq) < 8:
        seq.append("平")
    return seq


def opening_signature(text: str, n: int = 60) -> str:
    return "".join(HAN_RE.findall(text)[:n])


@dataclass
class Fingerprint:
    name: str
    sig: list[int]
    imagery: set[str]
    structure: list[str]
    opening: str
    chars: int

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "chars": self.chars,
            "structure": self.structure,
            "opening": self.opening,
            "imagery_size": len(self.imagery),
            # 签名只存摘要，避免报告过大
            "sig_digest": hashlib.blake2b(
                json.dumps(self.sig).encode(), digest_size=8).hexdigest(),
        }


def build(text: str, name: str) -> Fingerprint:
    mh = MinHash(128)
    return Fingerprint(
        name=name,
        sig=mh.signature(text),
        imagery=imagery_set(text),
        structure=structure_fingerprint(text),
        opening=opening_signature(text),
        chars=len(HAN_RE.findall(text)),
    )


def pair_similarity(a: Fingerprint, b: Fingerprint) -> dict:
    mh = MinHash.jaccard(a.sig, b.sig)
    inter = len(a.imagery & b.imagery)
    union = len(a.imagery | b.imagery) or 1
    jac = inter / union
    # 结构相似：功能序列完全一致的位数
    st = sum(1 for x, y in zip(a.structure, b.structure) if x == y) / 8.0
    op = 0.0
    if a.opening and b.opening:
        common = 0
        for x, y in zip(a.opening, b.opening):
            if x != y:
                break
            common += 1
        op = common / max(len(a.opening), len(b.opening))
    combined = 0.45 * mh + 0.30 * jac + 0.15 * st + 0.10 * op
    return {"minhash": round(mh, 4), "imagery_jaccard": round(jac, 4),
            "structure": round(st, 4), "opening": round(op, 4),
            "combined": round(combined, 4)}


def analyze_corpus(paths: list[Path], top_n: int = 20,
                   root: Path | None = None) -> dict:
    fps = []
    for p in paths:
        text = p.read_text(encoding="utf-8-sig")
        if len(HAN_RE.findall(text)) < 200:
            continue
        # 名字用相对路径，避免所有书都叫 "final" 撞名
        if root is not None:
            try:
                name = str(p.relative_to(root)).replace("\\", "/")
            except ValueError:
                name = p.stem
        else:
            name = p.stem
        name = name.replace("/final.txt", "")
        fps.append(build(text, name))
    n = len(fps)
    if n < 2:
        raise SystemExit("语料少于 2 篇，无法横向比对")

    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            s = pair_similarity(fps[i], fps[j])
            pairs.append({"a": fps[i].name, "b": fps[j].name, **s})
    pairs.sort(key=lambda x: -x["combined"])

    per_book_avg = {}
    for i, f in enumerate(fps):
        sims = [pair_similarity(f, g)["combined"]
                for j, g in enumerate(fps) if j != i]
        per_book_avg[f.name] = round(sum(sims) / len(sims), 4) if sims else 0.0

    mean_pair = sum(p["combined"] for p in pairs) / len(pairs)
    structure_counts: dict[str, int] = {}
    for f in fps:
        k = "".join(f.structure)
        structure_counts[k] = structure_counts.get(k, 0) + 1
    top_struct = sorted(structure_counts.items(), key=lambda kv: -kv[1])[:5]

    # 判级
    if mean_pair < 0.20:
        verdict = "OK：库内同质化低"
    elif mean_pair < 0.35:
        verdict = "WARN：开始坍缩，建议扩充种子池"
    else:
        verdict = "BAD：严重模式坍缩，同批书互相可替代"

    return {
        "books": n,
        "mean_pair_similarity": round(mean_pair, 4),
        "verdict": verdict,
        "top_pairs": pairs[:top_n],
        "most_typical_books": sorted(per_book_avg.items(), key=lambda kv: -kv[1])[:10],
        "most_distinct_books": sorted(per_book_avg.items(), key=lambda kv: kv[1])[:10],
        "structure_collapse": [
            {"structure": k, "count": v, "share": round(v / n, 3)}
            for k, v in top_struct
        ],
        "fingerprints": [f.to_json() for f in fps],
    }


def render_md(r: dict) -> str:
    out = ["# 跨书同质化报告", ""]
    out.append(f"- 样本：**{r['books']}** 本")
    out.append(f"- 平均两两相似度：**{r['mean_pair_similarity']}**")
    out.append(f"- 判定：**{r['verdict']}**")
    out.append("")
    out.append("## 最相似的 20 对")
    out.append("")
    out.append("| A | B | 合计 | 4-gram | 意象 | 结构 | 开头 |")
    out.append("|---|---|---|---|---|---|---|")
    for p in r["top_pairs"]:
        out.append(f"| {p['a']} | {p['b']} | {p['combined']} | {p['minhash']} | "
                   f"{p['imagery_jaccard']} | {p['structure']} | {p['opening']} |")
    out.append("")
    out.append("## 结构坍缩（同一套骨架的书有多少）")
    out.append("")
    for s in r["structure_collapse"]:
        out.append(f"- `{s['structure']}` × {s['count']} 本（占 {s['share']:.1%}）")
    out.append("")
    out.append("## 最典型的书（跟全库最像，优先重写）")
    out.append("")
    for name, v in r["most_typical_books"]:
        out.append(f"- {name}: {v}")
    out.append("")
    out.append("## 最有个性的书（可作风格种子）")
    out.append("")
    for name, v in r["most_distinct_books"]:
        out.append(f"- {name}: {v}")
    return "\n".join(out)


def collect(paths: list[Path]) -> list[Path]:
    """
    从目录里挑出"每本书一个文件"。
    如果存在 final.txt（流水线产物），只比 final.txt——
    否则会把同一本书的第 1/2/3 章当成三本书互相比，相似度虚高。
    """
    finals = [p for p in paths if p.name == "final.txt"]
    if finals:
        return sorted(finals)
    return sorted(paths)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="跨书同质化检测")
    ap.add_argument("corpus_dir")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args(argv)
    d = Path(args.corpus_dir)
    paths = collect(sorted(d.rglob("*.txt")))
    r = analyze_corpus(paths, args.top, root=d)
    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render_md(r), encoding="utf-8")
    print(f"{r['books']} 本，平均相似度 {r['mean_pair_similarity']}，{r['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
