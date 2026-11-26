#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runner.py —— 流水线唯一入口

    python src/runner.py --project sijie --from 1 --to 200

它负责串起整条链子，并维护 Web 控制台要读的 manifest：

    1. 读项目配置 projects/<name>.toml
    2. 世界设定   out/<name>/world.json      （缺就按预设生成）
    3. 人物表     out/<name>/cast.json       （缺就按预设生成）
    4. 四层大纲   out/<name>/outline.json    （缺就确定性生成，0 次模型调用）
    5. 正文       out/<name>/chapters/NNNNN.txt
    6. 进度清单   out/<name>/manifest.json   （每写完一章就刷新）

为什么要有这个入口
==================

以前是 `python src/write.py --start 1 --end 200 --workers 4 --out out/books`，
参数全部走命令行，而且 write.py 里还写死了 `build_world(5000)`。
现在 write.py 只负责「写一章」，编排全部收在这里：

- 断点续跑：manifest + 目录扫描双重判断，中断后重跑不会重复写
- 进度清单：每章落盘后立刻刷新，Web 随时可读
- 单章质量留痕：score / retries / issues 写进 index.jsonl，
  事后能直接查出「哪几章需要重写」

index.jsonl 是追加写的单章记录（一行一条），manifest 是它的聚合视图。
分开的好处：manifest 可以随时重建，索引不会因为 manifest 写坏而丢。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import characters as CH      # noqa: E402
import outline as OL         # noqa: E402
import project as PJ         # noqa: E402
import style_contract as SC  # noqa: E402
import worldbuild as WB      # noqa: E402
import write as W            # noqa: E402


# ==========================================================================
# 索引与 manifest
# ==========================================================================

INDEX_LOCK = threading.Lock()


def index_path(p: PJ.Project) -> Path:
    return p.dir / "index.jsonl"


def append_index(p: PJ.Project, rec: dict) -> None:
    with INDEX_LOCK:
        p.dir.mkdir(parents=True, exist_ok=True)
        with open(index_path(p), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_index(p: PJ.Project) -> dict[int, dict]:
    """chapters.jsonl → {章号: 记录}（同章号后写的覆盖先写的）。"""
    out: dict[int, dict] = {}
    f = index_path(p)
    if not f.exists():
        return out
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            out[int(r["no"])] = r
        except Exception:                                # noqa: BLE001
            continue
    return out


def lint_targets(style: str) -> dict:
    prof = SC.PROFILES.get(style) or SC.PROFILES[SC.DEFAULT_PROFILE]
    return {k: [lo, hi] for k, (lo, hi, _) in prof["targets"].items()}


def build_manifest(p: PJ.Project, running: dict | None = None,
                   errors: list | None = None) -> dict:
    idx = read_index(p)
    # **以磁盘为准**。index.jsonl 只用来补元数据，不用来决定"写了多少章"。
    #
    # 踩过的坑：初版用 set(idx) | on_disk，于是被删掉/写坏的章仍然算数。
    # 实测一次 429 风暴把 15 章覆盖成 8 字节空文件、事后删掉，
    # manifest 却仍然显示「已写 15 章，平均 3323 字」——
    # Web 控制台上看到的进度是假的。
    on_disk = {int(f.stem) for f in p.chapters_dir.glob("*.txt")
               if f.stem.isdigit() and f.stat().st_size > 1500}
    nos = sorted(on_disk)

    chars = [idx[n]["chars"] for n in nos if n in idx and idx[n].get("chars")]
    scores = [idx[n]["score"] for n in nos
              if n in idx and idx[n].get("score") is not None]
    lo = int(p.words_per_chapter * 0.88)

    chapters = []
    for n in nos:
        r = idx.get(n, {})
        chapters.append({
            "no": n,
            "chars": r.get("chars"),
            "score": r.get("score"),
            "retries": r.get("retries", 0),
            "issues": r.get("issues", [])[:4],
        })

    return {
        "project": p.name,
        "title": p.title,
        "genre": p.genre,
        "total": p.chapters,
        "written": len(nos),
        "target_words": [int(p.words_per_chapter * 0.88),
                         int(p.words_per_chapter * 1.18)],
        "model": p.model,
        "style": p.style,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "stats": {
            "avg_chars": round(sum(chars) / len(chars), 1) if chars else 0,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "below_target": sum(1 for c in chars if c < lo),
            "errors": len(errors or []),
        },
        "running": running,
        "chapters": chapters,
        "lint_targets": lint_targets(p.style),
    }


def write_manifest(p: PJ.Project, running: dict | None = None,
                   errors: list | None = None) -> None:
    p.dir.mkdir(parents=True, exist_ok=True)
    m = build_manifest(p, running, errors)
    tmp = p.manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p.manifest_path)      # 原子替换，Web 不会读到半截 JSON


# ==========================================================================
# 阶段：世界 / 人物 / 大纲
# ==========================================================================

def ensure_world(p: PJ.Project, log) -> WB.WorldBible:
    if p.world_path.exists():
        try:
            return WB.WorldBible.load(p.world_path)
        except Exception as e:                           # noqa: BLE001
            log(f"world.json 读不出来（{e}），重新生成")
    log("生成世界设定…")
    world = WB.build_world(p.chapters, title=p.title, logline=p.logline)
    world.save(p.world_path)
    return world


def ensure_cast(p: PJ.Project, world: WB.WorldBible, log) -> CH.Cast:
    if p.cast_path.exists():
        try:
            return CH.Cast.load(p.cast_path)
        except Exception as e:                           # noqa: BLE001
            log(f"cast.json 读不出来（{e}），重新生成")
    log("生成人物表…")
    cast = CH.build_cast(world, p.chapters)
    cast.save(p.cast_path)
    return cast


