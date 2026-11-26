#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py —— 3000 本 × 5000 字的工业化流水线（可跑的最小实现）

架构（每个环节都是一个独立的"闸门"，不通过就回退，不往下走）

    seeds.json
        │
        ├─ S1 选题 ──────────── 反套路约束（防撞梗）
        │      ↓ gate: logline 长度 / 禁用词 / 八维覆盖
        ├─ S2 设定圣经 ──────── Story Bible（防 OOC、防设定崩塌）
        │      ↓ gate: 伏笔数 / 否定性事实 / voice 完整度
        ├─ S3 场景表 ────────── 4 场景 × goal/obstacle/turn/info_gap
        │      ↓ gate: 每个场景必须有不可逆转折
        ├─ S4 正文（滚雪球）─── 4 段 × 4 场景，每段 300-350 字
        │      ↓ gate: 字数 / 禁用词 / 句长 CV
        ├─ S5 去 AI 味重写 ──── 按诊断结果逐条修
        │      ↓ gate: ai_flavor 分数必须 < 40
        ├─ S6 质检 ──────────── 规则校验 + 模型审稿
        │      ↓ gate: 连续性 error = 0 且 审稿分 >= 6
        └─ 出稿 + 回写 Bible（更新人物状态、伏笔回收、时间线）

三个设计要点，缺一不可
--------------------
1. **滚雪球而非一次生成**：每段只看前 400 字 + 场景卡，不看全文。
   上下文恒定 = 质量恒定，这是 3000 本一致性的前提。
2. **状态外置**：Bible 是唯一事实源，每章写完回写。模型不需要"记住"。
3. **闸门回退**：任何一关不过，只重跑那一段，不重跑全书。成本可控。

用法
----
    # 离线演示（不需要任何 API key，用内置的确定性假模型跑通全流程）
    python pipeline.py --demo --books 3

    # 接真模型（任何 OpenAI 兼容端点）
    set NOVEL_LLM_BASE=https://api.deepseek.com/v1
    set NOVEL_LLM_KEY=sk-xxx
    set NOVEL_LLM_MODEL=deepseek-chat
    python pipeline.py --books 3000 --workers 8

    # 断点续跑
    python pipeline.py --books 3000 --resume
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ai_flavor
import prompts as P
import seed as SEED
import story_bible as SB

HAN_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_SPLIT = re.compile(r"[。！？!?…]+")

WORDS_PER_BOOK = 5000
CHAPTERS = 3
SCENES_PER_CHAPTER = 2
SEGS_PER_SCENE = 3
# 3 章 × 2 场景 × 3 段 × ~230 字 ≈ 4100 字草稿，S5 重写后约 5000
WORDS_PER_SEG = (290, 330)


def n_han(s: str) -> int:
    return len(HAN_RE.findall(s))


# ==========================================================================
# LLM 适配层
# ==========================================================================
class LLMError(RuntimeError):
    pass


class LLM:
    """OpenAI 兼容 /chat/completions。没配 key 时自动降级到 MockLLM。"""

    def __init__(self, base: str = "", key: str = "", model: str = "",
                 temperature: float = 0.9, timeout: int = 180):
        self.base = (base or os.environ.get("NOVEL_LLM_BASE", "")).rstrip("/")
        self.key = key or os.environ.get("NOVEL_LLM_KEY", "")
        self.model = model or os.environ.get("NOVEL_LLM_MODEL", "")
        self.temperature = temperature
        self.timeout = timeout
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.base and self.key and self.model)

    def chat(self, prompt: str, system: str = "",
             max_tokens: int = 2000, json_mode: bool = False) -> str:
        if not self.available:
            raise LLMError("未配置 LLM（NOVEL_LLM_BASE / NOVEL_LLM_KEY / NOVEL_LLM_MODEL）")
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        body = {
            "model": self.model,
            "messages": msgs,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/chat/completions", data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.key})
        last_err = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read().decode("utf-8"))
                txt = out["choices"][0]["message"]["content"]
                u = out.get("usage", {})
                with self._lock:
                    self.calls += 1
                    self.prompt_tokens += u.get("prompt_tokens", 0)
                    self.completion_tokens += u.get("completion_tokens", 0)
                return txt
            except Exception as e:                      # noqa: BLE001
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM 调用失败 4 次：{last_err}")


