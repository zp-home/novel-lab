#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_model.py —— 同题对比不同模型的耗时/成本/文体契合度。

用法：python src/bench_model.py <章号> <段号> [模型1 模型2 ...]
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import characters as CH          # noqa: E402
import style_contract as SC      # noqa: E402
import outline as OL             # noqa: E402
import worldbuild as WB          # noqa: E402
import write as W                # noqa: E402


def main(argv: list[str]) -> int:
    ch_no = int(argv[0]) if argv else 1
    seg = int(argv[1]) if len(argv) > 1 else 1
    models = argv[2:] or ["agy-cli/gemini-4-hydrogen", "auto/gemini-3.8-flash"]

    world = WB.build_world(5000, title="四界")
    cast = CH.build_cast(world, 5000)
    book = OL.Book.load(HERE.parent / "out" / "outline_full.json")
    key = W.load_env_key()
    ch = book.chapter(ch_no)
    target = 1700
    prompt = W.build_prompt(ch, world, cast, W.CN.Canon(), seg, 2, "",
                            target, profile="webnovel")

    results: dict[str, dict] = {}
    lock = threading.Lock()

    def one(model: str) -> None:
        llm = W.LLM("http://127.0.0.1:3425/v1", key, model, timeout=600)
        t = time.time()
        try:
            txt = llm.chat(prompt, max_tokens=14000).strip()
            txt = W.clean_english(txt)
            dt = time.time() - t
            r = SC.lint(txt, "webnovel", seg_chars=(1300, 2100))
            with lock:
                results[model] = {"ok": True, "sec": dt, "text": txt,
                                  "chars": W.n_han(txt),
                                  "score": r["score"], "issues": r["issues"],
                                  "metrics": r["metrics"],
                                  "out_tok": llm.completion_tokens}
        except Exception as e:                          # noqa: BLE001
            with lock:
                results[model] = {"ok": False, "sec": time.time() - t,
                                  "err": f"{type(e).__name__}: {e}"}

    ths = [threading.Thread(target=one, args=(m,)) for m in models]
    for t in ths:
        t.start()
    for t in ths:
        t.join()

    out = HERE.parent / "out" / "bench"
    out.mkdir(parents=True, exist_ok=True)
    for m, r in results.items():
        safe = m.replace("/", "_")
        print("=" * 70)
        print(f"{m}  {'OK' if r['ok'] else 'FAIL'}")
        if not r["ok"]:
            print("  ", r["err"])
            continue
        print(f"  耗时 {r['sec']:.0f}s  汉字 {r['chars']}  "
              f"契合度 {r['score']}/100  输出tok {r['out_tok']}")
        for k in ("avg_sent", "short6", "long25", "sent_cv", "judgment",
                  "epithet", "concrete", "de", "ttr", "start_div",
                  "g4_dup", "dialogue"):
            if k in r["metrics"]:
                print(f"    {k:10s} {r['metrics'][k]:8.3f}")
        for i in r["issues"]:
            print("    ✗ " + i)
        (out / f"ch{ch_no}_s{seg}_{safe}.txt").write_text(r["text"],
                                                          encoding="utf-8")
        print(f"    -> out/bench/ch{ch_no}_s{seg}_{safe}.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
