#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project.py —— 项目配置（通用框架的入口）

为什么需要这一层
================

在此之前，整条流水线的参数是散落在各个 CLI 里的：
`--start/--end/--workers` 给 write.py，规模写死在 `build_world(5000)`，
标题写死 `title="四界"`，模型写死在 argparse 默认值，输出目录写死 `out/books`。

后果有三个，都是真实发生过的：

1. **Web 控制台没法接**。前端要知道"这个项目总共几章、每章多少字、
   用哪个模型"，但没有任何地方能一次问出来。
2. **不能同时跑两个项目**。所有输出都往 `out/books/` 里灌，
   两个项目会互相覆盖。
3. **改参数要改代码**。想试 3200 字/章，得改源码或记一长串命令行参数。

所以把「一个小说项目」变成一份配置：`projects/<name>.toml`，
其余所有模块都从 `Project` 对象取值。这也是"通用框架"的第一步——
框架本身不假设题材、规模、模型，只有「世界设定预设」是有题材的。

配置长这样（projects/sijie.toml）：

    [project]
    name = "sijie"
    title = "四界"
    genre = "仙侠"
    logline = "打铁的少年发现母亲留下的铜镜里藏着一道碑印"
    style = "webnovel"
    model = "agy-cli/gemini-4-hydrogen"
    chapters = 5000
    words_per_chapter = 3400
    segs = 2
    workers = 3
    world_preset = "four_realm"

    [gate]
    max_retries = 2
    min_score = 0

输出目录约定：

    out/<name>/chapters/00001.txt     正文
    out/<name>/outline.json           四层大纲
    out/<name>/manifest.json          Web 控制台读的进度清单
    out/<name>/run.log                运行日志
    out/<name>/world.json             世界设定
    out/<name>/cast.json              人物表
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROJECTS_DIR = REPO / "projects"
OUT_DIR = REPO / "out"

# 没写就用这套默认值（保证只有 name 也能跑起来）
DEFAULTS: dict[str, Any] = {
    "title": "未命名",
    "genre": "仙侠",
    "logline": "",
    "style": "webnovel",
    "model": "agy-cli/gemini-4-hydrogen",
    "chapters": 5000,
    "words_per_chapter": 3400,
    "segs": 2,
    "workers": 3,
    "world_preset": "four_realm",
    "max_tokens": 14000,
    "max_retries": 2,
    "efforts": ["medium", "high"],
}