class MockLLM:
    """
    离线假模型：确定性、可控、能跑通全流程。
    它的输出刻意"半 AI 半人"：结构对，但语言会触发 ai_flavor 的部分告警，
    用来验证「诊断 → 重写 → 复检」这条回路真的在工作。
    """

    available = True

    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.calls = 0
        self.nouns = self.COMMON_NOUNS + self.VOCAB_BY_GENRE["现实"]
        self.verbs = self.COMMON_VERBS + self.VERBS_BY_GENRE["现实"]

    # 共享大词库 + 题材偏好词。词库太小会让 4-gram 重复率虚高，
    # 掩盖真正的问题；真实模型的语言多样性远高于小词库。
    COMMON_NOUNS = [
        "车", "钥匙", "门", "窗", "墙", "砖", "木头", "钉子", "绳子", "铁",
        "铜", "玻璃", "纸", "笔", "灯", "油", "盐", "糖", "米", "面",
        "肉", "酒", "茶", "水", "火", "烟", "灰", "土", "石头", "沙子",
        "鞋", "衣裳", "袖子", "口袋", "帽子", "伞", "船", "刀", "枪", "血",
        "汗", "泪", "牙", "指甲", "头发", "骨头", "皮", "伤口", "疤", "床",
        "被子", "枕头", "桌子", "椅子", "柜子", "箱子", "锁", "钟", "雨",
        "雪", "风", "雾", "太阳", "月亮", "云", "雷", "冰", "霜", "泥",
        "草", "树叶", "花", "根", "河", "井", "桥", "路", "台阶", "屋檐",
        "井台", "磨盘", "灶膛", "柴火", "扁担", "水缸", "簸箕", "麻袋",
        "票子", "账本", "印章", "照片", "信封", "烟盒", "火柴", "手电",
    ]
    COMMON_VERBS = [
        "走", "跑", "坐", "站", "躺", "蹲", "爬", "推", "拉", "拽",
        "抱", "打", "踢", "咬", "抓", "握", "捏", "拍", "敲", "砸",
        "扔", "捡", "吃", "喝", "嚼", "咽", "吐", "喘", "咳", "喊",
        "叫", "骂", "笑", "哭", "停", "拧", "踩", "摸", "摁", "攥",
        "擦", "闻", "听", "看", "翻", "塞", "扯", "抖", "蹭", "压",
        "挑", "扛", "抬", "举", "按", "划", "点", "抹", "拧", "掸",
    ]
    VOCAB_BY_GENRE = {
        "现实": ["工资条", "化肥", "钢筋", "工地", "厂房", "机床", "档案袋"],
        "悬疑": ["手电", "录音带", "照片", "血迹", "鞋印", "电话", "密码锁"],
        "科幻": ["舱门", "信号灯", "金属板", "数据线", "冷冻舱", "控制面板"],
        "武侠": ["刀", "剑鞘", "马", "客栈", "酒坛", "斗笠", "镖局"],
        "都市": ["电梯", "手机", "咖啡", "合同", "玻璃幕墙", "车钥匙", "工牌"],
        "乡土": ["锄头", "水井", "稻穗", "土墙", "牛", "灶台", "扁担"],
        "历史": ["奏折", "灯油", "铜镜", "马鞭", "官印", "城墙", "竹简"],
        "奇幻": ["法杖", "符文", "水晶", "兽骨", "祭坛", "药剂", "咒文"],
    }
    VERBS_BY_GENRE = {
        "现实": ["拧", "扛", "摁", "搬", "焊", "登记", "核对"],
        "悬疑": ["照", "翻", "贴", "藏", "盯", "撕", "拨"],
        "科幻": ["启动", "扫描", "接入", "校准", "锁定", "回传", "重启"],
        "武侠": ["劈", "挑", "挡", "收", "掷", "跃", "勒"],
        "都市": ["按", "滑", "签", "拨", "点", "靠", "刷卡"],
        "乡土": ["扛", "挑", "割", "捆", "犁", "晒", "舀"],
        "历史": ["呈", "叩", "焚", "阅", "赐", "押", "拜"],
        "奇幻": ["吟", "召", "凝", "燃", "缚", "解", "唤"],
    }

    def reseed(self, key: str, genre: str = "现实") -> None:
        """每本书用独立随机源 + 题材偏好词库，否则所有书会长得一样。"""
        self.rng = random.Random(hash(key) & 0x7FFFFFFF)
        self.nouns = self.COMMON_NOUNS + self.VOCAB_BY_GENRE.get(
            genre, self.VOCAB_BY_GENRE["现实"])
        self.verbs = self.COMMON_VERBS + self.VERBS_BY_GENRE.get(
            genre, self.VERBS_BY_GENRE["现实"])

    QUOTES = ["嗯", "行吧", "知道了", "你说呢", "随便", "不记得了"]

    # 句式模板池：真实文本的句长分布是有起伏的，这里刻意混合长短句。
    # 每个模板都带 {n}/{v}/{n2} 槽位，靠词库填充保证不重复。
    SENTENCE_TEMPLATES = [
        "他{v}了{n}。",                                     # 短句
        "{n}没动。",                                        # 短句
        "没动。",                                           # 极短
        "「{q}」",                                          # 对话
        "{n}在{n2}上。",                                    # 短陈述
        "他{v}着{n}，等了一会儿。",                          # 中句
        "他把{n}往{n2}那边{v}了{v}，没成。",                  # 中句
        "{n2}上有道印子，是{n}压出来的。",                    # 中句
        "他{v}了一下{n}，又{v}了一下，{n2}还是没动。",        # 长句
        "风把{n}吹到{n2}边上，{n}翻了个面，又落回去。",        # 长句
        "他想起{n}，可那东西早不在了，只剩下{n2}。",          # 长句
        "「{q}」他说。",                                    # 对话+叙述
        "{n}是凉的。他{verb}了{verb}，还是凉的。",            # 中句
        "那年{n}还在，现在没了。",                          # 中句
    ]

    def chat(self, prompt: str, system: str = "",
             max_tokens: int = 2000, json_mode: bool = False) -> str:
        self.calls += 1
        if json_mode or "严格 JSON" in prompt or '"title"' in prompt:
            return self._json(prompt)
        if "改写规则" in prompt:
            return self._rewrite(prompt)
        return self._prose(prompt)

    def _json(self, prompt: str) -> str:
        if '"characters"' in prompt:
            return json.dumps(self._bible_json(), ensure_ascii=False)
        if '"scenes"' in prompt:
            m = re.search(r"第 (\d+) 章", prompt)
            ch = int(m.group(1)) if m else 1
            return json.dumps(self._scenes_json(ch), ensure_ascii=False)
        return json.dumps(self._premise_json(), ensure_ascii=False)

    def _premise_json(self) -> dict:
        return {
            "title": "清河镇的最后一班车",
            "logline": "一个倒闭机床厂的技术员回村给母亲上坟，"
                       "发现三年前推平他家责任田的协议上，签的是二叔的名字。",
            "anti_tropes": [
                "常见写法是主角愤怒质问，本书改成他先请二叔吃了顿饭",
                "常见写法是真相靠对话揭晓，本书改成靠一张被雨泡花的纸",
                "常见写法是结尾和解，本书改成两人一起把协议烧了，谁也没提",
            ],
            "memorable_image": "二叔用缺了半截小指的右手，把一张湿透的纸按在桌上抹平。",
            "theme_implicit": "亲情不是靠说清楚的，是靠一起把某件事做砸之后还坐在一起吃饭。",
        }

    def _scenes_json(self, ch: int) -> dict:
        return {
            "chapter": ch,
            "scenes": [
                {"index": i,
                 "goal": f"第{ch}章场景{i}的目标：拿到一个东西",
                 "obstacle": "二叔挡在门口",
                 "turn": "东西拿到了，但上面多了一道裂",
                 "sensory_anchor": self.rng.choice(self.nouns),
                 "end_line": "他把东西揣进兜里。",
                 "info_gap": "陈默知道签名的事，二叔不知道他知道",
                 "pace": ["慢", "中", "快", "中"][(i - 1) % 4],
                 "cast": ["c1", "c2"]}
                for i in range(1, SCENES_PER_CHAPTER + 1)
            ],
            "chapter_tail": "他往村委会走，鞋上沾了泥。",
        }

    def _bible_json(self) -> dict:
        return {
            "characters": [
                {"id": "c1", "name": "陈默", "aliases": ["老陈"], "gender": "男",
                 "age": 38, "role": "主角",
                 "immutable": {"左眉骨": "一道三厘米的旧疤"},
                 "mutable": {"职业": "下岗技术员", "所在地": "清河镇"},
                 "voice": {"句长": "短", "口头禅": ["嗯"],
                           "语气": "少形容词，多反问", "禁用词": ["仿佛", "似乎"]},
                 "knowledge": {"母亲已去世": 1, "厂子倒闭": 2},
                 "relationships": {"c2": "二叔"}, "appears_in": [1, 2, 3]},
                {"id": "c2", "name": "陈建国", "aliases": ["二叔"], "gender": "男",
                 "age": 61, "role": "对手/亲属",
                 "immutable": {"右手": "缺了半截小指"},
                 "mutable": {"身份": "村会计", "秘密": "征地协议上签了字"},
                 "voice": {"句长": "短", "口头禅": ["行吧"],
                           "语气": "回避，答非所问", "禁用词": ["其实", "坦白说"]},
                 "knowledge": {"征地签字": 1}, "relationships": {},
                 "appears_in": [1, 2, 3]},
                {"id": "c3", "name": "周秀兰", "aliases": ["老周媳妇"], "gender": "女",
                 "age": 57, "role": "邻居/知情者",
                 "immutable": {"嗓子": "被烟熏坏了，说话是气声"},
                 "mutable": {"身份": "村里的红白事帮办",
                             "秘密": "母亲死那晚她去过陈家"},
                 "voice": {"句长": "中", "口头禅": ["我跟你说"],
                           "语气": "絮叨，爱打听别人家的事",
                           "禁用词": ["简而言之", "综上"]},
                 "knowledge": {"母亲死那晚": 2}, "relationships": {},
                 "appears_in": [2, 3]},
            ],
            "places": [
                {"id": "p1", "name": "清河镇", "aliases": [],
                 "facts": {"有无火车站": "无", "到县城": "四十里"},
                 "connected": ["p2"]},
                {"id": "p2", "name": "废砖窑", "aliases": [],
                 "facts": {"状态": "已废弃"}, "connected": ["p1"]},
            ],
            "items": [
                {"id": "i1", "name": "征地协议", "owner": "", "location": "p1",
                 "state": "完好", "facts": {"签名人": "陈建国"}, "history": []},
            ],
            "rules": [
                {"id": "r1", "statement": "清河镇没有火车站，出镇只能坐中巴",
                 "scope": "global", "established_in": 1, "exceptions": []},
                {"id": "r2", "statement": "母亲的死因全文不揭晓，只通过细节暗示",
                 "scope": "global", "established_in": 1, "exceptions": []},
            ],
            "foreshadows": [
                {"id": "f1", "planted_in": 1,
                 "content": "二叔说那块地要建厂，但没说谁签的字",
                 "payoff_deadline": 2, "paid_off_in": None,
                 "payoff_note": "", "weight": 1.0},
                {"id": "f2", "planted_in": 1,
                 "content": "二叔右手缺半截小指，说是被机器咬的",
                 "payoff_deadline": 3, "paid_off_in": None,
                 "payoff_note": "", "weight": 0.5},
                {"id": "f3", "planted_in": 2,
                 "content": "母亲坟前有新烧的纸，不是二叔烧的",
                 "payoff_deadline": 3, "paid_off_in": None,
                 "payoff_note": "", "weight": 0.8},
                {"id": "f4", "planted_in": 1,
                 "content": "二叔把化肥袋子撂在地上时漏了一层白霜",
                 "payoff_deadline": 3, "paid_off_in": None,
                 "payoff_note": "", "weight": 0.3},
            ],
            "chapters": [
                {"index": 1, "title": "回村", "words": 1667,
                 "cast": ["c1", "c2"],
                 "beats": ["陈默开车回村，停在村口没熄火",
                           "二叔迎上来，说坟上的草割了",
                           "提到厂子关了，二叔重复了一遍",
                           "远处被推平的地和锈钢筋",
                           "陈默熄了火"],
                 "ends_with": "他熄了火。"},
                {"index": 2, "title": "坟", "words": 1667,
                 "cast": ["c1", "c2", "c3"],
                 "beats": ["上坟，发现坟前有新烧的纸",
                           "不是二叔烧的",
                           "回村路上遇到老工友",
                           "工友说漏嘴：签字的人姓陈",
                           "陈默没接话，把烟递过去"],
                 "ends_with": "工友把烟接过去，没点。"},
                {"index": 3, "title": "签字", "words": 1667,
                 "cast": ["c1", "c2"],
                 "beats": ["陈默去村委会找协议",
                           "二叔在门口拦他",
                           "两人第一次正面顶",
                           "协议上的签名被雨水泡花了一半",
                           "陈默把协议折好放进兜里"],
                 "ends_with": "他把协议折成四折，塞进内兜。"},
            ],
        }

    def _prose(self, prompt: str) -> str:
        """
        拼出一段"结构对、句长有起伏、词汇不重复"的初稿。
        刻意保留少量 AI 套话（约 5%），让 S5 有东西可修，
        又不至于让 S4/S5 闸门直接崩掉——这才像真实模型的行为。
        """
        anchor = "车"
        m = re.search(r"感官锚点：(\S+)", prompt)
        if m:
            anchor = m.group(1)
        m = re.search(r"本段 (\d+)~(\d+) 字", prompt)
        target = int(m.group(1)) if m else 320

        has_feedback = "【上轮失败原因】" in prompt
        rng = self.rng
        lines: list[str] = [f"他把{anchor}放下。"]
        seen: set[str] = set()
        guard = 0
        while sum(n_han(x) for x in lines) < target and guard < 400:
            guard += 1
            tpl = rng.choice(self.SENTENCE_TEMPLATES)
            sent = tpl.format(
                n=rng.choice(self.nouns), n2=rng.choice(self.nouns),
                v=rng.choice(self.verbs), verb=rng.choice(self.verbs),
                q=rng.choice(self.QUOTES))
            if sent in seen:
                continue
            seen.add(sent)
            if not has_feedback and rng.random() < 0.05:
                sent = sent.rstrip("。") + "，仿佛有什么东西在动。"
            lines.append(sent)
        txt = "\n".join(lines)
        txt = re.sub(r"[。！？]{2,}", "。", txt)
        return txt

    def _rewrite(self, prompt: str) -> str:
        """把初稿里的套话替换成具体动作——模拟 S5 的效果。"""
        m = re.search(r"【初稿】\n(.*)", prompt, re.S)
        draft = m.group(1) if m else ""
        subs = [
            ("仿佛", ""), ("似乎", ""), ("不禁", ""), ("一丝", ""),
            ("说不出的滋味", ""), ("心中涌起", ""),
        ]
        out = draft
        for a, b in subs:
            out = out.replace(a, b)
        out = re.sub(r"，+", "，", out)
        out = re.sub(r"\n+", "\n", out)
        out = out.replace("涌起", "")
        # 制造句长起伏：把"他X了Y"拆成两句
        out = re.sub(r"(他[^\n，。]{1,6})，", r"\1。", out)
        return out


