#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
outline.py —— 四层大纲（第 2~5 步，一次建完）

为什么大纲必须确定性生成，而不是让模型生成
========================================

5000 章的大纲，如果每章调一次模型：

    5000 次调用 × 每次 1500 tokens ≈ 750 万 tokens，且互相不一致

更致命的是**一致性问题**：模型不知道第 3000 章需要呼应第 100 章，
因为它没有那个记忆。它只会写一个"看起来合理"的章纲。

所以正确分工是：

    确定性代码：生成 5000 章骨架（免费、瞬间、绝对一致）
    模型：      只在真正写那一章时，把骨架扩成 4000 字正文

**模型不参与规划，只参与执行。** 这是 2000 万字可行的前提。

关键工程问题：确定性 ≠ 模板化
==========================

第一版我用 20×20 的标题词库 + 64 个 beat 模板，结果：

    5000 章只有 20 个唯一标题（每个重复 250 次）
    20000 个 beat 只有 138 个唯一值（每个重复 500 次）

校验居然"通过"了，因为阈值设得太松。**这是最危险的失败模式：
数据烂到没法读，但测试全绿。**

修法的核心是**组合空间必须 ≥ 需求**：

    标题：需要 ≥5000 种 → 用 3 段 × 每段 20 词 = 8000 种
    beat：需要 ≥20000 条 → 用「模板 × 施动者 × 受动者 × 物件 × 地点」
          五元组组合，空间是 64 × 8 × 8 × 12 × 6 ≈ 30 万种

确定性来自"章号 → 五元组的唯一映射"，而不是"从固定池里挑"。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import characters as CH
import worldbuild as WB


# ==========================================================================
# 一、六幕（全书总纲）
# ==========================================================================
ACTS = [
    {
        "no": 1, "name": "第一幕 · 铁匠之子",
        "start": 1, "end": 400,
        "conflict": "活下去。父亲欠债，妹妹病重，镇上有修士收保护费。",
        "irreversible": "林昭踏入修行，再也回不去做凡人。妹妹的时间开始倒数。",
        "escalates": "从「没有力量」到「有力量但保护不了想保护的人」",
    },
    {
        "no": 2, "name": "第二幕 · 人界之巅",
        "start": 401, "end": 1600,
        "conflict": "打得过所有人，却打不过时间。妹妹老死，师父失踪。",
        "irreversible": "林昭亲手送走妹妹，人界再无可恋，只剩飞升一条路。",
        "escalates": "从「打不过」到「打不得」——敌人是他不能杀的人",
    },
    {
        "no": 3, "name": "第三幕 · 灵界蝼蚁",
        "start": 1601, "end": 3000,
        "conflict": "绝对战力还在，但界壁把他压成最底层。旧身份一文不值。",
        "irreversible": "苏见月身死。林昭第一次为了复仇而修行，而不是为了守护。",
        "escalates": "从「守护」到「复仇」——动机变了，人也就变了",
    },
    {
        "no": 4, "name": "第四幕 · 仙界无位",
        "start": 3001, "end": 4200,
        "conflict": "仙位有限，得夺。夺来的仙位带着别人的因果。",
        "irreversible": "白蘅消散。林昭继承了她的仙位，也继承了追杀她的所有人。",
        "escalates": "从「复仇」到「背负」——他要背的不再是自己的仇",
    },
    {
        "no": 5, "name": "第五幕 · 神界叛徒",
        "start": 4201, "end": 4600,
        "conflict": "师父沈鹤年是叛神。他一直在等林昭来杀他。",
        "irreversible": "林昭亲手杀了沈鹤年。他成了自己最恨的那种人。",
        "escalates": "从「背负」到「背叛」——他开始怀疑自己站的那一边",
    },
    {
        "no": 6, "name": "第六幕 · 神主",
        "start": 4601, "end": 5000,
        "conflict": "神格唯一。要成神主，必须杀掉前任——而前任是法则本身。",
        "irreversible": "林昭成为神主，然后废掉神格。四界重归凡人可及。",
        "escalates": "从「成为法则」到「废掉法则」——他放弃了唯一的答案",
    },
]


# ==========================================================================
# 二、词汇矩阵（组合空间的设计）
# ==========================================================================
# 标题：3 段 × 20 词 = 8000 种组合 > 5000 章需求

T_A = ["归", "断", "渡", "焚", "锁", "锈", "雪", "井", "债", "碑",
       "灰", "潮", "隙", "影", "钉", "釉", "茧", "痕", "烬", "岸"]
T_B = ["刀", "骨", "灯", "门", "河", "印", "信", "药", "绳", "镜",
       "瓦", "钟", "鞘", "阶", "痂", "窗", "薪", "锤", "函", "坝"]
T_C = ["记", "书", "帖", "录", "图", "约", "誓", "契", "传", "谱",
       "简", "册", "铭", "辞", "赋", "引", "志", "笺", "檄", "诰"]
# 第 4 段：把组合空间从 8000 提到 160000，满足 5000 章的生日悖论需求
T_D = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
       "上", "下", "前", "后", "旧", "新", "残", "断", "半", "重"]

