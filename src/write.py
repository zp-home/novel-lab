#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
write.py —— 正文生成器（第 6 步）

设计
====

输入：outline_full.json（四层大纲）+ world.json + cast.json + canon.json
输出：out/books/00001.txt ... 每章 4000 字

核心约束（前几轮验证过的）：

1. **分段写**：每章 3 段 × ~1300 字。一次生成 4000 字必然平均化。
2. **上下文恒定**：每段只看「章纲 + 世界状态 + 前 400 字」，不看全文。
3. **质量门禁**：每段生成后立刻检查，不过就重写。
   - 字数下限
   - 英文污染（免费模型常见：混入 "three hundred"）
   - 病句
   - AI 套话密度
4. **断点续跑**：每章落盘，中断可续。

免费模型的问题（实测）
====================
hy4flash-free 会混入英文词（6 段里 3 段有）。所以必须加 `check_english()`
并且重试时把「禁止英文」写进 prompt。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ai_flavor
import canon as CN
import characters as CH
import outline as OL
import style_contract as SC
import worldbuild as WB

HAN_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]{3,}")
SENT_RE = re.compile(r"[。！？!?…]+")


def n_han(s: str) -> int:
    return len(HAN_RE.findall(s))


# ==========================================================================
# 质量门禁
# ==========================================================================

class GateFail(Exception):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("；".join(reasons))


def clean_english(text: str) -> str:
    """
    清理免费模型混入的英文。

    实测 workbuddy/hy4flash-free 会在中文里插入英文词，
    如「陆家小子，你爹欠咱 three hundred 两银子」。
    这些必须清掉，否则读者一眼看出是机器写的。

    第一版写错了：用 `\\s*\\b[A-Za-z]{3,}\\b\\s*` 删除，
    结果 "a piece of paper" 变成 "aof"（单词被逐个删掉后粘连），
    而且 "OK" 因为只有 2 字母没被删。
    修法：先把「连续英文片段」整体匹配掉，再单独处理残留。
    """
    NUM_MAP = {
        "one": "一", "two": "两", "three": "三", "four": "四",
        "five": "五", "six": "六", "seven": "七", "eight": "八",
        "nine": "九", "ten": "十", "hundred": "百", "thousand": "千",
        "twenty": "二十", "thirty": "三十", "fifty": "五十",
    }
    for en, zh in NUM_MAP.items():
        text = re.sub(r"\b" + en + r"\b", zh, text, flags=re.I)

    # 关键：整体匹配「可能由空格分隔的一串英文」，
    # 而不是逐个单词删——否则 a piece of 会粘成 aof
    text = re.sub(r"[A-Za-z][A-Za-z'’\-]*(?:[ \t]+[A-Za-z][A-Za-z'’\-]*)*",
                  "", text)

    # 清理由此产生的空括号、连续标点、行首行尾空白
    text = re.sub(r"[（(]\s*[）)]", "", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。]{2,}", "。", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # 英文被删后常留下「。，」或「，。」这种孤立标点，直接去掉
    text = re.sub(r"[，,、]\s*(?=[。！？])", "", text)
    text = re.sub(r"(?<=[。！？])[，,、]", "", text)
    text = re.sub(r"^[，,、。]+", "", text, flags=re.M)
    text = re.sub(r"^\s+|\s+$", "", text, flags=re.M)
    return text


def trim_to_length(text: str, max_chars: int) -> str:
    """
    超长文本截断到自然段边界。

    为什么不在超长时重试：模型经常一次写 4000+ 字（它以为在写整章）。
    如果判失败重试，会陷入死循环——实测 7 分钟只推进 1 章。
    截断是正确做法：多出来的部分本来就不属于这一段。
    """
    if n_han(text) <= max_chars:
        return text
    paras = text.split("\n")
    out, total = [], 0
    for para in paras:
        k = n_han(para)
        if total + k > max_chars and out:
            break
        out.append(para)
        total += k
    return "\n".join(out) if out else text[:max_chars * 2]