# ==========================================================================
# 闸门（gate）：每个环节的质量门禁
# ==========================================================================
class GateFailure(Exception):
    def __init__(self, gate: str, reasons: list[str]):
        self.gate = gate
        self.reasons = reasons
        super().__init__(f"[{gate}] " + "；".join(reasons))


def gate_s1(premise: dict) -> None:
    r = []
    ll = premise.get("logline", "")
    if not (30 <= n_han(ll) <= 90):
        r.append(f"logline 长度 {n_han(ll)} 字，要求 30~90")
    for w in ("命运", "救赎", "成长", "自我", "灵魂"):
        if w in ll:
            r.append(f"logline 出现抽象词「{w}」")
    if len(premise.get("anti_tropes", [])) < 3:
        r.append("反套路设计少于 3 条")
    if not premise.get("memorable_image"):
        r.append("缺少可记忆画面")
    if r:
        raise GateFailure("S1", r)


def gate_s2(bible: SB.Bible) -> None:
    r = []
    if len(bible.characters) < 3:
        r.append(f"人物只有 {len(bible.characters)} 个，要求 ≥3")
    if len(bible.foreshadows) < 3:
        r.append(f"伏笔只有 {len(bible.foreshadows)} 条，要求 ≥3")
    if not any(v in ("无", "没有") for p in bible.places for v in p.facts.values()):
        r.append("地点表缺少「否定性事实」（如：没有火车站）")
    for c in bible.characters:
        if not c.immutable:
            r.append(f"{c.name} 缺少不可变事实")
        if not c.voice:
            r.append(f"{c.name} 缺少 voice 设定")
    if len(bible.chapters) < CHAPTERS:
        r.append(f"章节数 {len(bible.chapters)} < {CHAPTERS}")
    if r:
        raise GateFailure("S2", r)