# beat 五元组：动作 × 施动者 × 受动者 × 物件 × 地点
# 组合空间 = 16 动作 × 8 施动 × 8 受动 × 12 物件 × 6 地点 ≈ 73 万
# 20000 个 beat 需要不重复 → 空间绰绰有余

B_ACT = {
    "冲突": ["挡住", "推开", "按住", "摔碎", "夺走", "拆开"],
    "揭示": ["说出", "摊开", "认出", "念出", "撕开", "点破"],
    "代价": ["烧掉", "押上", "割下", "交出", "砸烂", "埋掉"],
    "转折": ["放下", "退回", "钉死", "折好", "留住", "推回"],
}

# 物件分类 + 分类动词表。
#
# 踩过的坑：初版是「动作表 × 物件表」全笛卡尔积，于是生成了
# 「林昭·再割下·烧焦的账本上的印」「林小满·才摔碎·账本上的印」——
# 语法通，语义荒谬。模型拿到这种要点只能硬写，写出来就是硬伤。
#
# 修法：先给每个物件归一个材质类，再从**该类**的动词表里选。
# 这样「纸」类永远配 拆开/撕开/摊开/折好/烧掉/按住，
# 不会出现「摔碎一封信」。
OBJ_CLASS = {
    "那盏灯": "器", "半张契": "纸", "一把锈刀": "铁",
    "母亲的铜镜": "铁", "断了的指骨": "遗", "写了一半的信": "纸",
    "过期的药": "药", "一枚旧印": "印", "一截麻绳": "绳",
    "烧焦的账本": "纸", "带血的布": "布", "一块碎瓦": "瓦",
}

ACT_BY_CLASS = {
    "纸": ["拆开", "撕开", "摊开", "折好", "烧掉", "按住",
           "翻过来", "卷起来", "交出去", "收进袖"],
    "铁": ["按住", "夺走", "推开", "擦净", "收进袖", "掂了掂",
           "翻过来", "举起来", "搁下", "攥紧"],
    "器": ["按住", "推开", "拨亮", "擦净", "挪开", "收起来",
           "搁下", "举起来", "罩住", "吹灭"],
    "药": ["拆开", "退回", "封好", "倒出", "收起", "捏碎",
           "摊开", "收进袖", "搁下", "数了数"],
    "印": ["按住", "认出", "翻过来", "拓下", "扣住", "收起",
           "举起来", "擦净", "对着灯看", "搁下"],
    "绳": ["解开", "系紧", "割断", "缠上", "扯松", "收起",
           "绕上", "剪断", "塞进袖", "搁下"],
    "布": ["摊开", "叠好", "撕开", "裹上", "按住", "收起",
           "掀开", "打结", "搁下", "揣进怀"],
    "瓦": ["捡起", "放下", "砸碎", "翻过来", "按住", "收起",
           "踢开", "比了比", "搁下", "推走"],
    "遗": ["收起", "埋掉", "放下", "握紧", "藏起", "交回",
           "包好", "搁下", "举起来", "擦净"],
}

B_DOER = ["林昭", "沈鹤年", "苏见月", "陆无咎", "白蘅", "天枢", "林小满", "玄冥"]
B_OBJ = ["那盏灯", "半张契", "一把锈刀", "母亲的铜镜", "断了的指骨",
         "写了一半的信", "过期的药", "一枚旧印", "一截麻绳",
         "烧焦的账本", "带血的布", "一块碎瓦"]
B_PLACE = ["渡口", "旧屋", "祠堂", "崖边", "雪地里", "灯下"]
# 第 6 维：修饰词。把 beat 空间从 13824 提到 138240，
# 满足 20000 个 beat 需要 85% 唯一（生日悖论要求空间 ≥120000）
B_MOD = ["先", "又", "才", "没", "再", "还是", "终究", "反倒",
         "一声不响地", "当着所有人的面"]

# 句式骨架（16 个位置 × 4 变体 = 64）
# 同样铁律：全部占位符必须出现，否则不同变量塌缩成同一句
# 铁律二：地点必须带「在」，且不能重复
#
# ⚠️ 重要（第 3 轮修正）：
# 这 10 个骨架**只用于内部唯一性校验**，绝不进 prompt。
# 原因：模板写不出合格的中文。实测「{obj}被{doer}{mod}{act}，在{place}」
# 会生成「烧焦的账本被林小满反倒交出，在雪地里」——「被……反倒交出」
# 不合语法，「在雪地里」悬空。
# 更糟的是：初版 prompt 让模型「本段要落在这个 beat 上」「结尾停在这句上」，
# 模型就真的把这些病句原样抄进正文。
# 现在改成：大纲只产出**要点**（Beat.spec），句子一律由正文层自己写。
B_FRAME = [
    "{doer}{mod}{act}{obj}，在{place}，没人说话。",
    "在{place}，{doer}{mod}{act}{obj}。",
    "{doer}把{obj}{mod}{act}，站在{place}。",
    "{obj}被{doer}{mod}{act}，在{place}。",
    "{doer}{mod}把{obj}{act}，在{place}，谁都没拦。",
    "在{place}，{obj}{mod}被{doer}{act}，没人敢看。",
    "{doer}在{place}{mod}{act}{obj}，手没抖。",
    "{obj}在{place}{mod}被{doer}{act}，一声没吭。",
    "{doer}{mod}{act}{obj}的时候，{place}只有风。",
    "在{place}，{doer}把{obj}{mod}{act}，转身就走。",
]