def check_segment(text: str, min_chars: int = 900,
                  max_chars: int = 2400,
                  profile: str = SC.DEFAULT_PROFILE) -> list[str]:
    """
    单段质量检查。返回问题列表，空表示通过。

    分两层：
    1. 硬伤（字数、英文污染、病句、复读）——这些不管什么文体都算错。
    2. 文体契约（style_contract.lint）——按项目选的文体档案对指标。

    第 2 层是这一轮新增的。之前只有第 1 层，而第 1 层其实很宽松：
    它只拦「英文」「病句」「同一句出现 3 次」，拦不住
    「满篇器物特写、零概括、词汇自我复制」这种整体性跑偏。
    实测第 1 章 4122 字在第 1 层是全过的，但读起来费劲。
    """
    problems = []
    n = n_han(text)
    if n < min_chars:
        problems.append(f"字数 {n} < {min_chars}")

    # 英文污染（免费模型常见）
    eng = LATIN_RE.findall(text)
    if len(eng) > 2:
        problems.append(f"混入英文 {len(eng)} 处：{'/'.join(eng[:3])}")

    # 病句
    g = OL.check_grammar(text)
    if g:
        problems.append(f"病句：{g[0]}")

    # 复读：同一句出现 3 次以上
    sents = [s.strip() for s in SENT_RE.split(text) if n_han(s) > 4]
    if sents:
        from collections import Counter
        top, cnt = Counter(sents).most_common(1)[0]
        if cnt >= 3:
            problems.append(f"复读：同一句出现 {cnt} 次")

    # 禁用词密度
    hits = sum(text.count(w) for w in P_BANNED)
    if hits > 8:
        problems.append(f"AI 套话 {hits} 处（刷屏）")

    # 注意：这里**故意不**把 style_contract 的文体指标当硬伤。
    #
    # 实测教训：一段 1200 字的样本，ttr / g4_dup / concrete 这些指标的
    # 抽样噪声很大，经常在阈值上下抖 0.005。把它们当硬伤的结果是
    # 每段平均重试 1.75 次（一章 6 次），而重试生成的新稿并不更好，
    # 最后用的还是降级稿——纯粹烧钱烧时间。
    #
    # 所以分成两层：
    #   单段：只拦结构性硬伤（字数/英文/病句/复读/套话刷屏）
    #   整章：跑 style_contract.lint 打分，记进 manifest，
    #         由「待修章节」表驱动事后重写（见 src/repair.py）
    # 这也更符合事实：文体是整章属性，不是段属性。

    return problems



# 与 prompts.py 保持一致的禁用词（只取最刺眼的）
P_BANNED = [
    "仿佛", "似乎", "不禁", "不由得", "缓缓", "微微", "轻轻", "悄然",
    "一丝", "一抹", "一缕", "如同", "宛如", "犹如", "恰似",
    "瞳孔骤缩", "嘴角勾起", "眼底闪过", "若有所思", "意味深长",
    "深吸一口气", "沉默片刻", "心中涌起", "心头一震", "五味杂陈",
    "百感交集", "难以言喻", "不知为何", "与此同时", "命运的齿轮",
    "冥冥之中", "这一刻", "终于明白", "恍然大悟", "无尽的", "深深的",
    "莫名的", "前所未有的", "难以形容的", "令人窒息的",
]


# ==========================================================================
# 模型
# ==========================================================================