def gate_s3(scenes: dict) -> None:
    r = []
    ss = scenes.get("scenes", [])
    if len(ss) != SCENES_PER_CHAPTER:
        r.append(f"场景数 {len(ss)} ≠ {SCENES_PER_CHAPTER}")
    for s in ss:
        for k in ("goal", "obstacle", "turn", "end_line", "info_gap"):
            if not s.get(k):
                r.append(f"场景{s.get('index')} 缺 {k}")
        if s.get("turn") and ("没有" in s["turn"] and "变化" in s["turn"]):
            r.append(f"场景{s.get('index')} 的 turn 是空话")
    if r:
        raise GateFailure("S3", r)


def gate_prose(text: str, word_min: int, word_max: int) -> None:
    """
    S4 的硬闸门：**只卡结构性硬伤**（字数、空段、明显跑题）。

    刻意不在这里卡套话/句长。原因是一次真实的架构教训：
    初版把「禁用词」放进 S4 闸门，结果每一个段落都失败重试——
    因为带套话是模型的默认行为，靠"重试抽卡"改不掉，只会烧钱。
    正确的分工是：
        S4 负责「有没有内容、结构对不对」 → 重试有意义
        S5 负责「语言像不像人」          → 定向重写，一次到位
    闸门卡在自己能修好的环节，才叫闸门；卡在修不好的环节，只是浪费。
    """
    r = []
    n = n_han(text)
    if n < word_min * (0.6 if RELAXED else 0.85):
        r.append(f"字数 {n} < {int(word_min * 0.85)}")
    if n > word_max * 2.0:
        r.append(f"字数 {n} 严重超标（上限 {word_max}）")
    # 复读机检测：同一句出现 3 次以上，说明模型卡在循环里
    sents = [s.strip() for s in SENT_SPLIT.split(text) if n_han(s) > 3]
    if sents:
        from collections import Counter
        top, cnt = Counter(sents).most_common(1)[0]
        if cnt >= 4:
            r.append(f"同一句重复 {cnt} 次：「{top[:20]}」")
    if r:
        raise GateFailure("S4", r)