# 旁人的反应。这是 beat 里真正带"戏"的那一维：
# 动作本身是信息，旁人的反应才是压力。
B_TWIST = ["没人说话", "谁都没拦", "手没抖", "一声没吭", "没人敢看",
           "谁都没动", "没人接话", "谁也没问", "没人抬头", "谁也没让"]

# 卷级「这一卷到底卡在哪」。给卷一个贯穿的问题，章才不会各说各话。
VOL_PROBLEM = [
    "东西是真的，但来路说不清",
    "有人先一步动过手，痕迹还在",
    "拿得到，但拿走就得罪人",
    "代价已经付过一次，不能再付",
    "答案在死人手里，活人不敢提",
    "两方各有一半凭证，缺一不可",
    "找到了，但已经被抵押出去",
    "追到最后发现是自家人设的局",
]

# 弧级「这一弧盯的是物件的哪个部位」。
#
# 只靠卷级线索还不够：一个卷 50 章全在写「烧焦的账本」，
# 读者到第 30 章会腻。所以每 10 章换一个"看这件东西的角度"：
# 先看本体，再看背面，再看上面的字，再看缺的那一角……
# 物件没换（因果链不断），焦点换了（不腻）。
OBJ_ASPECT = ["", "的背面", "的边缘", "上的字", "上的印",
              "的另一半", "缺的那一角", "的来路"]


# 结尾句：必须是具体动作，不能是总结
# 铁律：每个模板必须包含**全部**占位符 {doer}{obj}{place}{mod}。
# 踩过的坑：初版有些模板只含 {doer}（如「{doer}数了数还剩几个人。」），
# 于是 obj/place/mod 虽然算了却没进文本，不同章塌缩成同一句——
# 16 个模板 × 3 个 doer = 48 种输出，5000 章必然重复 100 次。
END_FRAME = [
    "{doer}把{obj}收进袖子里，{mod}没看{place}一眼。",
    "{doer}{mod}转身走了，{obj}留在{place}。",
    "{place}的门{mod}关上了，{doer}手里还攥着{obj}。",
    "{doer}的手{mod}停在半空，{obj}掉在{place}。",
    "{place}的灯{mod}灭了，{doer}没去捡{obj}。",
    "{doer}{mod}没有回头，{obj}还在{place}。",
    "{doer}把{obj}留在{place}，{mod}走了。",
    "{obj}上沾了血，{mod}没人擦，{doer}站在{place}。",
    "{doer}在{place}数了数，{mod}把{obj}收了起来。",
    "{place}的路{mod}还长，{doer}把{obj}揣好。",
    "{doer}把那句话咽了回去，{mod}捏紧了{obj}。",
    "{obj}还在{place}，{mod}没人去捡，{doer}也没动。",
    "{doer}看了一眼{obj}，{mod}走了，没回头。",
    "{place}，{doer}蹲下来，{obj}{mod}没拿。",
    "{doer}把{obj}折好放进内兜，{mod}离开了{place}。",
    "{obj}在{place}放了很久，{mod}没人动，{doer}也没来。",
    "{doer}{mod}踩灭了烟，{obj}扔在{place}。",
    "{place}只剩下{obj}，{doer}{mod}走了。",
    "{doer}抹了把脸，{mod}把{obj}塞进{place}的缝里。",
    "{obj}硌着手，{doer}{mod}没松，{place}很静。",
]


# ==========================================================================
# 三、确定性映射（核心）
# ==========================================================================

def _h(*parts) -> int:
    """
    稳定 hash：同一组输入永远得到同一个数。

    **踩过的坑（这是本文件最重要的一处修复）：**
    初版用朴素 FNV-1a：

        h = 2166136261
        for ch in str(p):
            h ^= ord(ch); h = (h * 16777619) & 0xFFFFFFFF
        return h % size

    结果 5000 章只生成了 45 个唯一标题（应接近 5000）。

    原因：**FNV-1a 的低位分布极差**——它的低位周期很短。
    而 `% 20`、`% 12` 这类小模数恰好只用到低位，
    于是所有章号都塌缩到少数几个桶里。

    修法：加一步 finalizer（splitmix64 风格的雪崩混合），
    让高位也参与进来。这是哈希表实现里的标准做法。

    教训：**确定性 ≠ 随便写个 hash**。分布不好，组合空间再大也没用。
    """
    h = 2166136261
    for p in parts:
        for ch in str(p):
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
    # ---- splitmix64 finalizer：雪崩混合，修复低位偏差 ----
    h ^= h >> 16
    h = (h * 0x7FEB352D) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 0x846CA68B) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def _idx(n: int, *parts, size: int) -> int:
    return _h(n, *parts) % size