class LLM:
    def __init__(self, base: str, key: str, model: str,
                 temperature: float = 0.95, timeout: int = 240,
                 effort: str | None = None):
        self.base = base.rstrip("/")
        self.key = key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.effort = effort
        self.calls = 0
        self.fails = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._lock = threading.Lock()

    def chat(self, prompt: str, max_tokens: int = 2200,
             temperature: float | None = None,
             effort: str | None = "__same__") -> str:
        import urllib.error
        import urllib.request
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        # 逐次覆盖推理档位：默认沿用实例设置，调用方可以按"第几次尝试"传不同的值。
        # 实测（同一章同一段）：
        #   high   237s 1484字 契合度 47.0
        #   medium  70s 1226字 契合度 41.3
        #   low     35s  996字 契合度 28.1
        # 所以默认 medium，质检不过再升 high——不要一上来就 high。
        eff = self.effort if effort == "__same__" else effort
        if eff:   # 空字符串=不传，实测传了反而触发 3 万推理 token
            body["reasoning_effort"] = eff
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.key})
        last = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    d = json.loads(r.read().decode("utf-8"))
                txt = d["choices"][0]["message"]["content"]
                u = d.get("usage", {})
                with self._lock:
                    self.calls += 1
                    self.prompt_tokens += u.get("prompt_tokens", 0)
                    self.completion_tokens += u.get("completion_tokens", 0)
                return txt
            except urllib.error.HTTPError as e:          # noqa: F821
                last = e
                with self._lock:
                    self.fails += 1
                # 429 必须指数退避。
                #
                # 踩过的坑：初版对所有错误一视同仁，1/2/3 秒后重试。
                # 结果是连发 3 个 429 之后整批任务全部失败，
                # 每章拿到空稿还被当成成功写进了正文文件
                # （日志里 15 章「✅ 0字 评分77.7 重试9」）。
                # 限流不是"稍等一秒就好"，要等真的退下去。
                if e.code in (429, 503, 502):
                    wait = min(60, 8 * (2 ** attempt))
                    time.sleep(wait)
                else:
                    time.sleep(1.5 * (attempt + 1))
            except Exception as e:                       # noqa: BLE001
                last = e
                with self._lock:
                    self.fails += 1
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"模型调用失败 5 次：{last}")


# ==========================================================================
# Prompt
# ==========================================================================

STYLE = SC.PROFILES[SC.DEFAULT_PROFILE]["contract"]