@dataclass
class Project:
    name: str
    title: str = DEFAULTS["title"]
    genre: str = DEFAULTS["genre"]
    logline: str = ""
    style: str = DEFAULTS["style"]
    model: str = DEFAULTS["model"]
    chapters: int = DEFAULTS["chapters"]
    words_per_chapter: int = DEFAULTS["words_per_chapter"]
    segs: int = DEFAULTS["segs"]
    workers: int = DEFAULTS["workers"]
    world_preset: str = DEFAULTS["world_preset"]
    max_tokens: int = DEFAULTS["max_tokens"]
    max_retries: int = DEFAULTS["max_retries"]
    # 推理档位阶梯。空列表 = 不传 reasoning_effort。
    #
    # 为什么要可配：不同模型对这个参数的反应完全相反。
    #   gemini-4-hydrogen：high 237s / medium 70s / low 35s，medium 是最佳性价比
    #   deepseek-v4.1-flash-max：**传了反而更差**（默认 1431 推理 token，
    #     传 low 变 32857），所以必须传空列表
    efforts: list = field(default_factory=lambda: list(DEFAULTS["efforts"]))
    raw: dict = field(default_factory=dict)

    # ---------------- 路径 ----------------
    @property
    def dir(self) -> Path:
        return OUT_DIR / self.name

    @property
    def chapters_dir(self) -> Path:
        return self.dir / "chapters"

    @property
    def outline_path(self) -> Path:
        return self.dir / "outline.json"

    @property
    def world_path(self) -> Path:
        return self.dir / "world.json"

    @property
    def cast_path(self) -> Path:
        return self.dir / "cast.json"

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    @property
    def log_path(self) -> Path:
        return self.dir / "run.log"

    def chapter_path(self, no: int) -> Path:
        return self.chapters_dir / f"{no:05d}.txt"

    def ensure_dirs(self) -> None:
        self.chapters_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- 读写 ----------------
    @classmethod
    def load(cls, name: str) -> "Project":
        p = PROJECTS_DIR / f"{name}.toml"
        if not p.exists():
            raise FileNotFoundError(f"找不到项目配置 {p}")
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(name, data)

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Project":
        sec = data.get("project", data)
        gate = data.get("gate", {})
        merged = dict(DEFAULTS)
        merged.update({k: v for k, v in sec.items()
                       if k in DEFAULTS and k not in ("max_retries",)})
        if "max_retries" in gate:
            merged["max_retries"] = gate["max_retries"]
        if "max_tokens" in gate:
            merged["max_tokens"] = gate["max_tokens"]
        if "efforts" in sec:
            merged["efforts"] = list(sec["efforts"])
        merged["name"] = name
        return cls(**merged, raw=data)

    @classmethod
    def list_all(cls) -> list["Project"]:
        if not PROJECTS_DIR.exists():
            return []
        out = []
        for p in sorted(PROJECTS_DIR.glob("*.toml")):
            try:
                out.append(cls.load(p.stem))
            except Exception:                            # noqa: BLE001
                continue
        return out

    def save(self) -> Path:
        """写回 toml（只在 Web 新建项目时用，格式从简）。"""
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        lines = ["[project]"]
        for k in ("name", "title", "genre", "logline", "style", "model",
                  "chapters", "words_per_chapter", "segs", "workers",
                  "world_preset"):
            v = getattr(self, k)
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            else:
                lines.append(f"{k} = {v}")
        lines.append("efforts = [" + ", ".join(f'"{e}"' for e in self.efforts) + "]")
        lines += ["", "[gate]", f"max_retries = {self.max_retries}",
                  f"max_tokens = {self.max_tokens}", ""]
        p = PROJECTS_DIR / f"{self.name}.toml"
        p.write_text("\n".join(lines), encoding="utf-8")
        return p

    # ---------------- 校验 ----------------
    def validate(self) -> list[str]:
        bad = []
        if not self.name.isidentifier():
            bad.append(f"项目名 {self.name!r} 必须是合法标识符（字母数字下划线）")
        if self.chapters < 1:
            bad.append("chapters 必须 ≥ 1")
        if not (1500 <= self.words_per_chapter <= 8000):
            bad.append("words_per_chapter 建议 1500~8000")
        if self.segs < 1:
            bad.append("segs 必须 ≥ 1")
        if self.words_per_chapter // max(self.segs, 1) < 700:
            bad.append("每段不足 700 字，模型容易写不够，建议减少 segs")
        if not (1 <= self.workers <= 8):
            bad.append("workers 建议 1~8（实测 ≥8 会让网关排队到超时）")
        return bad

    def summary(self) -> str:
        return (f"{self.title}（{self.genre}）｜{self.chapters} 章 × "
                f"{self.words_per_chapter} 字｜{self.segs} 段/章｜"
                f"文体 {self.style}｜模型 {self.model}｜并发 {self.workers}")


def load(name: str) -> Project:
    return Project.load(name)


if __name__ == "__main__":
    import sys
    names = sys.argv[1:]
    if not names:
        for p in Project.list_all():
            bad = p.validate()
            print(f"[{'OK' if not bad else 'BAD'}] {p.name}: {p.summary()}")
            for b in bad:
                print("      ✗", b)
    else:
        for n in names:
            p = Project.load(n)
            print(p.summary())
            for b in p.validate():
                print("  ✗", b)