def make_title(no: int) -> str:
    """
    4 段组合，20^4 = 160000 种空间。

    为什么需要这么大：生日悖论下，要从 N 种里抽 5000 次得到 90% 唯一，
    N 至少要 50000。20^3=8000 只有 74% 唯一率（实测），20^4 才够。
    """
    a = T_A[_idx(no, "a", size=len(T_A))]
    b = T_B[_idx(no, "b", size=len(T_B))]
    c = T_C[_idx(no, "c", size=len(T_C))]
    d = T_D[_idx(no, "d", size=len(T_D))]
    return f"{a}{b}{c}{d}"


def vol_thread(vno: int, cast_names: dict) -> dict:
    """
    卷级线索。这是「故事讲得通」的关键。

    踩过的坑：初版每章的物件是全局按章号哈希抽的，于是
    第 1 章在追母亲的铜镜，第 2 章突然变成「一块碎瓦」「半张契」，
    第 3 章又变成「写了一半的信」。结构节奏是对的，但没有任何
    因果关系——读者会觉得"作者在随机换道具"。

    修法：一个卷（默认 50 章）只认一条线索，卷内所有章的 beat
    都围绕同一个「目标物」和同一个「主场景」展开。物件只在卷边界换。
    这正是长篇连载的实际写法：几十章解决一件事。

    地点按弧（默认 10 章）轮换，让卷内还有推进感。
    """
    obj = B_OBJ[_idx(vno, "thread_obj", size=len(B_OBJ))]
    return {
        "obj": obj,
        "obj_base": obj,
        "obj_clean": obj.replace("那", "").replace("的", "的"),
        "foe": list(cast_names.values())[
            _idx(vno, "thread_foe", size=len(cast_names))],
        "place0": B_PLACE[_idx(vno, "thread_place", size=len(B_PLACE))],
        "problem": VOL_PROBLEM[_idx(vno, "thread_prob", size=len(VOL_PROBLEM))],
    }


def make_beat(no: int, kind: str, bi: int, cast_names: dict,
              thread: dict | None = None,
              arc_place: str | None = None) -> tuple[str, list[str], str]:
    """
    组合生成 beat。返回 (文本, 涉及角色id, 要点)。

    - 文本：只用于唯一性校验和人工审读，**不进 prompt**（模板中文不通顺）。
    - 要点：进 prompt。用「·」「｜」分隔，故意不写成句子，
      这样模型没法照抄，只能自己组织语言。

    传了 `thread` 就用卷级线索里的物件（保证卷内因果连贯），
    否则退回全局哈希（老行为，保留给测试）。

    空间：6 动作 × 8 施动 × 6 地点 × 10 修饰 × 10 旁人反应 = 28800/类型，
    远大于每卷 200 个 beat 的需求。
    """
    acts = B_ACT[kind]
    acts_by_kind = acts
    act = acts[_idx(no, kind, "act", bi, size=len(acts))]

    # 施动者从在场角色里选（保证人物在场正确）
    doers = list(cast_names.values())
    doer_name = doers[_idx(no, kind, "doer", bi, size=len(doers))]
    doer_id = next((cid for cid, nm in cast_names.items() if nm == doer_name),
                   list(cast_names.keys())[0])

    if thread:
        obj = thread["obj"]
        base = thread.get("obj_base") or obj
        cls = OBJ_CLASS.get(base, "器")
        acts = ACT_BY_CLASS[cls]
        act = acts[_idx(no, kind, "act", bi, size=len(acts))]
    else:
        obj = B_OBJ[_idx(no, kind, "obj", bi, size=len(B_OBJ))]
        act = acts_by_kind[_idx(no, kind, "act", bi, size=len(acts_by_kind))]
    if arc_place:
        place = arc_place
    else:
        place = B_PLACE[_idx(no, kind, "place", bi, size=len(B_PLACE))]
    frame = B_FRAME[_idx(no, kind, "frame", bi, size=len(B_FRAME))]
    mod = B_MOD[_idx(no, kind, "mod", bi, size=len(B_MOD))]
    twist = B_TWIST[_idx(no, kind, "twist", bi, size=len(B_TWIST))]

    text = frame.format(doer=doer_name, act=act, obj=obj,
                        place=place, mod=mod)
    # 要点：谁·怎么动·对什么·在哪｜旁人什么反应
    spec = (f"{doer_name}·{mod}{act}·{obj.replace('那', '')}"
            f"·{place}｜旁人：{twist}")
    return text, [doer_id], spec