def build_prompt(ch: OL.Chapter, world: WB.WorldBible,
                 cast: CH.Cast, canon: CN.Canon,
                 seg: int, n_seg: int, prev_text: str,
                 target: int, feedback: str = "",
                 profile: str = SC.DEFAULT_PROFILE,
                 compact: bool = False) -> str:
    lv = world.level_at(ch.no)
    present = []
    for cid in ch.cast:
        c = cast.get(cid)
        if c:
            present.append(c)
    present_txt = "\n".join(
        f"- {c.name}（{c.role}）：{world.level_at(ch.no).name if c.id == 'c1' else CH.level_name(world, c.level_at(ch.no))}"
        f"｜{c.voice.get('语气', '')}｜口头禅 {'/'.join(c.voice.get('口头禅', [])[:2])}"
        for c in present[:4])

    beats = "\n".join(f"  {i+1}. [{b.kind}] {b.spec or b.text}"
                      for i, b in enumerate(ch.beats))

    # 本段要覆盖哪个 beat
    beat_i = min(len(ch.beats) - 1, (seg - 1) * len(ch.beats) // n_seg)
    this_beat = ch.beats[beat_i]

    # 状态块：恒定上下文的关键（大小与章节号无关）
    try:
        state_txt = CN.render_state(canon, ch.no, list(ch.cast))
    except Exception:                                    # noqa: BLE001
        state_txt = ""

    # 分段职责。两段制是这一轮改的：
    # 三段制每段只有 1300 字，模型为了凑字数就往里塞器物特写；
    # 两段制每段 1700 字，有空间把「为什么」讲清楚。
    if n_seg == 2:
        seg_guide = [
            "第一段（建立 + 抛问题）：用一次具体的行动或对话切入，交代清楚"
            "**此刻的处境、人物想要什么、什么在挡着**。中间必须有一段至少 6 句的"
            "对话来回，双方掌握的信息不对称。写满 5 个自然段。",
            "第二段（加压 + 决断）：障碍比预想更麻烦，代价具体到数得出来。"
            "主角做出选择，写清楚他放弃了什么。**不要写他后悔**。"
            "结尾停在本章规定的那句话上。写满 5 个自然段。",
        ]
        this_guide = seg_guide[min(seg - 1, 1)]
        n_para = 5
    else:
        seg_guide = [
            "第一段（建立 + 抛问题）：交代处境、目标、障碍。写满 4 个自然段。",
            "第二段（推进）：目标受阻。至少 6 句对话来回，双方信息不对称。"
            "写满 4 个自然段。",
            "第三段（加压 + 收束）：代价具体化，主角做出选择。"
            "写清楚代价是什么，不写他后悔。写满 4 个自然段。",
        ]
        this_guide = seg_guide[min(seg - 1, 2)]
        n_para = 4

    end_req = ""
    if seg == n_seg and ch.ends_with:
        end_req = (f"\n【本章最后一段必须收在这个要点上（用你自己的话写，"
                   f"禁止照抄这个词序）】\n  {ch.end_spec or ch.ends_with}")

    target_min = int(target * 0.82)
    target_max = int(target * 1.15)

    return f"""你在写长篇小说《{world.title}》第 {ch.no} 章的第 {seg}/{n_seg} 段。

【本章大纲】
第 {ch.no} 章《{ch.title}》｜主角当前境界：{lv.name if lv else ''}
本章目标：{ch.goal}

四个要点（这是**要点**，不是句子；用你自己的话写成情节，禁止照抄词序）：
{beats}

【本段要写】
{this_guide}
本段要落在这个要点上：[{this_beat.kind}] {this_beat.spec or this_beat.text}
字数：{target_min} ~ {target_max} 字（硬指标，多写要删，少写要补）。

【在场人物】
{present_txt}

【世界状态（用来核对事实，不许复述外观，见契约第六条）】
{state_txt}

【前文最后 400 字（必须无缝接上，不要重述）】
{prev_text or '（这是本章开头）'}
{end_req}
{SC.contract(profile)}
{feedback}

【长度与质感同时是硬指标】
写不够就补：补**人物的盘算、对话的来回、障碍的具体运作方式**，
不要靠加器物描写和形容词凑字数——那些是这一版要砍掉的东西。
写超了就删：先删环境描写，再删重复动作，最后才动对话。

只输出正文。不要标题，不要章节号，不要任何解释或说明。
"""



# ==========================================================================
# 单章生成
# ==========================================================================

class Writer:
    def __init__(self, llm: LLM, world: WB.WorldBible, cast: CH.Cast,
                 book: OL.Book, out: Path, segs: int = 2,
                 words: int = 3400, retries: int = 2, verbose: bool = True,
                 profile: str = SC.DEFAULT_PROFILE,
                 max_tokens: int = 12000,
                 efforts: list[str] | None = None):
        self.llm = llm
        self.world = world
        self.cast = cast
        self.book = book
        self.out = out
        self.segs = segs
        self.words = words
        self.retries = retries
        self.verbose = verbose
        self.profile = profile
        self.max_tokens = max_tokens
        # 推理档位阶梯：第 1 次用第 1 档，第 2 次升到第 2 档……
        # 实测 medium 比 high 快 3.4 倍，只在写砸时才值得花 high 的钱。
        # 空列表 = 这个模型不吃 reasoning_effort（deepseek 就是），一律不传。
        self.efforts = list(efforts) if efforts else [""]
        self.canon = CN.Canon()
        CH.sync_to_canon(cast, self.canon)
        self.log_lines: list[str] = []
        self._lock = threading.Lock()

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with self._lock:
            self.log_lines.append(line)
        if self.verbose:
            print(line, flush=True)

    def _extend(self, text: str, need: int, tail_ctx: str) -> str:
        """
        写不够时「接着写」，而不是「重写」。

        为什么：重写要重新生成 1700 字（60~90 秒），而且新稿很可能
        还是不够；接着写只要再补几百字，还能保住前半段的语气衔接。
        衔接靠给模型看最后 200 字 + 明确「不要重写前面」。
        """
        prompt = (
            f"以下是正在写的一段小说正文的最后 200 字：\n\n{text[-200:]}\n\n"
            f"接着往下写，补足 {need} 字左右，然后自然停住。\n"
            f"要求：直接从断点续写，不要重复前面已经写过的内容，"
            f"不要写「……」「（续）」之类的标记，不要总结。\n"
            f"补的内容优先写：人物的盘算、对话的来回、障碍的具体运作方式。"
            f"不要靠环境描写和形容词凑字数。\n\n只输出续写的正文。"
        )
        try:
            add = self.llm.chat(prompt, max_tokens=self.max_tokens,
                                effort=self.efforts[0])
            add = clean_english(add).strip()
            if n_han(add) < 80:
                return text
            return text.rstrip() + "\n" + add
        except Exception:                                # noqa: BLE001
            return text

    def write_chapter(self, no: int) -> tuple[str, dict]:
        ch = self.book.chapter(no)
        if not ch:
            raise ValueError(f"第 {no} 章没有大纲")

        target = self.words // self.segs
        lo, hi = int(target * 0.82), int(target * 1.15)
        segs: list[str] = []
        stats = {"chapter": no, "segs": [], "retries": 0, "lint": []}

        for si in range(1, self.segs + 1):
            prev = "\n".join(segs)[-400:]
            feedback = ""
            got = None
            for attempt in range(self.retries + 1):
                prompt = build_prompt(ch, self.world, self.cast, self.canon,
                                      si, self.segs, prev, target, feedback,
                                      profile=self.profile)
                eff = self.efforts[min(attempt, len(self.efforts) - 1)]
                try:
                    txt = self.llm.chat(prompt, max_tokens=self.max_tokens,
                                        effort=eff).strip()
                    txt = clean_english(txt)
                    # 截断线必须等于上限 hi，不能更松。
                    # 之前设的是 target*1.35，结果模型写到 1500 字，
                    # 截断后仍然超过 hi(1380)，被判"字数超了"→ 重试，
                    # 而重试生成的新稿大概率还是超长。一章白烧 3 次调用。
                    # 截断本来就是为了"多出来的部分不属于这一段"，直接截到 hi。
                    txt = trim_to_length(txt, hi)
                except Exception as e:                   # noqa: BLE001
                    feedback = f"\n【上轮失败】{e}"
                    stats["retries"] += 1
                    continue

                # 太短：先接着写，别浪费掉已经不错的前半段
                if n_han(txt) < lo:
                    txt = self._extend(txt, lo - n_han(txt) + 150, prev)
                    # 续写之后必须再截一次。踩过的坑：忘了这一步，
                    # 续写把段推到 4531 字（上限 4140），整章超出 4000 字要求。
                    txt = trim_to_length(txt, hi)

                probs = check_segment(txt, min_chars=lo, max_chars=hi,
                                      profile=self.profile)
                if not probs:
                    got = txt
                    break

                stats["retries"] += 1
                feedback = ("\n【上轮问题，必须逐条修正】\n- " +
                            "\n- ".join(probs[:6]))
                try:
                    soft = SC.lint(txt, self.profile, seg_chars=(lo, hi)).get("soft", [])
                    if soft:
                        # 软指标不触发重写，但既然已经要重写了，就顺手一起提
                        feedback += ("\n【另外这些地方读起来还紧，能改就改】\n- "
                                     + "\n- ".join(soft[:3]))
                except Exception:                        # noqa: BLE001
                    pass
                if self.verbose:
                    self.log(f"    第{no}章 段{si} 第{attempt+1}次未过："
                             f"{'；'.join(probs[:3])}")

            if got is None:
                got = txt if 'txt' in dir() else ""
                self.log(f"  ⚠️ 第{no}章 段{si} 未达质量标准，保留降级稿")

            segs.append(got)
            stats["segs"].append(n_han(got))

        text = "\n\n".join(segs)
        stats["chars"] = n_han(text)

        # 空稿绝不能当成功。
        #
        # 踩过的坑：模型被限流（HTTP 429）时，三次尝试全失败，
        # `got` 落成空字符串，write_chapter 照样返回，
        # runner 照样写盘、照样打 ✅。
        # 日志里出现了 15 章「✅ 0字 评分77.7 重试9」，
        # 正文文件被覆盖成空——而且是在 --force 模式下，
        # 等于把之前写好的章也一起毁了。
        if stats["chars"] < 500:
            raise RuntimeError(
                f"第 {no} 章只生成了 {stats['chars']} 字，判定失败（不写盘）")

        # 整章层面算文体分：3000 字的样本统计意义才够
        try:
            r = SC.lint(text, self.profile)
            stats["lint"] = [r["score"]]
            stats["issues"] = r["issues"] + r.get("soft", [])
        except Exception:                                # noqa: BLE001
            stats["lint"] = []
            stats["issues"] = []
        return text, stats


    def save_chapter(self, no: int, text: str) -> Path:
        self.out.mkdir(parents=True, exist_ok=True)
        p = self.out / f"{no:05d}.txt"
        p.write_text(text, encoding="utf-8")
        return p


# ==========================================================================
# 批量
# ==========================================================================

def load_env_key() -> str:
    env = Path(os.path.expanduser("~")) / ".dsh" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("MAGPIE_GATEWAY_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get("MAGPIE_GATEWAY_KEY", "")


def run(start: int, end: int, writer: Writer, workers: int,
        resume: bool) -> dict:
    todo = []
    for no in range(start, end + 1):
        p = writer.out / f"{no:05d}.txt"
        if resume and p.exists() and p.stat().st_size > 500:
            continue
        todo.append(no)

    print(f"待写 {len(todo)} 章（第 {start}~{end} 章），并发 {workers}")
    if not todo:
        return {"done": 0, "skipped": end - start + 1}

    t0 = time.time()
    done = 0
    errors = []
    lock = threading.Lock()

    def work(no):
        try:
            text, stats = writer.write_chapter(no)
            writer.save_chapter(no, text)
            return stats
        except Exception as e:                           # noqa: BLE001
            return {"chapter": no, "error": str(e),
                    "trace": traceback.format_exc()[-400:]}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, no): no for no in todo}
        for fut in as_completed(futs):
            r = fut.result()
            with lock:
                done += 1
                if "error" in r:
                    errors.append(r)
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (len(todo) - done) / rate if rate else 0
                if done % 5 == 0 or done == len(todo):
                    print(f"  [{done}/{len(todo)}] "
                          f"{rate*3600:.0f} 章/小时  "
                          f"ETA {eta/60:.1f} 分  "
                          f"错误 {len(errors)}", flush=True)

    return {"done": done, "errors": errors,
            "seconds": round(time.time() - t0, 1)}