def ensure_outline(p: PJ.Project, world, cast, log) -> OL.Book:
    if p.outline_path.exists():
        try:
            book = OL.Book.load(p.outline_path)
            if len(book.all_chapters()) >= p.chapters:
                return book
            log(f"大纲只有 {len(book.all_chapters())} 章，需要 {p.chapters} 章，重建")
        except Exception as e:                           # noqa: BLE001
            log(f"outline.json 读不出来（{e}），重建")
    log(f"确定性生成 {p.chapters} 章大纲（0 次模型调用）…")
    t = time.time()
    book = OL.build_outline(world, cast, p.chapters,
                            words_per_ch=p.words_per_chapter)
    problem = OL.validate(book, world, cast, p.chapters)
    if problem:
        log(f"大纲校验有 {len(problem)} 条问题：{problem[:3]}")
    log(f"大纲完成，用时 {time.time() - t:.1f}s")
    book.save(p.outline_path)
    return book


# ==========================================================================
# 主流程
# ==========================================================================

def run(p: PJ.Project, start: int, end: int, workers: int,
        force: bool = False, log_path: Path | None = None) -> int:
    p.ensure_dirs()
    logp = log_path or p.log_path
    logp.parent.mkdir(parents=True, exist_ok=True)
    logf = open(logp, "a", encoding="utf-8")
    lock = threading.Lock()

    def log(msg: str) -> None:
        line = f"[{datetime.now():%H:%M:%S}] {msg}"
        with lock:
            print(line, flush=True)
            logf.write(line + "\n")
            logf.flush()

    log("=" * 70)
    log(f"项目 {p.name}｜{p.summary()}")
    bad = p.validate()
    for b in bad:
        log(f"  ⚠️ 配置问题：{b}")

    key = W.load_env_key()
    if not key:
        log("❌ 找不到 MAGPIE_GATEWAY_KEY（~/.dsh/.env）")
        return 1

    world = ensure_world(p, log)
    cast = ensure_cast(p, world, log)
    book = ensure_outline(p, world, cast, log)

    todo = [n for n in range(start, min(end, p.chapters) + 1)
            if force or not p.chapter_path(n).exists()
            or p.chapter_path(n).stat().st_size < 500]
    log(f"待写 {len(todo)} 章（{start}~{min(end, p.chapters)}），并发 {workers}")
    write_manifest(p, running={"pid": os.getpid(), "from": start,
                               "to": end, "done": 0, "todo": len(todo),
                               "eta_sec": None, "phase": "prose"})
    if not todo:
        log("没有要写的章，退出")
        logf.close()
        return 0

    llm = W.LLM("http://127.0.0.1:3425/v1", key, p.model, timeout=900)
    writer = W.Writer(llm, world, cast, book, p.chapters_dir,
                      segs=p.segs, words=p.words_per_chapter,
                      retries=p.max_retries, profile=p.style,
                      max_tokens=p.max_tokens, verbose=False,
                      efforts=p.efforts or [""])

    errors: list[dict] = []
    done = 0
    t0 = time.time()

    def work(no: int):
        try:
            text, stats = writer.write_chapter(no)
            writer.save_chapter(no, text)
            sc = [s for s in stats.get("lint", []) if s]
            rec = {"no": no, "chars": stats["chars"],
                   "score": round(sum(sc) / len(sc), 1) if sc else None,
                   "retries": stats.get("retries", 0),
                   "segs": stats.get("segs", []),
                   "issues": (stats.get("issues") or [])[:4],
                   "ts": datetime.now().isoformat(timespec="seconds")}
            append_index(p, rec)
            return rec
        except Exception as e:                           # noqa: BLE001
            return {"no": no, "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-500:]}

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(work, n): n for n in todo}
            for fut in as_completed(futs):
                r = fut.result()
                done += 1
                if "error" in r:
                    errors.append(r)
                    log(f"  ❌ 第{r['no']}章 失败：{r['error'][:120]}")
                else:
                    log(f"  ✅ 第{r['no']}章 {r['chars']}字 "
                        f"评分{r['score']} 重试{r['retries']}"
                        f"  [{done}/{len(todo)}]")
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (len(todo) - done) / rate if rate else 0
                write_manifest(p, running={
                    "pid": os.getpid(), "from": start, "to": end,
                    "done": done, "todo": len(todo),
                    "eta_sec": round(eta), "phase": "prose"}, errors=errors)
    except KeyboardInterrupt:
        log("收到中断，已写的章都落盘了，可以 --from 续跑")
    finally:
        el = time.time() - t0
        log(f"结束：完成 {done}/{len(todo)} 章，用时 {el / 60:.1f} 分，"
            f"模型调用 {llm.calls} 次，失败 {llm.fails} 次，"
            f"tokens 入 {llm.prompt_tokens:,} / 出 {llm.completion_tokens:,}")
        write_manifest(p, running=None, errors=errors)
        logf.close()
    return 0 if not errors else 2


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="novel-lab 流水线入口")
    ap.add_argument("--project", required=True)
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--to", dest="end", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="已存在的章也重写")
    ap.add_argument("--log", default="")
    a = ap.parse_args(argv)

    p = PJ.Project.load(a.project)
    end = a.end or p.chapters
    workers = a.workers or p.workers
    return run(p, a.start, end, workers, force=a.force,
               log_path=Path(a.log) if a.log else None)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