def make_end(no: int, cast_names: dict,
             thread: dict | None = None) -> tuple[str, str]:
    """返回 (文本, 要点)。文本只做校验；要点进 prompt。"""
    doers = list(cast_names.values())
    doer = doers[_idx(no, "end", "doer", size=len(doers))]
    if thread:
        obj = thread["obj"]
    else:
        obj = B_OBJ[_idx(no, "end", "obj", size=len(B_OBJ))]
    place = B_PLACE[_idx(no, "end", "place", size=len(B_PLACE))]
    frame = END_FRAME[_idx(no, "end", "frame", size=len(END_FRAME))]
    mod = B_MOD[_idx(no, "end", "mod", size=len(B_MOD))]
    text = frame.format(doer=doer, obj=obj, place=place, mod=mod)
    spec = f"{doer}·{mod}处理·{obj.replace('那', '')}·{place}"
    return text, spec


# ==========================================================================
# 四、数据结构
# ==========================================================================

@dataclass
class Beat:
    text: str
    cast: list[str] = field(default_factory=list)
    kind: str = ""
    # 进 prompt 的「要点」。故意不是句子——模板中文不通顺，
    # 一旦写成句子就会被模型照抄进正文。
    spec: str = ""


@dataclass
class Chapter:
    no: int
    title: str
    goal: str
    beats: list[Beat] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    ends_with: str = ""
    end_spec: str = ""
    turn: str = ""
    level: str = ""
    words: int = 4000


@dataclass
class Arc:
    no: int
    vol: int
    idx_in_vol: int
    name: str
    goal: str
    start: int
    end: int
    escalates: str = ""
    chapters: list[Chapter] = field(default_factory=list)


@dataclass
class Volume:
    no: int
    act: int
    name: str
    goal: str
    escalates: str
    start: int
    end: int
    arcs: list[Arc] = field(default_factory=list)


@dataclass
class Book:
    title: str
    logline: str
    spine: str
    acts: list[dict]
    milestones: list[dict]
    volumes: list[Volume] = field(default_factory=list)

    def volume_of(self, ch: int) -> Volume | None:
        for v in self.volumes:
            if v.start <= ch <= v.end:
                return v
        return None

    def arc_of(self, ch: int) -> Arc | None:
        for v in self.volumes:
            for a in v.arcs:
                if a.start <= ch <= a.end:
                    return a
        return None

    def chapter(self, ch: int) -> Chapter | None:
        a = self.arc_of(ch)
        if not a:
            return None
        for c in a.chapters:
            if c.no == ch:
                return c
        return None

    def all_chapters(self) -> list[Chapter]:
        out = []
        for v in self.volumes:
            for a in v.arcs:
                out.extend(a.chapters)
        return out

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1),
                     encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Book":
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        b = cls(title=d["title"], logline=d["logline"], spine=d["spine"],
                acts=d["acts"], milestones=d["milestones"])
        for vd in d.get("volumes", []):
            arcs = []
            for ad in vd.pop("arcs", []):
                chs = []
                for cd in ad.pop("chapters", []):
                    bs = [Beat(**x) for x in cd.pop("beats", [])]
                    c = Chapter(**cd)
                    c.beats = bs
                    chs.append(c)
                a = Arc(**ad)
                a.chapters = chs
                arcs.append(a)
            v = Volume(**vd)
            v.arcs = arcs
            b.volumes.append(v)
        return b


# ==========================================================================
# 五、生成
# ==========================================================================

def _present(cast: CH.Cast, ch: int) -> list[str]:
    out = []
    for c in cast.characters:
        if c.first_appear > ch:
            continue
        if c.last_appear is not None and ch > c.last_appear:
            continue
        out.append(c.id)
    return out


def _arc_pos(i: int, n: int = 10) -> str:
    if i <= n * 0.25:
        return "起"
    if i <= n * 0.5:
        return "承"
    if i <= n * 0.75:
        return "转"
    return "合"


def build_outline(world: WB.WorldBible, cast: CH.Cast,
                  total: int = 5000, words_per_ch: int = 4000,
                  ch_per_vol: int = 50, arcs_per_vol: int = 5) -> Book:
    ch_per_arc = ch_per_vol // arcs_per_vol

    book = Book(
        title=world.title or "四界",
        logline="一个铁匠之子从人界杀到神界，最后亲手废掉自己成为的神。",
        spine="林昭从只想让家人活下去，到愿意为不相干的人去死，"
              "最后发现唯一的办法是放弃成为神。",
        acts=ACTS,
        milestones=_build_milestones(cast),
    )

    n_vol = (total + ch_per_vol - 1) // ch_per_vol
    for vno in range(1, n_vol + 1):
        vstart = (vno - 1) * ch_per_vol + 1
        vend = min(vno * ch_per_vol, total)
        if vstart > total:
            break
        act = next((a for a in ACTS if a["start"] <= vstart <= a["end"]),
                   ACTS[-1])

        vol = Volume(
            no=vno, act=act["no"],
            name=_vol_name(world, vstart, vno),
            goal=_vol_goal(world, vstart, act, vno),
            escalates=_vol_escalates(act, vno),
            start=vstart, end=vend,
        )

        for ai in range(1, arcs_per_vol + 1):
            astart = vstart + (ai - 1) * ch_per_arc
            aend = min(astart + ch_per_arc - 1, vend)
            if astart > vend:
                break
            arc = Arc(
                no=(vno - 1) * arcs_per_vol + ai, vol=vno, idx_in_vol=ai,
                name=["起·局", "承·势", "转·折", "合·收", "余·波"][(ai - 1) % 5],
                goal=_arc_goal(act, ai, world, astart),
                start=astart, end=aend,
                escalates=["建立规则", "打破规则", "代价显现",
                           "不可逆", "余震"][(ai - 1) % 5],
            )
            for ch in range(astart, aend + 1):
                arc.chapters.append(
                    _make_chapter(ch, ch_per_arc, world, cast, words_per_ch,
                                  ch_per_vol=ch_per_vol))
            vol.arcs.append(arc)
        book.volumes.append(vol)

    return book


