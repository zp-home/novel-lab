#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
progress.py —— 生成正文进度看板（单文件 HTML，自动刷新）

读取 out/books/*.txt 和 out/outline_full.json，
生成一个可视化页面，显示：
- 进度条（已写/总数）
- 每章字数、质量
- 正文预览
- 与大纲的对应关系（幕/卷/弧/章）
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import outline as OL

HAN = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]{3,}")
BANNED = ["仿佛", "似乎", "不禁", "缓缓", "微微", "一丝", "一抹",
          "如同", "宛如", "瞳孔骤缩", "嘴角勾起", "若有所思",
          "意味深长", "深吸一口气", "心中涌起", "五味杂陈",
          "难以言喻", "与此同时", "命运的齿轮", "这一刻", "终于明白"]


def snapshot(books_dir: Path, book: OL.Book, target: int) -> dict:
    files = sorted(books_dir.glob("*.txt")) if books_dir.exists() else []
    rows = []
    total_chars = 0
    for f in files:
        try:
            no = int(f.stem)
        except ValueError:
            continue
        t = f.read_text(encoding="utf-8")
        n = len(HAN.findall(t))
        eng = len(LATIN.findall(t))
        banned = sum(t.count(w) for w in BANNED)
        total_chars += n
        ch = book.chapter(no)
        vol = book.volume_of(no)
        act = next((a for a in book.acts
                    if a["start"] <= no <= a["end"]), book.acts[0])
        rows.append({
            "no": no,
            "chars": n,
            "english": eng,
            "banned": banned,
            "title": ch.title if ch else "",
            "level": ch.level if ch else "",
            "act": act["name"],
            "volume": vol.name if vol else "",
            "head": t[:260],
            "tail": t[-160:],
        })
    rows.sort(key=lambda r: r["no"])
    return {
        "generated": len(rows),
        "target": target,
        "total_chars": total_chars,
        "avg": round(total_chars / max(1, len(rows))),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chapters": rows,
    }


def main(argv: list[str]) -> int:
    target = 200
    books = ROOT / "out" / "books"
    if len(argv) > 0:
        target = int(argv[0])
    if len(argv) > 1:
        books = Path(argv[1])

    world_p = ROOT / "out" / "outline_full.json"
    book = OL.Book.load(world_p)

    d = snapshot(books, book, target)
    out = ROOT / "out" / "progress.json"
    out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    pct = d["generated"] / target * 100
    print(f"{d['updated']}  {d['generated']}/{target} 章 ({pct:.1f}%)  "
          f"{d['total_chars']:,} 字  平均 {d['avg']} 字/章")

    # 质量统计
    if d["chapters"]:
        eng_bad = [c for c in d["chapters"] if c["english"] > 0]
        banned_bad = [c for c in d["chapters"] if c["banned"] > 8]
        short = [c for c in d["chapters"] if c["chars"] < 2800]
        print(f"  英文污染 {len(eng_bad)} 章｜套话超标 {len(banned_bad)} 章"
              f"｜字数不足 {len(short)} 章")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