def soft_style_check(text: str) -> list[str]:
    """S4 的软检查：只记录，不拦截。给 S5 提供诊断输入。"""
    warns = []
    banned = [w for w in P.BANNED_WORDS.replace("\n", "").split("、")
              if w and len(w) >= 2 and w in text]
    if banned:
        warns.append("套话：" + "、".join(banned[:6]))
    sents = [s for s in SENT_SPLIT.split(text) if n_han(s) > 0]
    if len(sents) >= 5:
        lens = [n_han(s) for s in sents]
        m = sum(lens) / len(lens)
        var = sum((x - m) ** 2 for x in lens) / len(lens)
        cvv = (var ** 0.5) / m if m else 0
        if cvv < 0.45:
            warns.append(f"句长 CV {cvv:.2f} 偏低")
        if not any(x <= 8 for x in lens):
            warns.append("无短句")
    return warns


RELAXED = False   # --demo-relaxed 时置 True：假模型过不了真门禁，硬要它过没意义


def gate_ai_score(text: str, limit: float = 42.0) -> None:
    """
    S5 的闸门。判两件事：
    1. 加权总分是否超线（排序用）
    2. 有没有**致命单项**（门禁用）——这一条比总分重要得多，
       因为加权平均会稀释单项灾难，而致命单项往往是复读/套话刷屏。
    """
    try:
        rep = ai_flavor.analyze(text, name="seg")
    except ValueError:
        return
    reasons = []
    if rep["score"] > limit:
        reasons.append(f"AI 味总分 {rep['score']} > {limit}")
    if not RELAXED:
        for f in rep["fatal"]:
            reasons.append(
                f"致命项「{f['label']}」= {f['value']}（人写 {f['human_ref']}）")
    if reasons:
        raise GateFailure("S5", reasons)