def _build_milestones(cast: CH.Cast) -> list[dict]:
    ms = []
    for c in cast.characters:
        if c.importance < 0.8:
            continue
        for m in c.milestones:
            if m.note:
                ms.append({"chapter": m.chapter, "who": c.name,
                           "event": m.note, "level": m.level_index})
    ms.sort(key=lambda x: x["chapter"])
    return ms


def _vol_name(world: WB.WorldBible, ch: int, vno: int) -> str:
    lv = world.level_at(ch)
    realm = lv.realm if lv else ""
    a = T_A[_idx(vno, "va", size=len(T_A))]
    b = T_B[_idx(vno, "vb", size=len(T_B))]
    return f"第{vno}卷 · {realm}·{a}{b}"


def _vol_goal(world: WB.WorldBible, ch: int, act: dict, vno: int) -> str:
    lv = world.level_at(ch)
    if not lv:
        return act["conflict"]
    cost = ["失去一个盟友", "暴露一个秘密", "欠下一笔债",
            "毁掉一处退路", "多一个敌人", "少一个亲人"][vno % 6]
    return (f"{act['conflict']}｜本卷推进到 {lv.name}，但代价是{cost}")


def _vol_escalates(act: dict, vno: int) -> str:
    return f"{act['escalates']}｜第{vno}卷把这一层的代价推到极限"


def _arc_goal(act: dict, ai: int, world: WB.WorldBible, ch: int) -> str:
    pos = _arc_pos(ai, 5)
    lv = world.level_at(ch)
    return (f"{pos}段：在{lv.name if lv else ''}境界下，"
            f"把「{act['conflict'][:14]}」推进一层")


def _make_chapter(ch: int, ch_per_arc: int, world: WB.WorldBible,
                  cast: CH.Cast, words: int, ch_per_vol: int = 50) -> Chapter:
    lv = world.level_at(ch)
    present = _present(cast, ch)
    names = {cid: (cast.get(cid).name if cast.get(cid) else cid)
             for cid in present}
    if "c1" not in names:
        names["c1"] = cast.get("c1").name if cast.get("c1") else "林昭"
        present = ["c1"] + present

    pos_i = (ch - 1) % ch_per_arc + 1
    pos = _arc_pos(pos_i, ch_per_arc)

    beats = []
    used_cast: list[str] = []
    # 卷级线索：同一卷的 50 章共用同一个目标物，因果才连得上
    vno = (ch - 1) // max(ch_per_vol, 1)
    thread = vol_thread(vno, names)
    # 弧级焦点：每 10 章换一个"看这件东西的角度"
    arc_i = (ch - 1) // max(ch_per_arc, 1)
    aspect = OBJ_ASPECT[_idx(arc_i, "aspect", size=len(OBJ_ASPECT))]
    thread = dict(thread, obj=thread["obj"] + aspect,
                  obj_base=thread["obj_base"])
    # 弧级地点：相邻弧必然不同（+arc_i 保证不撞）
    base = vno % len(B_PLACE)
    arc_place = B_PLACE[(base + arc_i) % len(B_PLACE)]

    for bi, kind in enumerate(["冲突", "揭示", "代价", "转折"], start=1):
        text, ids, spec = make_beat(ch, kind, bi, names,
                                    thread=thread, arc_place=arc_place)
        beats.append(Beat(text=text, cast=ids, kind=kind, spec=spec))
        used_cast.extend(ids)

    ends, end_spec = make_end(ch, names, thread=thread)

    turn_dims = ["关系", "实力", "立场", "认知"]
    turn = turn_dims[_idx(ch, "turn", size=4)]

    goals = ["拿到一个答案", "拿到一件东西", "拿到一个承诺",
             "找到一条退路", "确认一件事", "还清一笔债"]
    goal = goals[_idx(ch, "goal", size=len(goals))]

    cast_final = list(dict.fromkeys(used_cast + present))[:6]

    # 目标里带上卷线索，让每章都知道自己在追什么
    obj_clean = thread["obj"].replace("那", "")
    return Chapter(
        no=ch,
        title=make_title(ch),
        goal=(f"在{lv.name if lv else ''}境界下，{goal}："
              f"围绕{obj_clean}，卡在「{thread['problem']}」上"),
        beats=beats,
        cast=cast_final,
        ends_with=ends,
        end_spec=end_spec,
        turn=f"{turn}发生不可逆变化",
        level=lv.name if lv else "",
        words=words,
    )


