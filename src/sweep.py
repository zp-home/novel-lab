#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep.py —— 扫 reasoning_effort / 模型，找「速度 × 质量」的拐点。

用法：python src/sweep.py <章号> <段号>
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import characters as CH          # noqa: E402
import outline as OL             # noqa: E402
import style_contract as SC      # noqa: E402
import worldbuild as WB          # noqa: E402
import write as W                # noqa: E402

CASES = [
    ("agy-cli/gemini-4-hydrogen", "medium"),
    ("agy-cli/gemini-4-hydrogen", "high"),
    ("auto/gemini-3.8-flash", "low"),
    ("auto/gemini-3.8-flash", "medium"),
]


def main(argv: list[str]) -> int:
    ch_no = int(argv[0]) if argv else 5
    seg = int(argv[1]) if len(argv) > 1 else 1

    world = WB.build_world(5000, title="四界")
    cast = CH.build_cast(world, 5000)
    book = OL.Book.load(HERE.parent / "out" / "sijie" / "outline.json")
    key = W.load_env_key()
    prompt = W.build_prompt(book.chapter(ch_no), world, cast,
                            W.CN.Canon(), seg, 2, "", 1700,
                            profile="webnovel")
    out = HERE.parent / "out" / "sweep"
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    for model, effort in CASES:
        body = {"model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.95, "max_tokens": 14000}
        if effort:
            body["reasoning_effort"] = effort
        req = urllib.request.Request(
            "http://127.0.0.1:3425/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        t = time.time()
        tag = f"{model.split('/')[-1]}_{effort}"
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                d = json.loads(r.read().decode())
            txt = W.clean_english(d["choices"][0]["message"]["content"]).strip()
            u = d.get("usage") or {}
            det = u.get("completion_tokens_details") or {}
            r2 = SC.lint(txt, "webnovel", seg_chars=(1300, 2100))
            (out / f"ch{ch_no}_{tag}.txt").write_text(txt, encoding="utf-8")
            rows.append((tag, time.time() - t, W.n_han(txt),
                         u.get("completion_tokens"),
                         det.get("reasoning_tokens"), r2["score"],
                         len(r2["issues"])))
            print(f"{tag:34s} {rows[-1][1]:6.0f}s {rows[-1][2]:5d}字 "
                  f"out={rows[-1][3]:6d} reason={rows[-1][4]:6d} "
                  f"score={rows[-1][5]:5.1f} bad={rows[-1][6]}",
                  flush=True)
        except Exception as e:                           # noqa: BLE001
            print(f"{tag:34s} {time.time() - t:6.0f}s FAIL "
                  f"{type(e).__name__}: {str(e)[:120]}", flush=True)

    print("\n=== 汇总（score 越高越贴合目标文体；速度按每段算）===")
    for tag, sec, chars, otok, rtok, score, bad in rows:
        print(f"{tag:34s} {sec:6.0f}s {chars:5d}字 score={score:5.1f} "
              f"每章≈{sec * 2 / 60:4.1f}分 200章@3并发≈"
              f"{sec * 2 * 200 / 3 / 3600:4.1f}小时")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