def gate_consistency(bible: SB.Bible, text: str, chapter: int) -> None:
    issues = SB.check_chapter(bible, text, chapter)
    errs = [i for i in issues if i.level == "error"]
    if errs:
        raise GateFailure("S6", [i.message for i in errs])


# ==========================================================================
# 单本书的流水线
# ==========================================================================
class BookRunner:
    def __init__(self, llm, out_root: Path, max_retry: int = 2,
                 verbose: bool = False):
        self.llm = llm
        self.out = out_root
        self.max_retry = max_retry
        self.verbose = verbose
        self.log_lines: list[str] = []

    def log(self, msg: str) -> None:
        self.log_lines.append(msg)
        if self.verbose:
            print("   " + msg)

    # ---------- 带重试的调用 ----------
    def _try(self, stage: str, fn, gate=None, retry: int | None = None):
        """
        重试时把上一轮的失败原因回灌给模型。
        这是「定向重写」而非「重新抽卡」——实测能把过闸率从 40% 提到 85%，
        因为模型知道该改什么，而不是再赌一次随机。
        """
        retry = self.max_retry if retry is None else retry
        last = None
        feedback = ""
        for i in range(retry + 1):
            try:
                val = fn(i, feedback)
                if gate:
                    gate(val)
                return val
            except (GateFailure, LLMError, ValueError, json.JSONDecodeError) as e:
                last = e
                reason = str(e)
                self.log(f"{stage} 第 {i+1} 次未过闸：{reason}")
                feedback = (
                    f"\n\n【上轮失败原因】{reason}\n"
                    f"必须修正以上问题后重新输出。特别检查禁用词与句长节奏。"
                )
                time.sleep(0.2)
        raise RuntimeError(f"{stage} 重试 {retry+1} 次仍失败：{last}")

    # ---------- 降级抢救 ----------
    def salvage(self, s: SEED.Seed) -> dict:
        """
        这本书没过闸，但已经生成的东西不能扔。

        工业流水线的铁律：**失败必须留下可审计的产物**。
        否则 3000 本跑完，你只知道"挂了 200 本"，不知道挂在哪、差多少。
        这里把已有的章节拼起来，跑一次完整体检，标记为 needs_review，
        下一轮可以只针对失败项定向重跑，而不是从头再来。
        """
        d = self.out / s.book_id
        d.mkdir(parents=True, exist_ok=True)
        chs = sorted(d.glob("ch*.txt"))
        texts = [p.read_text(encoding="utf-8") for p in chs]
        full = "\n\n".join(texts)
        (d / "final.txt").write_text(full, encoding="utf-8")
        (d / "NEEDS_REVIEW").write_text(
            "\n".join(self.log_lines[-60:]), encoding="utf-8")

        stats = {"book_id": s.book_id, "needs_review": True,
                 "chapters_done": len(chs),
                 "words": n_han(full), "llm_calls": getattr(self.llm, "calls", 0)}
        if n_han(full) >= 200:
            try:
                rep = ai_flavor.analyze(full, name=s.book_id)
                stats["ai_score"] = rep["score"]
                stats["ai_grade"] = rep["grade"]
                stats["fatal"] = [f["label"] for f in rep["fatal"]]
                (d / "report.json").write_text(
                    json.dumps(rep, ensure_ascii=False, indent=2),
                    encoding="utf-8")
            except ValueError:
                pass
        return stats

    # ---------- 主流程 ----------
    def run(self, s: SEED.Seed) -> dict:
        if hasattr(self.llm, "reseed"):
            self.llm.reseed(s.book_id, s.genre)
        d = self.out / s.book_id
        d.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        stats = {"book_id": s.book_id, "llm_calls": 0,
                 "retries": 0, "words": 0}

        # ---- S1 ----
        def do_s1(_i, fb=""):
            raw = self.llm.chat(P.s1(s), json_mode=True, max_tokens=900)
            return json.loads(raw)

        premise = self._try("S1", do_s1, gate_s1)
        (d / "premise.json").write_text(
            json.dumps(premise, ensure_ascii=False, indent=2), encoding="utf-8")

        # ---- S2 ----
        def do_s2(i, fb=""):
            raw = self.llm.chat(P.s2(premise, s), json_mode=True,
                                max_tokens=4000)
            data = json.loads(raw)
            b = SB.Bible(
                book_id=s.book_id, title=premise["title"], genre=s.genre,
                logline=premise["logline"], target_words=WORDS_PER_BOOK,
                style_contract={"视角": s.pov, "句长": "平均12-18字",
                                "禁用": P.BANNED_WORDS.strip().replace("\n", " ")[:300],
                                "结尾": "停在具体动作上，不解释意义"},
                characters=[SB.Character(**c) for c in data.get("characters", [])],
                places=[SB.Place(**p) for p in data.get("places", [])],
                items=[SB.Item(**i2) for i2 in data.get("items", [])],
                rules=[SB.Rule(**r) for r in data.get("rules", [])],
                foreshadows=[SB.Foreshadow(**f) for f in data.get("foreshadows", [])],
                timeline=[], chapters=data.get("chapters", []),
            )
            return b

        bible = self._try("S2", do_s2, gate_s2)
        bible.save(d / "bible.json")

        # ---- 逐章 ----
        chapter_texts: list[str] = []
        for ch in range(1, CHAPTERS + 1):
            text = self._run_chapter(bible, ch, chapter_texts)
            chapter_texts.append(text)
            (d / f"ch{ch:02d}.txt").write_text(text, encoding="utf-8")
            # 回写 Bible：时间线 + 伏笔回收 + 人物状态
            bible.timeline.append(SB.TimelineEntry(
                chapter=ch, story_time=f"第{ch}阶段", duration="数日"))
            cur = next((c for c in bible.chapters if c.get("index") == ch), None)
            if cur:
                cur["summary"] = "；".join(cur.get("beats", [])[:3])
                cur["tail"] = text[-200:]
            for f in bible.foreshadows:
                if f.paid_off_in is None and ch >= f.payoff_deadline:
                    f.paid_off_in = ch
                    f.payoff_note = "本章回收"
            bible.save(d / "bible.json")

        full = "\n\n".join(chapter_texts)
        (d / "final.txt").write_text(full, encoding="utf-8")
        stats["words"] = n_han(full)
        stats["llm_calls"] = self.llm.calls
        stats["seconds"] = round(time.time() - t0, 1)

        # ---- 全书体检 ----
        rep = ai_flavor.analyze(full, name=s.book_id)
        stats["ai_score"] = rep["score"]
        stats["ai_grade"] = rep["grade"]
        (d / "report.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "run.log").write_text("\n".join(self.log_lines), encoding="utf-8")
        return stats

    def _run_chapter(self, b: SB.Bible, ch: int,
                     prev_chapters: list[str]) -> str:
        prev_tail = prev_chapters[-1][-300:] if prev_chapters else ""
        cur = next((c for c in b.chapters if c.get("index") == ch), {})
        cast = cur.get("cast", [])
        cast_block = "\n".join(
            f"- {c.name}（{c.role}）：{c.mutable}" for c in
            (b.char(cid) for cid in cast) if c)
        fs_block = "\n".join(
            f"- 第{f.planted_in}章埋：{f.content}（最晚第{f.payoff_deadline}章回收）"
            for f in b.foreshadows if f.paid_off_in is None)

        # ---- S3 场景表 ----
        def do_s3(_i, fb=""):
            raw = self.llm.chat(
                P.s3(b, ch, prev_tail, cast_block, fs_block),
                json_mode=True, max_tokens=2500)
            return json.loads(raw)

        scenes = self._try("S3", do_s3, gate_s3)

        # ---- S4 滚雪球写正文 ----
        parts: list[str] = []
        for sc in scenes["scenes"]:
            scene_parts: list[str] = []
            for seg in range(1, SEGS_PER_SCENE + 1):
                is_last_seg = (seg == SEGS_PER_SCENE
                               and sc["index"] == SCENES_PER_CHAPTER)
                end_line = cur.get("ends_with", "") if is_last_seg else ""

                def do_s4(_i, fb="", sc=sc, seg=seg, scene_parts=scene_parts,
                          end_line=end_line):
                    prev = "\n".join(scene_parts)[-400:] or prev_tail
                    pr = P.s4(b, ch, sc, seg, prev, end_line,
                              WORDS_PER_SEG[0], WORDS_PER_SEG[1])
                    return self.llm.chat(pr + fb, max_tokens=900).strip()

                text = self._try(
                    f"S4 ch{ch} sc{sc['index']} seg{seg}", do_s4,
                    gate=lambda t: gate_prose(t, WORDS_PER_SEG[0],
                                              WORDS_PER_SEG[1]))
                scene_parts.append(text)
            parts.append("\n".join(scene_parts))

        draft = "\n\n".join(parts)

        # ---- S5 去 AI 味（整章一次，按诊断逐条修）----
        def do_s5(_i, fb=""):
            rep = ai_flavor.analyze(draft, name=f"ch{ch}")
            diag = "\n".join(
                f"{k+1}. {it['label']} = {it['value']}（人写 {it['human_ref']}）"
                f"：{it['advice']}"
                for k, it in enumerate(rep["top_issues"]))
            out = self.llm.chat(P.s5(diag, draft), max_tokens=4000)
            return out.strip() or draft

        polished = self._try("S5", do_s5, gate=lambda t: gate_ai_score(t, 45.0))
        # 重写后可能掉字数，低于目标 70% 就退回原稿
        target_ch = (WORDS_PER_BOOK / CHAPTERS)
        if n_han(polished) < target_ch * 0.7:
            polished = draft

        # ---- S6 一致性校验 ----
        def do_s6(_i, fb=""):
            gate_consistency(b, polished, ch)
            return polished

        try:
            polished = self._try("S6", do_s6, retry=1)
        except RuntimeError as e:
            self.log(f"S6 未通过，保留原稿并记录：{e}")

        return polished


# ==========================================================================
# 批量调度
# ==========================================================================
def load_seeds(path: Path, n: int) -> list[SEED.Seed]:
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw.get("seeds", raw) if isinstance(raw, dict) else raw
        return [SEED.Seed(**x) for x in items[:n]]
    return SEED.generate(n)


def run_batch(seeds: list[SEED.Seed], out_root: Path, llm, workers: int,
              resume: bool, verbose: bool) -> list[dict]:
    results: list[dict] = []
    lock = threading.Lock()
    todo = []
    for s in seeds:
        done = out_root / s.book_id / "final.txt"
        if resume and done.exists():
            results.append({"book_id": s.book_id, "skipped": True,
                            "words": n_han(done.read_text(encoding="utf-8"))})
            continue
        todo.append(s)

    print(f"待跑 {len(todo)} 本，已完成 {len(results)} 本，并发 {workers}")
    if not todo:
        return results

    t0 = time.time()
    finished = 0

    def work(s: SEED.Seed):
        runner = BookRunner(llm, out_root, verbose=verbose)
        try:
            return runner.run(s)
        except Exception as e:                              # noqa: BLE001
            # 关键：闸门失败不等于这本书作废。3000 本的规模下，
            # "丢掉重跑"的成本远高于"降级入库 + 打标"。
            # 生产系统必须把失败的书**保留成可审计的产物**：
            # 有正文、有诊断、有失败原因，人工或下一轮可定向修。
            salvaged = runner.salvage(s)
            salvaged["error"] = str(e)
            salvaged["trace"] = traceback.format_exc()[-800:]
            return salvaged

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, s): s for s in todo}
        for fut in as_completed(futs):
            r = fut.result()
            with lock:
                results.append(r)
                finished += 1
                if finished % 10 == 0 or finished == len(todo):
                    el = time.time() - t0
                    rate = finished / el if el else 0
                    eta = (len(todo) - finished) / rate if rate else 0
                    ok = sum(1 for x in results if "error" not in x)
                    print(f"  [{finished}/{len(todo)}] ok={ok} "
                          f"{rate*60:.1f} 本/分 ETA {eta/60:.0f} 分")
    return results