# ==========================================================================
# 六、校验（这次阈值是真的严）
# ==========================================================================

# 病句模式：确定性生成最容易出这些
_BAD_PATTERNS = [
    ("在在", "重复介词"),
    ("了了", "重复助词"),
    ("的的", "重复助词"),
    ("把把", "重复介词"),
    ("被被", "重复介词"),
    ("，。", "空逗号"),
    ("。。", "重复句号"),
    ("放下在", "动补搭配错误"),
    ("交出在", "动补搭配错误"),
    ("撕开在", "动补搭配错误"),
    ("摊开在", "动补搭配错误"),
    ("拦住在", "动补搭配错误"),
    ("在在了", "介词助词叠加"),
]


def check_grammar(text: str) -> list[str]:
    """检查确定性生成可能产生的病句。"""
    return [desc for pat, desc in _BAD_PATTERNS if pat in text]


def validate(book: Book, world: WB.WorldBible, cast: CH.Cast,
             total: int = 5000) -> list[str]:
    problems: list[str] = []
    from collections import Counter

    chs = book.all_chapters()

    # A. 章号无缝
    if len(chs) != total:
        problems.append(f"❌ 章纲数量 {len(chs)} ≠ {total}")
    if chs and chs[0].no != 1:
        problems.append(f"❌ 首章不是第 1 章")
    for a, b in zip(chs, chs[1:]):
        if b.no != a.no + 1:
            problems.append(f"❌ 章号断裂：{a.no} → {b.no}")
            break
    if chs and chs[-1].no != total:
        problems.append(f"❌ 末章不是第 {total} 章")

    # B. 每章必须有 4 beat + ends_with
    bad = [c.no for c in chs if len(c.beats) < 4]
    if bad:
        problems.append(f"❌ {len(bad)} 章 beat 不足 4 个")
    no_end = [c.no for c in chs if not c.ends_with]
    if no_end:
        problems.append(f"❌ {len(no_end)} 章没有 ends_with")

    # C. 人物出场正确
    bad_cast = []
    for c in chs:
        for cid in c.cast:
            p = cast.get(cid)
            if not p:
                bad_cast.append((c.no, cid, "角色不存在"))
            elif p.first_appear > c.no:
                bad_cast.append((c.no, cid, "尚未登场"))
            elif p.last_appear is not None and c.no > p.last_appear:
                bad_cast.append((c.no, cid, "已退场"))
    if bad_cast:
        n, cid, why = bad_cast[0]
        problems.append(f"❌ {len(bad_cast)} 处出场错误（第 {n} 章 {cid}：{why}）")

    # D. 每卷有 escalates
    if any(not v.escalates for v in book.volumes):
        problems.append("❌ 有卷缺少 escalates")

    # ===== 关键：这次的阈值是"真的严" =====
    # E. 章标题唯一率必须 ≥90%
    titles = [c.title for c in chs]
    u_titles = len(set(titles))
    title_rate = u_titles / len(titles)
    print(f"  [标题] 唯一 {u_titles}/{len(titles)} = {title_rate:.1%}")
    if title_rate < 0.90:
        problems.append(
            f"❌ 章标题唯一率仅 {title_rate:.1%}（要求 ≥90%）。"
            f"最高重复「{Counter(titles).most_common(1)[0][0]}」"
            f"×{Counter(titles).most_common(1)[0][1]}")

    # F. beat 唯一率必须 ≥85%
    beats = [b.text for c in chs for b in c.beats]
    u_beats = len(set(beats))
    beat_rate = u_beats / len(beats)
    print(f"  [beat] 唯一 {u_beats}/{len(beats)} = {beat_rate:.1%}")
    if beat_rate < 0.85:
        problems.append(
            f"❌ beat 唯一率仅 {beat_rate:.1%}（要求 ≥85%）。"
            f"最高重复「{Counter(beats).most_common(1)[0][0][:24]}」"
            f"×{Counter(beats).most_common(1)[0][1]}")

    # G. 结尾句唯一率必须 ≥60%（结尾句池本来就小）
    ends = [c.ends_with for c in chs]
    u_ends = len(set(ends))
    end_rate = u_ends / len(ends)
    print(f"  [结尾] 唯一 {u_ends}/{len(ends)} = {end_rate:.1%}")
    if end_rate < 0.60:
        problems.append(f"❌ 结尾句唯一率仅 {end_rate:.1%}（要求 ≥60%）")

    # H. 主角必须在场
    no_main = [c.no for c in chs if "c1" not in c.cast]
    if no_main:
        problems.append(f"❌ {len(no_main)} 章主角不在场")

    # K. 语义唯一率（比字符串唯一率严格得多）
    #    字符串唯一率高 != 语义不重复。实测：字符串 99% 唯一，
    #    但语义空间只有 6 动作 x 12 物件 x 6 地点 = 432 种组合，
    #    5000 章 x 4 beat = 20000 条，平均每种组合用 46 次。
    #    这就是确定性生成的固有局限，必须显式暴露，不能靠字符串去重糊过去。
    all_acts = sum(B_ACT.values(), [])
    semantic = []
    for c in chs:
        for b in c.beats:
            act = next((a for a in all_acts if a in b.text), "?")
            obj = next((o for o in B_OBJ if o in b.text), "?")
            place = next((pl for pl in B_PLACE if pl in b.text), "?")
            semantic.append((act, obj, place))
    u_sem = len(set(semantic))
    all_act_n = len(set(all_acts))
    space = all_act_n * len(B_OBJ) * len(B_PLACE)
    avg_use = len(semantic) / max(1, u_sem)
    print("  [语义] 唯一 %d 种组合（上限 %d），平均每条用 %.1f 次"
          % (u_sem, space, avg_use))
    if u_sem < space * 0.8:
        problems.append(
            "WARN 语义组合只覆盖 %d/%d，模板多样性不足" % (u_sem, space))

    # J. 病句检测（确定性生成最容易出这个）
    bad_sents = []
    for c in chs:
        for txt in [b.text for b in c.beats] + [c.ends_with, c.goal]:
            g = check_grammar(txt)
            if g:
                bad_sents.append((c.no, txt, g[0]))
    if bad_sents:
        n0, txt0, why0 = bad_sents[0]
        problems.append(
            "❌ %d 处病句（如第 %d 章「%s」：%s）"
            % (len(bad_sents), n0, txt0[:30], why0))

    # I. 连续 3 章不能完全相同的 beat 组合
    for i in range(len(chs) - 2):
        s1 = tuple(b.text for b in chs[i].beats)
        s2 = tuple(b.text for b in chs[i + 1].beats)
        s3 = tuple(b.text for b in chs[i + 2].beats)
        if s1 == s2 == s3:
            problems.append(f"❌ 第 {chs[i].no}~{chs[i+2].no} 章 beat 完全相同")
            break

    return problems