# ==========================================================================
# CLI
# ==========================================================================

def main(argv: list[str]) -> int:
    """
    兼容入口。真正的编排在 runner.py。

    为什么留这个壳：老的调用方式是
        python src/write.py --start 1 --end 200 --workers 4
    现在改成项目制（projects/<name>.toml），直接报错会让人卡住，
    所以这里把所有参数翻译成一次 runner 调用。
    """
    import project as PJ
    import runner as R

    ap = argparse.ArgumentParser(description="生成正文（转调 runner）")
    ap.add_argument("--project", default="sijie")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--segs", type=int, default=0)
    ap.add_argument("--words", type=int, default=0)
    ap.add_argument("--profile", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--max-tokens", type=int, default=0)
    ap.add_argument("--fresh", "--force", dest="force", action="store_true")
    a = ap.parse_args(argv)

    p = PJ.Project.load(a.project)
    if a.workers:
        p.workers = a.workers
    if a.segs:
        p.segs = a.segs
    if a.words:
        p.words_per_chapter = a.words
    if a.profile:
        p.style = a.profile
    if a.model:
        p.model = a.model
    if a.max_tokens:
        p.max_tokens = a.max_tokens
    print(f"→ runner：{p.summary()}")
    return R.run(p, a.start, a.end or p.chapters, p.workers, force=a.force)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