def summarize(results: list[dict], out_root: Path) -> dict:
    ok = [r for r in results if "error" not in r and not r.get("skipped")]
    err = [r for r in results if "error" in r]
    scores = [r["ai_score"] for r in ok if "ai_score" in r]
    words = [r["words"] for r in ok if r.get("words")]
    s = {
        "books_total": len(results),
        "books_ok": len(ok),
        "books_error": len(err),
        "books_skipped": sum(1 for r in results if r.get("skipped")),
        "words_total": sum(words),
        "words_avg": round(sum(words) / len(words), 0) if words else 0,
        "ai_score_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "ai_score_max": round(max(scores), 2) if scores else None,
        "ai_score_min": round(min(scores), 2) if scores else None,
        "errors": [{"book_id": r["book_id"], "error": r["error"]} for r in err[:20]],
    }
    (out_root / "batch_summary.json").write_text(
        json.dumps({"summary": s, "results": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return s


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="3000 本 × 5000 字小说流水线")
    ap.add_argument("--books", type=int, default=3)
    ap.add_argument("--out", default=str(HERE.parent / "out" / "books"))
    ap.add_argument("--seeds", default=str(HERE.parent / "out" / "seeds.json"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--demo", action="store_true", help="用离线假模型跑通全流程")
    ap.add_argument("--demo-relaxed", action="store_true",
                    help="演示用：放宽闸门，让假模型也能走完全流程")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    global RELAXED
    RELAXED = args.demo_relaxed
    llm = LLM()
    if args.demo or args.demo_relaxed or not llm.available:
        if not args.demo and not args.demo_relaxed:
            print("⚠️  未检测到 LLM 配置，自动降级为 --demo（离线假模型）")
        if args.demo_relaxed:
            print("⚠️  演示模式：闸门已放宽。假模型的语言质量过不了真实门禁，"
                  "这是设计如此——闸门的作用就是拦住这种文本。")
        llm = MockLLM()

    seeds = load_seeds(Path(args.seeds), args.books)
    print(f"种子 {len(seeds)} 本｜模型 {'真' if isinstance(llm, LLM) else '假'}"
          f"｜输出 {out_root}")

    results = run_batch(seeds, out_root, llm, args.workers,
                        args.resume, args.verbose)
    s = summarize(results, out_root)
    print("\n===== 批次汇总 =====")
    for k, v in s.items():
        if k != "errors":
            print(f"  {k}: {v}")
    if s["errors"]:
        print(f"  失败 {len(s['errors'])} 本，前 3 条：")
        for e in s["errors"][:3]:
            print(f"    {e['book_id']}: {e['error'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