def stats(book: Book) -> dict:
    from collections import Counter
    chs = book.all_chapters()
    titles = [c.title for c in chs]
    beats = [b.text for c in chs for b in c.beats]
    ends = [c.ends_with for c in chs]
    return {
        "幕数": len(book.acts),
        "卷数": len(book.volumes),
        "弧数": sum(len(v.arcs) for v in book.volumes),
        "章数": len(chs),
        "beat 总数": len(beats),
        "章标题唯一": f"{len(set(titles))}/{len(titles)}",
        "beat 唯一": f"{len(set(beats))}/{len(beats)}",
        "结尾句唯一": f"{len(set(ends))}/{len(ends)}",
        "总字数": f"{sum(c.words for c in chs):,}",
    }


# ==========================================================================
# 七、CLI
# ==========================================================================

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    total = 5000

    world = WB.build_world(total, title="四界")
    cast = CH.build_cast(world, total)
    book = build_outline(world, cast, total)

    out_p = here.parent / "out" / "outline_full.json"
    book.save(out_p)

    print("=" * 74)
    print("四层大纲")
    print("=" * 74)
    print(f"\n【全书】{book.title}")
    print(f"  一句话：{book.logline}")
    print(f"  脊柱：{book.spine}")
    print(f"  里程碑：{len(book.milestones)} 个")

    print(f"\n【六幕】")
    for a in book.acts:
        print(f"  第{a['no']}幕 {a['name']}（第 {a['start']}~{a['end']} 章）")
        print(f"    冲突：{a['conflict']}")
        print(f"    不可逆：{a['irreversible']}")
        print(f"    升级：{a['escalates']}")

    print(f"\n【卷纲抽样】")
    for v in (book.volumes[0], book.volumes[31],
              book.volumes[60], book.volumes[99]):
        print(f"  {v.name}（第 {v.start}~{v.end} 章，第{v.act}幕）")
        print(f"    目标：{v.goal[:64]}")
        print(f"    升级：{v.escalates[:64]}")

    print(f"\n【章纲抽样】")
    for no in (1, 2, 250, 1601, 2400, 3001, 4201, 5000):
        c = book.chapter(no)
        if not c:
            continue
        print(f"\n  第{c.no}章《{c.title}》｜{c.level}｜{c.words} 字")
        print(f"    目标：{c.goal}")
        for b in c.beats:
            print(f"      · [{b.kind}] {b.text}")
        print(f"    结尾：{c.ends_with}")
        print(f"    转折：{c.turn}")

    print("\n" + "=" * 74)
    print("统计")
    print("=" * 74)
    for k, v in stats(book).items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 74)
    print("校验")
    print("=" * 74)
    problems = validate(book, world, cast, total)
    if problems:
        for p in problems:
            print("  " + p)
    else:
        print("  ✅ 大纲可运行：章号无缝、每章 4 beat、人物出场正确、")
        print("     每卷有升级、标题/beat/结尾唯一率达标、主角全程在场")

    print(f"\n已写出 {out_p}")
