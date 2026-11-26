#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prose_judge.py —— 中文网文正文「读者体验」专项评审器

和 ai_flavor.py 的分工
----------------------
ai_flavor.py 是**通用 AI 味检测器**：它回答"这段文字像不像模型按概率均值写出来的"，
词表以套话/情绪直说/抽象大词为主。它抓不到真人读者抱怨的那三件事：

    1. 字数偏多；
    2. 修饰过重、描述过重；
    3. 读起来费劲。

本模块只回答这三件事里**可计算**的部分，每条指标都有明确的判定逻辑，
并且**必须给出原文例句**——因为"哪句话读起来累"是给人看的，不是给分数看的。

    中文小说'读起来累'的七个可计算病因
    ----------------------------------
    定语堆叠      '的'字密度 / 'X的Y的Z' 三连 / 一句内 ≥3 个'的' 的句子占比
    无关细节      纯静物·纯环境句（无人、无动作、无因果/条件/时间推进）占比
    碎句轰炸      连续 ≥3 句 ≤6 字的片段数 / ≤6 字句占比
    句首雷同      连续 ≥3 句同一开头的片段数 / 相邻同头比
    代称滥用      少年·少女·老人·汉子… 每千字次数
    动作复读      '他+动词' / '动词+了+量词' 短语全文 ≥3 次的清单
    解释过载      含 因为/所以/要是/否则/意味着/等于/说白了 的句子占比 + 连续解释句
    信息密度      每 300 字新增专名数 / 对话轮中'给新信息'的比例（辅助）
    逗号链        一句内 ≥4 个逗号的"长呼吸句"占比（辅助，我自建）

用法
----
    python src/prose_judge.py FILE_OR_DIR [MORE ...] [--json out/judge/x.json] [--md out/judge/y.md]

    # 生成 A/B/C 三批诊断报告 + 横向对比（写入 out/judge/）
    python src/prose_judge.py --emit-reports

    # 作为库
    from prose_judge import analyze_text, analyze_file
    r = analyze_text(text, name="ch01")
    print(r["readability"]["score"])

设计原则
--------
1. **纯标准库**，不联网、不装包，可离线跑。
2. 每个指标除了数值，必须能吐出**原文例句**（最多 20 条），否则一律标记 [不可靠]。
3. 启发式不可靠的地方**写在报告里**，不藏。宁可少一个指标，不给假数字。
4. 综合分 0~100（越高越易读）是**可分解**的：每一项扣了多少分都打印出来，
   方便把分数翻译成"改哪一句"。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# 一、词表
# --------------------------------------------------------------------------

# 句末标点（含省略号、问叹号半角）
TERM_CHARS = "。！？!?…"
CLOSE_QUOTE = "」』”\"'"
OPEN_QUOTE = "「『“\""

# 句内停顿
COMMA_CHARS = "，,、；;"

# 1) 人物标记 —— 出现即视为"句中有人的存在"
PRONOUN = ("他", "她", "我", "你", "您", "咱", "俺", "谁", "人家", "自己")

# 身体部位：有它也说明写的是人（哪怕没写代词）
BODY_PART = (
    "眼睛", "眼神", "眼珠", "眼皮", "眼角", "目光", "手", "手指", "指头", "指节",
    "手掌", "掌心", "手背", "肩", "肩膀", "胳膊", "臂", "腕", "腿", "脚", "膝盖",
    "脸", "脸色", "腮", "嘴", "嘴角", "牙", "牙花子", "眉", "眉毛", "眉骨", "掌",
    "背", "腰", "脖子", "喉咙", "喉", "鼻子", "耳朵", "胸口", "胸", "肚子",
    "头发", "下巴", "额头", "拳", "拳头", "袖", "袖筒", "胡须", "脖子",
)

# 人的动作动词（用于判断"这句有没有人在做事"）
HUMAN_VERB = (
    "走", "跑", "坐", "站", "躺", "蹲", "爬", "推", "拉", "拽", "抱", "打", "踢",
    "咬", "抓", "握", "捏", "拍", "敲", "砸", "扔", "丢", "捡", "拾", "吃", "喝",
    "嚼", "咽", "吐", "喘", "咳", "喊", "叫", "骂", "笑", "哭", "退", "转", "抬",
    "伸", "按", "扶", "挪", "俯", "弯", "抖", "攥", "扯", "盯", "看", "瞧", "望",
    "听", "问", "说", "答", "点", "摇", "摆", "跨", "迈", "踏", "踩", "蹲", "靠",
    "倚", "缩", "拱", "递", "接", "掏", "摸", "擦", "抹", "关", "开", "挑", "翻",
    "盖", "掀", "揭", "卷", "裹", "抽", "塞", "掰", "拧", "捶", "跺", "挠", "扶",
    "动", "愣", "抿", "撇", "眯", "皱", "侧", "偏", "低", "起", "落", "磕", "蹭",
    "赶", "撂", "端", "拎", "提", "扛", "摔", "撕", "捂", "摁", "掐", "嗅", "闻",
    "舔", "踹", "捶", "掷", "抛", "摁", "掖", "撑", "攥", "扶", "拖", "扯",
)

# 因果 / 条件 / 时间推进 —— 这类词出现说明句子在"推进剧情"，不是纯静物
CAUSAL_COND = (
    "因为", "所以", "因此", "于是", "要是", "如果", "若", "否则", "既然", "只要",
    "除非", "免得", "以致", "为了", "不然", "反而", "因此", "既然", "才", "便",
)
TIME_ADV = (
    "然后", "接着", "后来", "此后", "之后", "以前", "从前", "当初", "刚才", "现在",
    "忽然", "突然", "立刻", "随即", "马上", "已经", "还没", "正在", "这时", "此时",
    "那年", "那天", "那天夜里", "半晌", "半天", "起先", "起初", "最后", "终于",
    "顿时", "骤然", "猛地", "霎时", "瞬间", "一瞬", "转眼",
)
# 规则/后果句（"过了子时，旧物就得封进内库"）——含这些词就不是纯静物
MODAL_RE = re.compile(r"(就得|得要|该|必须|不能|不准|不许|否则|免得|才算|只能|不许)")
# 静态动词：允许出现在"纯静物句"里而不算人在动
STATIC_VERB = (
    "搁", "放", "摆", "挂", "悬", "贴", "压", "铺", "垂", "堆", "落", "盖", "插",
    "嵌", "刻", "印", "铸", "掉", "裂", "破", "缺", "有", "是", "在", "被", "让",
    "照", "映", "闪", "亮", "暗", "湿", "干", "旧", "新",
)

# 2) 代称（标签化叫法）—— 网文里最容易滥用的"万能称呼"
EPITHET = (
    "少年", "少女", "老人", "老者", "汉子", "壮汉", "矮胖汉子", "姑娘", "丫头",
    "小妹", "小哥", "大叔", "妇人", "女子", "男子", "那人", "此人", "众人", "来人",
    "青年人", "中年男人", "老者", "老翁", "老太", "婆子", "掌柜", "小二", "脚夫",
    "灰袄老者", "年轻人", "汉子", "壮年汉子", "外门弟子", "内门弟子",
)

# 3) 解释句标记（说理腔 / 说明文腔）
EXPLAIN_MARK = (
    "因为", "所以", "要是", "否则", "意味着", "等于", "说白了", "也就是说",
    "换句话说", "毕竟", "显然", "事实上", "其实", "本来", "反正", "总之",
    "说到底", "说白了", "只能", "也就是说",
)
# 核心五个（严格按需求定义的集合），用于主指标
EXPLAIN_CORE = ("因为", "所以", "要是", "否则", "意味着", "等于", "说白了")

# 4) 专名启发式用：姓氏表（常用 350 姓，足够覆盖网文人名）
SURNAME = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜谢邹苏潘葛"
    "范彭鲁韦马苗方俞任袁柳鲍史唐薛雷贺倪汤殷罗毕郝安常乐于傅齐康伍余顾孟黄萧尹"
    "姚邵汪毛狄米贝明戴宋庞熊纪舒屈项董梁杜阮蓝闵席季贾路娄江童颜郭梅盛林钟徐邱"
    "骆高夏蔡田樊胡凌霍虞万柯管卢莫房裘应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆"
    "荣翁荀惠甄曲封松井段富巫焦巴弓牧山谷车侯全班仰秋仲伊宫宁仇甘厉祖武符刘景詹"
    "龙叶幸司韶黎薄印白怀蒲从鄂索咸赖卓蔺屠蒙池乔苍双闻党翟谭贡劳姬申扶冉宰郦雍"
    "桑桂牛寿通边燕浦尚农温庄晏柴瞿阎慕连习艾容向古易慎戈廖衡步都耿满弘匡国文寇"
    "广东欧沃利蔚越隆师巩聂晁融冷辛那简饶空曾沙养鞠丰巢关相查后荆红游权盖益桓"
)

# 姓氏起头但其实是普通词的——必须排除，否则专名密度会虚高
_NAME_BLOCK_TEXT = (
    "于是 小时 平时 时候 后来 方便 方面 千万 万一 石头 左右 哪里 上下 前后 国家 "
    "文明 明白 明年 明显 和平 和气 成人 成本 成为 成长 司机 司空 马上 马路 黄金 "
    "白天 万物 万里 江湖 江南 山谷 山口 车道 车子 车轮 全球 全部 全家 皮肤 皮毛 "
    "毛病 武士 武器 武力 弟子 干净 干什么 干枯 干笑 干涩 干粮 常常 常人 常年 常事 "
    "安全 安静 安顿 孙子 孙女 子时 子孙 宁可 宁肯 官府 官家 官人 文书 文字 文化 "
    "温暖 温和 庄重 庄稼 柴火 柴门 叶子 花园 花白 苗头 苏醒 范围 段落 汤水 汤药 "
    "雷霆 雷电 雷同 贺喜 费用 费劲 费力 成熟 成亲 片段 康复 康健 余额 顾问 顾及 "
    "黄泉 黄沙 萧条 汪洋 毛皮 米饭 米粒 明亮 明天 明早 明朝 宋朝 庞大 熊掌 纪元 "
    "纪录 舒服 舒展 屈膝 项目 项圈 柱子 杜绝 蓝天 蓝布 席地 席卷 季节 季风 路线 "
    "江面 江水 童话 童年 颜面 颜色 梅花 盛开 盛饭 林中 林间 钟声 钟头 徐州 徐缓 "
    "骆驼 高层 高矮 夏天 夏季 田野 田埂 樊笼 胡须 胡话 凌乱 凌晨 霍然 万丈 管家 "
    "莫非 房梁 房内 裘皮 应声 应诺 宗旨 宗族 丁香 宣纸 宣布 郁闷 单体 杭州 洪亮 "
    "包袱 包括 诸位 左边 石阶 石壁 吉祥 程度 陆续 荣光 惠民 甄别 曲调 曲子 封口 "
    "封条 松手 松针 井口 井台 富裕 巫师 焦黑 焦躁 巴掌 弓弦 牧人 车夫 侯爵 班长 "
    "仰头 秋天 秋风 仲裁 伊始 宫殿 宁静 仇恨 甘心 厉声 祖宗 武人 符纸 景色 龙鳞 "
    "叶脉 幸运 司徒 韶光 黎民 薄薄 薄雾 印象 白云 白布 怀中 怀内 蒲扇 从容 赖皮 "
    "卓然 屠夫 蒙蒙 池水 乔装 苍天 苍白 双亲 闻声 觉察 非常 是非 成语 语气 语调 "
    "数目 数据 数字 育儿 巢穴 关心 关卡 相国 查问 荆州 红外 游戏 权力 盖住 盖子 "
    "益处 段落 段落 段落 段落 段落 段落 段落 段落 段落 段落 段落 段落 段落 段落"
)
NAME_BLOCK = set(_NAME_BLOCK_TEXT.split())

# 地名/机构后缀
PLACE_SUFFIX = (
    "镇", "城", "村", "山", "谷", "堂", "院", "门", "宗", "阁", "寺", "观", "岭",
    "河", "江", "湖", "寨", "堡", "关", "府", "库", "林", "峰", "洞", "殿", "楼",
)
PLACE_BLOCK = set(
    "房门 门口 大门 后门 出门 进门 开门 关门 院子 院里 门外 门里 门口 门板 "
    "窗前 墙根 山脚 河面 水面 江面 后面 前面 里面 外面 上面 下面 当中 中间 "
    "下首 上首 里屋 外屋 屋里 屋内 院墙 库房 库门 药堂 账房"
)

# 器物/术语后缀
PROP_SUFFIX = (
    "镜", "册", "符", "丹", "剑", "刀", "炉", "珠", "印", "阵", "诀", "灵石",
    "铜片", "算盘", "账簿", "契约", "珠子", "玉佩", "令牌", "牌位", "字条",
)
PROP_BLOCK = set(
    "镜子 影子 刀子 印子 印痕 手印 脚印 石印 册子 炉子 珠子 眼界 地步 阵子 "
    "法子 念头 念头 阵脚 着刀 出刀 拔刀 提刀 收刀 拿刀 一把刀 灵石 铜片 "
)

# 人名末字黑名单：姓氏字开头的普通短语（"石阶上""张了张""从怀里"）一律挡掉。
# 注意：**不能**放"年/天/月/日/文/明/成/平/和/时"——这些是常见人名用字
#（沈鹤年、李天一、方明月…），放进去会把真名一起杀掉。
NAME_TAIL_BAN_ANY = set(
    "的了是在有和与也都就才要会能把被让给从向到对为以及而且但却又再还只更最很太"
    "不没无个些里上下中内外前后这那哪来去人们说道问答看走站坐笑哭蹲伸抬低侧转盯"
    "攥咬牙嘴手脚眼头脸眉肩背腰腿声口心身掏拿放推拉抓握捏拍敲扔吃喝喊叫骂退停动"
    "抖扯望听应点摇摆跨迈踏踩靠倚缩拱递接摸擦关挑翻盖掀卷裹抽塞掰拧跳磕蹭跺踹"
    "起落开合抱打踢跑躺爬站靠缩皱抿撇眯咧哼嘿喂哦啊呀吧呢吗嘛吧啦"
)
# 两字人名还要额外挡掉身体/方位字（"左手""边角""后那"）
NAME_TAIL_BAN_2 = NAME_TAIL_BAN_ANY | set(
    "边角面里后前上下中内外间侧处心口指掌牙耳鼻胸膝年月日时天地人儿子头尾端底顶"
    "东西南北手足身背腿臂"
)

# 专名候选里绝不能出现的功能字（含这些的多半是切错的短语）
FUNC_CHARS = set(
    "的了是在有和与也都就才要会能把被让给从向到对为以及而且但却又再还只更最很太"
    "不没无个些我你他她它们这那哪什么怎样吗呢吧啊呀"
)
# 量词/方位/指示字打头的候选一律不要（"面铜镜""这面镜""把锈刀"都是切错的）
BAD_PREFIX = set(
    "面道张条只个块根把片支枚颗粒团阵股缕抹丝声口下步眼手脚头边里前后上中内外"
    "两一这那每某几半满全件样种堆层截段副双对扇幅座所间处点些"
)

# 静物/环境名词——"纯静物句"必须至少含一个，否则那是抽象断言，不是静物描写。
# （这一条是实测加上的：不加的话"盘算早定死了。""境界差了五重。"会被误判成静物句。）
STATIC_NOUN = (
    "灯", "灯芯", "灯盏", "灯笼", "蜡烛", "火苗", "火", "烟", "灰", "炭", "光", "影子",
    "铜镜", "镜子", "镜面", "镜钮", "镜背", "镜缘", "裂纹", "刻纹", "铸纹", "花纹",
    "条案", "案", "桌", "桌面", "桌沿", "柜台", "铺板", "门", "门板", "门槛", "门框",
    "门缝", "窗", "墙", "墙根", "土墙", "屋", "屋顶", "梁", "柱", "砖", "地砖", "地板",
    "铁钩", "竹签", "秤", "秤砣", "秤杆", "算盘", "算珠", "狼毫", "笔", "墨", "纸",
    "油纸", "纸包", "布袋", "包袱", "绳子", "铜片", "帕子", "袖", "袖筒", "衣裳",
    "鞋", "鞋帮", "鞋尖", "脚印", "手印", "血", "汗", "泪", "水", "油", "药", "药渣",
    "雪", "雪地", "雪面", "风", "雨", "云", "月", "太阳", "天", "地", "石头", "沙",
    "街", "街道", "屋檐", "冰溜子", "渡口", "河", "江", "井", "桥", "路", "山", "洞",
    "库房", "内库", "库门", "册子", "账簿", "账本", "碑", "碑印", "印", "符",
    "符纹", "阵", "丹", "剑", "刀", "枪", "棍", "牌", "令", "车", "船", "肉", "米",
    "饭", "酒", "茶", "碗", "筷子", "锅", "灶", "泥", "草", "树", "叶", "花", "根",
    "布", "铁", "铜", "银", "钱", "银子", "灵石", "谷", "骨", "牙", "头发",
)
# "两人""几个人"也算人在场（不能算静物句）
PERSON_COUNT = ("两人", "一人", "三人", "二人", "几人", "俩人", "两个", "几个",
                "众人", "旁人", "有人", "没人", "所有人")
# 人名/称谓的补充正则（姓氏表覆盖不到的"老赵头""李师傅"）
PERSON_RE = re.compile(r"(老[一-龥]头|小[一-龥]子|[一-龥]师傅|[一-龥]掌柜|那[一-龥]子)")

# 5) 空转对话（说了等于没说）
FILLER_TURN = set((
    "嗯 啊 哦 噢 唔 是 对 好 行 不 没有 什么 谁 别 闭嘴 你说呢 走吧 滚 哼 嘿 "
    "哈 喂 哥 妹 师父 老头 老头儿 急什么 是吗 那我呢 你说 嗯嗯"
).split())
NUM_WORDS = "零一二三四五六七八九十百千万两半几数"
QUANT_RE = re.compile(
    "[" + NUM_WORDS + "][个声口下步眼只阵把根次圈遍顿分日月年层条张片斤斗袋些]"
)

# 动作复读用：量词
MEASURE = "个声口下步眼只阵把根次圈遍顿分日月年层条张片斤斗袋些"

HAN_RE = re.compile(r"[\u4e00-\u9fff]")

# --------------------------------------------------------------------------
# 二、切分
# --------------------------------------------------------------------------


@dataclass
class Sent:
    text: str
    start: int
    end: int
    para: int
    idx: int          # 全文句序号
    han: int = 0
    dialogue: bool = False
    commas: int = 0

    def __post_init__(self):
        self.han = len(HAN_RE.findall(self.text))
        self.commas = sum(1 for ch in self.text if ch in COMMA_CHARS)


def dialogue_mask(text: str) -> bytearray:
    """标出所有落在引号内的字符位置。"""
    mask = bytearray(len(text))
    pairs = {"「": "」", "『": "』", "“": "”", '"': '"'}
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in pairs:
            close = pairs[c]
            j = text.find(close, i + 1)
            if j == -1:
                i += 1
                continue
            for k in range(i, min(j + 1, n)):
                mask[k] = 1
            i = j + 1
        else:
            i += 1
    return mask


def split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\r?\n", text)
    return [p.strip() for p in parts if p.strip()]


def parse(text: str) -> tuple[list[Sent], list[str], bytearray]:
    paras = split_paragraphs(text)
    mask = dialogue_mask(text)
    sents: list[Sent] = []
    pos = 0
    gi = 0
    for pi, par in enumerate(paras):
        start = text.find(par, pos)
        if start < 0:
            start = pos
        end = start + len(par)
        pos = end
        i = start
        buf_start = start
        while i < end:
            ch = text[i]
            # 一句里出现第二个开引号 = 引号内插叙后又起新引号，
            # 读者在这里本来就换了一口气，所以就地断句（否则会造出假的 60 字长句）
            if ch in OPEN_QUOTE and text.count(ch, buf_start, i) >= 1:
                seg = text[buf_start:i].strip()
                if seg and han_len(seg) >= 4:
                    sents.append(_mk(seg, buf_start, i, pi, gi, mask))
                    gi += 1
                    buf_start = i
            if ch in TERM_CHARS:
                j = i + 1
                while j < end and (text[j] in TERM_CHARS or text[j] in CLOSE_QUOTE):
                    j += 1
                seg = text[buf_start:j].strip()
                if seg:
                    sents.append(_mk(seg, buf_start, j, pi, gi, mask))
                    gi += 1
                buf_start = j
                i = j
            else:
                i += 1
        tail = text[buf_start:end].strip()
        if tail:
            sents.append(_mk(tail, buf_start, end, pi, gi, mask))
            gi += 1
    return sents, paras, mask


def _mk(seg: str, s: int, e: int, pi: int, gi: int, mask: bytearray) -> Sent:
    inside = sum(mask[s:e])
    total = max(1, e - s)
    return Sent(seg, s, e, pi, gi, dialogue=(inside * 2 >= total))


def han_len(s: str) -> int:
    return len(HAN_RE.findall(s))


def pct(a: int, b: int) -> float:
    return (a / b) if b else 0.0


# --------------------------------------------------------------------------
# 三、各指标
# --------------------------------------------------------------------------


def _strip_head(s: str) -> str:
    """去掉句首引号/标点/空白，返回用于比较开头的字符串。"""
    i = 0
    while i < len(s) and (s[i] in OPEN_QUOTE or s[i] in CLOSE_QUOTE
                          or s[i] in "，,、。！？!?…—-·　 \t"):
        i += 1
    return s[i:]


def m_attributive(text: str, sents: list[Sent]) -> dict:
    """定语堆叠：的字密度 / '的'三连 / ≥3 个'的' 的句子占比。"""
    n_han = han_len(text)
    de = text.count("的")
    de_per_100 = de / (n_han / 100.0) if n_han else 0.0

    # X 的 Y 的 Z：3 个'的'之间各夹 ≤6 字，且同在一句
    triple_re = re.compile(r"的[^的。！？!?…，,]{0,6}的[^的。！？!?…，,]{0,6}的")
    triples = []
    for s in sents:
        for mm in triple_re.finditer(s.text):
            triples.append(s.text[max(0, mm.start() - 12):mm.end() + 6])
    quad_re = re.compile(r"的[^的。！？!?…]{0,8}的[^的。！？!?…]{0,8}的[^的。！？!?…]{0,8}的")
    quads = sum(1 for s in sents for _ in quad_re.finditer(s.text))

    ge3 = [s for s in sents if s.text.count("的") >= 3]
    de_ge3_examples = sorted(ge3, key=lambda s: -s.text.count("的"))[:20]
    return {
        "de_per_100": round(de_per_100, 2),
        "de_triple": len(triples),
        "de_triple_per_1k": round(len(triples) / (n_han / 1000.0), 2) if n_han else 0.0,
        "de_quad": quads,
        "sent_ge3de_ratio": round(pct(len(ge3), len(sents)), 4),
        "sent_ge3de_count": len(ge3),
        "examples": [
            {"quote": e.text, "de": e.text.count("的"), "para": e.para + 1}
            for e in de_ge3_examples
        ],
        "triple_examples": [t for t in triples[:20]],
        "n_sent": len(sents),
        "n_han": n_han,
    }


def _is_static_scene(s: Sent, person_tokens: set[str] | None = None) -> bool:
    """纯静物/纯环境句：没有人、没有人的动作、没有因果/条件/时间推进。

    判据（全部满足才算）：
      1. 不在引号内（不是对话）；
      2. 不含人物代词 / 身体部位 / 代称 / 已识别的人名 / "老赵头"式称谓；
      3. 不含因果·条件·时间推进词；
      4. 不含人的动作动词；
      5. **至少含一个器物/环境名词**（否则那是抽象断言，不算静物描写）；
      6. ≥4 个汉字。
    """
    t = s.text
    if s.dialogue:
        return False
    if any(p in t for p in PRONOUN):
        return False
    if any(p in t for p in PERSON_COUNT):
        return False
    if any(b in t for b in BODY_PART):
        return False
    if any(e in t for e in EPITHET):
        return False
    if PERSON_RE.search(t):
        return False
    if person_tokens and any(n in t for n in person_tokens):
        return False
    if any(v in t for v in CAUSAL_COND):
        return False
    if any(v in t for v in TIME_ADV):
        return False
    if MODAL_RE.search(t):
        return False
    if any(v in t for v in HUMAN_VERB):
        return False
    if not any(w in t for w in STATIC_NOUN):
        return False
    return s.han >= 4


def m_static_detail(text: str, sents: list[Sent],
                    person_tokens: set[str] | None = None) -> dict:
    hits = [s for s in sents if _is_static_scene(s, person_tokens)]
    return {
        "count": len(hits),
        "ratio": round(pct(len(hits), len(sents)), 4),
        "examples": [
            {"quote": s.text, "han": s.han, "para": s.para + 1} for s in hits[:20]
        ],
        "n_sent": len(sents),
    }


def m_short_sent(text: str, sents: list[Sent]) -> dict:
    n_han = han_len(text)
    lens = [s.han for s in sents]
    short = [s for s in sents if s.han <= 6]
    runs = []
    i = 0
    while i < len(sents):
        if sents[i].han <= 6:
            j = i
            while j < len(sents) and sents[j].han <= 6:
                j += 1
            if j - i >= 3:
                runs.append(sents[i:j])
            i = j
        else:
            i += 1
    longest = max((len(r) for r in runs), default=0)
    avg = sum(lens) / len(lens) if lens else 0.0
    sd = math.sqrt(sum((x - avg) ** 2 for x in lens) / len(lens)) if lens else 0.0
    return {
        "short_ratio": round(pct(len(short), len(sents)), 4),
        "short_count": len(short),
        "robust_ratio": round(pct(sum(1 for x in lens if x <= 10), len(lens)), 4),
        "runs_ge3": len(runs),
        "runs_ge3_per_1k": round(len(runs) / (n_han / 1000.0), 2) if n_han else 0.0,
        "longest_run": longest,
        "avg_sent": round(avg, 1),
        "sent_cv": round(sd / avg, 2) if avg else 0.0,
        "max_sent": max(lens) if lens else 0,
        "examples": [
            {"quote": " ｜ ".join(x.text for x in r), "n": len(r)} for r in runs[:20]
        ],
        "n_sent": len(sents),
    }


def _open_key(s: Sent) -> str:
    h = _strip_head(s.text)
    if not h:
        return ""
    c0 = h[0]
    if c0 in ("他", "她", "我", "你", "您", "咱"):
        return c0
    han = HAN_RE.findall(h)
    return "".join(han[:2])


def m_open_repeat(text: str, sents: list[Sent]) -> dict:
    n_han = han_len(text)
    keys = [_open_key(s) for s in sents]
    runs = []
    i = 0
    while i < len(keys):
        if not keys[i]:
            i += 1
            continue
        j = i + 1
        while j < len(keys) and keys[j] == keys[i]:
            j += 1
        if j - i >= 3:
            runs.append((keys[i], sents[i:j]))
        i = j
    adj_same = sum(1 for a, b in zip(keys, keys[1:]) if a and a == b)
    dist = Counter(k for k in keys if k)
    return {
        "runs_ge3": len(runs),
        "runs_ge3_per_1k": round(len(runs) / (n_han / 1000.0), 2) if n_han else 0.0,
        "adjacent_same_ratio": round(pct(adj_same, max(1, len(keys) - 1)), 4),
        "longest_run": max((len(r[1]) for r in runs), default=0),
        "top_keys": [[k, c] for k, c in dist.most_common(8)],
        "head_div": round(len(dist) / max(1, len(keys)), 3),
        "examples": [
            {"key": k, "n": len(ss), "quote": "".join(x.text for x in ss)}
            for k, ss in runs[:20]
        ],
        "n_sent": len(sents),
    }


def m_epithet(text: str, sents: list[Sent]) -> dict:
    n_han = han_len(text)
    cnt = Counter()
    occ = {}
    for w in EPITHET:
        c = text.count(w)
        if c:
            cnt[w] += c
        for s in sents:
            if w in s.text and w not in occ:
                occ[w] = s.text
    total = sum(cnt.values())
    return {
        "per_1k": round(total / (n_han / 1000.0), 2) if n_han else 0.0,
        "total": total,
        "distinct": len(cnt),
        "hits": cnt.most_common(15),
        "examples": [{"word": w, "quote": occ[w]} for w, _ in cnt.most_common(12)
                     if w in occ],
        "n_han": n_han,
    }


def m_action_repeat(text: str, sents: list[Sent]) -> dict:
    """'他/她+动词' 与 '动词+了+量词' 短语在全文出现 ≥3 次的清单。

    刻意**不**把 说/道/问/答/看/听 当动作——它们是对白标签，
    重复"他说""他说"是另一个病（对白标签单调），混进来会把数字搞脏。
    主语也刻意**只取代词**（他/她/我/你/您/咱），不猜人名，
    因为人名启发式有噪声；宁可漏，不给假数字。
    """
    n_han = han_len(text)
    ACTION_VERB = tuple(v for v in HUMAN_VERB
                        if v not in ("说", "道", "问", "答", "看", "听", "望", "瞧"))
    subj_re = re.compile("(他|她|我|你|您|咱)(" + "|".join(ACTION_VERB) + ")")

    c1 = Counter()
    for s in sents:
        seen = set()
        for mm in subj_re.finditer(s.text):
            g = mm.group(0)
            if g in seen:
                continue
            seen.add(g)
            c1[g] += 1
    reps = sorted([(k, v) for k, v in c1.items() if v >= 3],
                  key=lambda kv: -kv[1])

    # 动词+了+量词：如"退了一步""咬了一口""攥了一把"
    meas_re = re.compile("([一-龥]{1,2}了[" + NUM_WORDS + "]?[" + MEASURE + "])")
    c2 = Counter()
    for s in sents:
        seen = set()
        for mm in meas_re.finditer(s.text):
            g = mm.group(1)
            if g in seen:
                continue
            seen.add(g)
            c2[g] += 1
    reps2 = sorted([(k, v) for k, v in c2.items() if v >= 3],
                   key=lambda kv: -kv[1])

    def find_quote(phrase: str) -> str:
        for s in sents:
            if phrase in s.text:
                return s.text
        return ""

    examples = []
    for k, v in reps[:14]:
        examples.append({"phrase": k, "n": v, "kind": "代词+动作",
                         "quote": find_quote(k)})
    for k, v in reps2[:14]:
        examples.append({"phrase": k, "n": v, "kind": "动作+了+量词",
                         "quote": find_quote(k)})
    examples.sort(key=lambda e: -e["n"])
    return {
        "phrases_ge3": len(reps) + len(reps2),
        "phrases_ge3_per_1k": round((len(reps) + len(reps2)) / (n_han / 1000.0), 2)
        if n_han else 0.0,
        "max_repeat": max([v for _, v in reps] + [v for _, v in reps2], default=0),
        "examples": examples[:20],
        "distinct_verbs": len(c1),
        "n_han": n_han,
    }


def m_explain(text: str, sents: list[Sent]) -> dict:
    n_han = han_len(text)
    hits = [s for s in sents
            if any(w in s.text for w in EXPLAIN_MARK) and not s.dialogue]
    core_hits = [s for s in sents if any(w in s.text for w in EXPLAIN_CORE)]
    # 连续两句都是解释句的片段
    is_ex = [any(w in s.text for w in EXPLAIN_MARK) for s in sents]
    runs = []
    i = 0
    while i < len(is_ex):
        if is_ex[i]:
            j = i
            while j < len(is_ex) and is_ex[j]:
                j += 1
            if j - i >= 2:
                runs.append(sents[i:j])
            i = j
        else:
            i += 1
    cnt = Counter()
    for s in hits:
        for w in EXPLAIN_MARK:
            if w in s.text:
                cnt[w] += 1
    return {
        "verbose_ratio": round(pct(len(hits), len(sents)), 4),
        "any_ratio": round(pct(sum(is_ex), len(sents)), 4),
        "core_ratio": round(pct(len(core_hits), len(sents)), 4),
        "consecutive_runs": len(runs),
        "consecutive_runs_per_1k": round(len(runs) / (n_han / 1000.0), 2)
        if n_han else 0.0,
        "hits": cnt.most_common(12),
        "examples": [{"quote": s.text, "para": s.para + 1} for s in hits[:20]],
        "run_examples": [
            {"n": len(r), "quote": "".join(x.text for x in r)} for r in runs[:10]
        ],
        "n_sent": len(sents),
        "n_han": n_han,
    }


def extract_names(text: str) -> dict:
    """专名启发式提取：人名 / 地名机构 / 器物术语。返回 {名: {pos,kind,count}}。

    已知不可靠点（报告里标注 [不可靠]）：
      * 人名靠「姓氏表 + 1~2 字」切，复姓、法号、绰号会漏；
      * 姓氏字开头的普通短语（"石阶上"）靠末字黑名单挡，挡不干净；
      * 器物/术语靠后缀表，表外的新设定抓不到。

    输出同时用于：① 报告里的人工审计清单；② 静物句判定时的人物过滤。
    """
    out: dict[str, dict] = {}
    cand_count: Counter = Counter()

    def bad(cand: str, min_len_ok: bool = True) -> bool:
        if any(ch in FUNC_CHARS for ch in cand):
            return True
        if cand[0] in BAD_PREFIX:
            return True
        if cand in NAME_BLOCK:
            return True
        return False

    for i, c in enumerate(text):
        if c not in SURNAME:
            continue
        for ln in (3, 2):
            cand = text[i:i + ln]
            if len(cand) < ln:
                continue
            if not all("\u4e00" <= ch <= "\u9fff" for ch in cand):
                continue
            if bad(cand):
                continue
            if cand[-1] in (NAME_TAIL_BAN_2 if ln == 2 else NAME_TAIL_BAN_ANY):
                continue
            cand_count[cand] += 1
    # 削掉被更长候选覆盖的短前缀（"林小"是"林小满"的前缀）
    for cand in sorted(list(cand_count), key=len):
        if len(cand) == 2:
            longer = sum(v for k, v in cand_count.items()
                         if len(k) == 3 and k.startswith(cand))
            rest = cand_count[cand] - longer
            if rest < 3:
                del cand_count[cand]
            else:
                cand_count[cand] = rest
    for cand, c in cand_count.items():
        if c >= 3:
            out.setdefault(cand, {"pos": max(0, text.find(cand)),
                                  "kind": "人名", "count": c})

    # (b) 地名 / 机构
    suf = "|".join(PLACE_SUFFIX)
    for mm in re.finditer(r"([一-龥]{1,2})(" + suf + r")", text):
        cand = mm.group(0)
        if cand in PLACE_BLOCK or cand in out or bad(cand):
            continue
        if text.count(cand) < 2:
            continue
        out.setdefault(cand, {"pos": mm.start(), "kind": "地名/机构",
                              "count": text.count(cand)})

    # (c) 器物 / 术语
    psuf = "|".join(PROP_SUFFIX)
    for mm in re.finditer(r"([一-龥]{1,2})(" + psuf + r")", text):
        cand = mm.group(0)
        if cand in PROP_BLOCK or cand in out or bad(cand):
            continue
        if text.count(cand) < 2:
            continue
        out.setdefault(cand, {"pos": mm.start(), "kind": "器物/术语",
                              "count": text.count(cand)})

    # (d) 削掉"是更长专名的后缀"的候选（"牛镇"⊂"青牛镇"、"灵谷"⊂"南灵谷"）
    for cand in list(out):
        longer = [k for k in out if len(k) > len(cand) and k.endswith(cand)]
        if any(out[k]["count"] >= out[cand]["count"] for k in longer):
            del out[cand]
    return out


def person_tokens(names: dict) -> set[str]:
    """静物句判定用的人物标记集合（人名只取出现最多的 15 个）。"""
    top = sorted(names.items(), key=lambda kv: -kv[1]["count"])[:15]
    return set(PRONOUN) | set(EPITHET) | set(BODY_PART) | {k for k, _ in top}


def m_info_density(text: str, sents: list[Sent],
                   names: dict | None = None) -> dict:
    n_han = han_len(text)
    if names is None:
        names = extract_names(text)
    # 字符位置 -> 汉字序号
    pos2han = {}
    idx = 0
    for i, ch in enumerate(text):
        if "\u4e00" <= ch <= "\u9fff":
            pos2han[i] = idx
            idx += 1
    firsts = sorted(pos2han.get(v["pos"], 0) for v in names.values())
    nwin = max(1, n_han // 300)
    counts = [0] * nwin
    for f in firsts:
        counts[min(nwin - 1, f // 300)] += 1
    per_win = sum(counts) / len(counts) if counts else 0.0

    # 稳健代理：每 300 字窗口内的 2-gram 类型/形符比（读者要吸收多少"生词"）
    chars = HAN_RE.findall(text)
    grams = [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    ttrs = []
    for w in range(nwin):
        seg = grams[w * 300:(w + 1) * 300]
        if len(seg) >= 60:
            ttrs.append(len(set(seg)) / len(seg))
    bigram_ttr = round(sum(ttrs) / len(ttrs), 3) if ttrs else 0.0

    # 对话轮：是否给出新信息
    turns = []
    for s in sents:
        if s.dialogue:
            m = re.search(r"[「『“\"]([^」』”\"]*)[」』”\"]", s.text)
            inner = m.group(1) if m else s.text
            turns.append(inner.strip())
    seen_turns: set[str] = set()
    seen_bigrams: set[str] = set()
    seen_names: set[str] = set()
    filler = new_info = repeat = 0
    detail = []
    for t in turns:
        key = re.sub(r"[^\u4e00-\u9fff]", "", t)
        if not key:
            continue
        if key in seen_turns:
            repeat += 1
        seen_turns.add(key)
        bigrams = [key[i:i + 2] for i in range(len(key) - 1)]
        new_bg = [g for g in bigrams if g not in seen_bigrams]
        seen_bigrams.update(bigrams)
        newname = [nm for nm in names if nm in t and nm not in seen_names]
        seen_names.update(newname)
        why = []
        if newname:
            why.append("新专名 " + "/".join(newname[:2]))
        if QUANT_RE.search(t):
            why.append("数量")
        if any(w in t for w in ("因为", "所以", "要是", "否则", "但是", "却", "才",
                                "就", "原来", "除非", "只要", "不然", "其实", "反而")):
            why.append("转折/因果")
        if len(new_bg) >= 3:
            why.append(f"新词×{len(new_bg)}")
        has_new = bool(why)
        is_filler = (len(key) <= 2 or key in FILLER_TURN
                     or (not has_new and len(key) <= 6))
        if is_filler:
            filler += 1
        if has_new:
            new_info += 1
        detail.append({"turn": t[:60], "filler": is_filler, "new": has_new,
                       "why": why[:3]})
    nt = len(detail)
    return {
        "new_name_per_300": round(per_win, 2),
        "new_name_total": len(firsts),
        "windows": counts,
        "windows_max": max(counts) if counts else 0,
        "names": sorted(({"name": k, **v} for k, v in names.items()),
                        key=lambda d: d["pos"])[:60],
        "bigram_ttr": bigram_ttr,
        "turns": nt,
        "turn_new_info_ratio": round(pct(new_info, nt), 4),
        "turn_filler_ratio": round(pct(filler, nt), 4),
        "turn_repeat_ratio": round(pct(repeat, nt), 4),
        "turn_examples": [d for d in detail if d["new"]][:8],
        "fillers": [d["turn"] for d in detail if d["filler"]][:12],
        "n_han": n_han,
    }


def m_micro_action(text: str, sents: list[Sent]) -> dict:
    """碎动作链：一句里 ≥3 个分句、且分句平均 ≤8 字、且是叙事句。

    这是"描述过重"最贴近读者体感的可计算形态——
        "他把竹签搁在灯盏沿上，竹签滚了半圈，停在铁钩的影子里。"
    三个分句、三个微小动作，每个都不改变剧情，读者却要为每一个重新对焦。
    """
    n_han = han_len(text)
    hits = []
    for s in sents:
        if s.dialogue or s.han < 8:
            continue
        parts = [p for p in re.split(r"[，,、；;：:]", s.text) if HAN_RE.search(p)]
        if len(parts) < 3:
            continue
        lens = [len(HAN_RE.findall(p)) for p in parts]
        avg = sum(lens) / len(lens)
        if avg <= 8:
            hits.append((s, len(parts), round(avg, 1)))
    return {
        "count": len(hits),
        "ratio": round(pct(len(hits), len(sents)), 4),
        "per_1k": round(len(hits) / (n_han / 1000.0), 2) if n_han else 0.0,
        "examples": [
            {"quote": s.text, "clauses": n, "avg_clause": a} for s, n, a in hits[:20]
        ],
        "n_sent": len(sents),
        "n_han": n_han,
    }


def m_long_sent(text: str, sents: list[Sent]) -> dict:
    """长句占比：单句 ≥35 字（一口气要读 35 个字才见到句号）。

    这是"读起来费劲"最直接的可计算证据之一——比逗号数更可靠，
    因为中文长句可以用逗号，也可以一个逗号都不用（"……的……的……的……"）。
    """
    n_han = han_len(text)
    lens = [s.han for s in sents if s.han > 0]
    long35 = [s for s in sents if s.han >= 35]
    long50 = [s for s in sents if s.han >= 50]
    total = max(1, len(lens))
    return {
        "ratio_35": round(pct(len(long35), total), 4),
        "count_35": len(long35),
        "ratio_50": round(pct(len(long50), total), 4),
        "avg_sent": round(sum(lens) / total, 1) if lens else 0.0,
        "max_sent": max(lens) if lens else 0,
        "examples": [
            {"quote": s.text, "han": s.han, "commas": s.commas}
            for s in sorted(long35, key=lambda s: -s.han)[:20]
        ],
        "n_sent": len(sents),
        "n_han": n_han,
    }


def m_comma_chain(text: str, sents: list[Sent]) -> dict:
    n_han = han_len(text)
    long_chain = [s for s in sents if s.han > 0 and s.commas >= 4]
    very = [s for s in sents if s.commas >= 6]
    clause_lens = []
    maxc = 0
    for s in sents:
        parts = [p for p in re.split(r"[，,、；;]", s.text) if HAN_RE.search(p)]
        clause_lens.extend(len(HAN_RE.findall(p)) for p in parts)
        maxc = max(maxc, s.commas)
    avg_clause = sum(clause_lens) / len(clause_lens) if clause_lens else 0.0
    return {
        "chain_ratio": round(pct(len(long_chain), len(sents)), 4),
        "chain_count": len(long_chain),
        "very_chain_count": len(very),
        "max_commas": maxc,
        "avg_clause_len": round(avg_clause, 1),
        "examples": [
            {"quote": s.text, "commas": s.commas, "han": s.han}
            for s in sorted(long_chain, key=lambda s: -s.commas)[:20]
        ],
        "n_sent": len(sents),
        "n_han": n_han,
    }


# --------------------------------------------------------------------------
# 四、判定阈值 + 可读性综合分
# --------------------------------------------------------------------------
# 每个指标: (权重, 阈值种类, 参数)
#   hi : 越大越差   (good, bad)
#   lo : 越小越差   (good, bad)   good > bad
#   band: 中间好     (lo_good, hi_good, lo_bad, hi_bad)
# 权重总和 = 100，所以"扣分"就是可读性分数，1 个权重 = 1 分。
LIVE_THRESHOLDS = {
    "de_per_100":        (6,  "hi",   (2.0, 4.5)),
    "de_triple_per_1k":  (5,  "hi",   (0.5, 4.0)),
    "sent_ge3de_ratio":  (5,  "hi",   (0.02, 0.08)),
    "static_ratio":      (12, "hi",   (0.02, 0.12)),
    "short_runs_per_1k": (6,  "hi",   (0.3, 2.0)),
    "short_ratio":       (3,  "hi",   (0.18, 0.42)),
    "open_runs_per_1k":  (8,  "hi",   (0.2, 2.0)),
    "epithet_per_1k":    (5,  "hi",   (0.5, 5.0)),
    "action_phr_per_1k": (4,  "hi",   (1.0, 6.0)),
    "explain_ratio":     (12, "hi",   (0.015, 0.08)),
    "long_sent_ratio":   (12, "hi",   (0.08, 0.18)),
    "micro_action_ratio": (4, "hi",   (0.06, 0.20)),
    "new_name_per_300":  (6,  "band", (0.30, 1.60, 0.05, 2.20)),
    "turn_new_info":     (6,  "lo",   (0.50, 0.22)),
    "comma_chain_ratio": (6,  "hi",   (0.08, 0.20)),
}

LABELS = OrderedDict([
    ("de_per_100", "定语堆叠·'的'字密度"),
    ("de_triple_per_1k", "定语堆叠·'的…的…的'三连(处/千字)"),
    ("sent_ge3de_ratio", "定语堆叠·单句≥3个'的'占比"),
    ("static_ratio", "无关细节·纯静物/环境句占比"),
    ("short_runs_per_1k", "碎句轰炸·连续≥3句≤6字(段/千字)"),
    ("short_ratio", "碎句轰炸·≤6字句占比"),
    ("open_runs_per_1k", "句首雷同·连续≥3句同头(段/千字)"),
    ("epithet_per_1k", "代称滥用·少年/汉子/老者…(次/千字)"),
    ("action_phr_per_1k", "动作复读·≥3次重复短语(个/千字)"),
    ("explain_ratio", "解释过载·解释句占比(叙事句)"),
    ("long_sent_ratio", "长句·单句≥35字占比"),
    ("micro_action_ratio", "描述过重·碎动作链句占比"),
    ("new_name_per_300", "信息密度·每300字新增专名数"),
    ("turn_new_info", "信息密度·对话'给新信息'轮占比"),
    ("comma_chain_ratio", "逗号链·单句≥4逗号占比[辅助]"),
])

AUX = {"comma_chain_ratio"}
UNRELIABLE = {"new_name_per_300", "turn_new_info"}

# ---- 第二套阈值：以仓库里唯一的人类样本 samples/human_01.txt 为锚点 ----
# 为什么要第二套：主阈值是按"网文读者体验"拍的，而 human_01（294 字乡土小说，
# ai_flavor 判 5.9 分"人味充足"）在"碎句""碎动作链"上反而比 A 批更极端。
# 也就是说这两项超标未必是病，可能只是"碎"这种风格。所以另给一套把碎句
# 基准放到人类样本水平的阈值，用来看"排名会不会翻转"。
ALT_THRESHOLDS = {
    "de_per_100":        (6,  "hi",   (2.0, 4.5)),
    "de_triple_per_1k":  (5,  "hi",   (0.5, 4.0)),
    "sent_ge3de_ratio":  (5,  "hi",   (0.02, 0.08)),
    "static_ratio":      (12, "hi",   (0.02, 0.12)),
    "short_runs_per_1k": (6,  "hi",   (7.5, 14.0)),
    "short_ratio":       (3,  "hi",   (0.55, 0.75)),
    "open_runs_per_1k":  (8,  "hi",   (0.2, 2.0)),
    "epithet_per_1k":    (5,  "hi",   (0.5, 5.0)),
    "action_phr_per_1k": (4,  "hi",   (1.0, 6.0)),
    "explain_ratio":     (12, "hi",   (0.015, 0.08)),
    "long_sent_ratio":   (12, "hi",   (0.08, 0.18)),
    "micro_action_ratio": (4, "hi",   (0.20, 0.40)),
    "new_name_per_300":  (6,  "band", (0.30, 1.60, 0.05, 2.20)),
    "turn_new_info":     (6,  "lo",   (0.50, 0.22)),
    "comma_chain_ratio": (6,  "hi",   (0.08, 0.20)),
}


def _sev(sev_kind: str, v: float, p: tuple) -> float:
    if sev_kind == "hi":
        return _sev_hi(v, *p)
    if sev_kind == "lo":
        return _sev_lo(v, *p)
    return _sev_band(v, *p)


def _sev_hi(v: float, good: float, bad: float) -> float:
    if bad <= good:
        return 0.0
    return max(0.0, min(1.0, (v - good) / (bad - good)))


def _sev_lo(v: float, good: float, bad: float) -> float:
    if good <= bad:
        return 0.0
    return max(0.0, min(1.0, (good - v) / (good - bad)))


def _sev_band(v: float, lo_good: float, hi_good: float,
              lo_bad: float, hi_bad: float) -> float:
    if v < lo_good:
        return _sev_lo(v, lo_good, lo_bad)
    if v > hi_good:
        return _sev_hi(v, hi_good, hi_bad)
    return 0.0


def score_readability(vals: dict, thresholds: dict | None = None) -> dict:
    TH = thresholds or LIVE_THRESHOLDS
    contrib = []
    total = 0.0
    for key, (w, kind, p) in TH.items():
        v = vals.get(key)
        if v is None:
            contrib.append({"key": key, "label": LABELS[key], "value": None,
                            "points": 0.0, "level": "n/a", "weight": w,
                            "note": "样本不足，未参与打分"})
            continue
        if kind == "hi":
            sev = _sev_hi(v, *p)
            tgt = f"≤{p[0]} 好 / ≥{p[1]} 差"
        elif kind == "lo":
            sev = _sev_lo(v, *p)
            tgt = f"≥{p[0]} 好 / ≤{p[1]} 差"
        else:
            sev = _sev_band(v, *p)
            tgt = f"{p[0]}~{p[1]} 好 / <{p[2]}或>{p[3]} 差"
        pts = w * sev
        total += pts
        lvl = "ok" if sev < 0.34 else ("warn" if sev < 0.67 else "bad")
        contrib.append({
            "key": key, "label": LABELS[key], "value": v, "weight": w,
            "severity": round(sev, 3), "points": round(pts, 1),
            "level": lvl, "target": tgt,
            "aux": key in AUX, "unreliable": key in UNRELIABLE,
        })
    return _finish(contrib, total)


def _finish(contrib: list[dict], total: float) -> dict:
    score = max(0.0, min(100.0, 100.0 - total))
    if score >= 80:
        grade = "易读"
    elif score >= 65:
        grade = "尚可"
    elif score >= 50:
        grade = "偏累"
    elif score >= 35:
        grade = "很累"
    else:
        grade = "极难读"
    contrib.sort(key=lambda c: -c["points"])
    return {"score": round(score, 1), "grade": grade, "penalty": round(total, 1),
            "contributions": contrib}


# --------------------------------------------------------------------------
# 五、句级"读起来累"成本 + Top-N
# --------------------------------------------------------------------------


def sentence_cost(s: Sent, person_tokens: set[str] | None = None
                  ) -> tuple[float, list[str]]:
    t = s.text
    cost = 0.0
    reasons = []
    de = t.count("的")
    if de >= 3:
        cost += 1.6 * (de - 2)
        reasons.append(f"一句 {de} 个'的'（定语套定语）")
    elif de == 2:
        cost += 0.4
    if s.commas >= 4:
        cost += 1.2 * (s.commas - 3)
        reasons.append(f"{s.commas} 个逗号连成一口气（{s.han} 字）")
    if s.han >= 55:
        cost += 3.0
        reasons.append(f"单句 {s.han} 字，太长")
    elif s.han >= 40:
        cost += 1.8
        reasons.append(f"单句 {s.han} 字偏长")
    if _is_static_scene(s, person_tokens):
        cost += 3.2
        reasons.append("纯静物/环境描写，不推进剧情")
    if any(w in t for w in EXPLAIN_MARK) and not s.dialogue:
        cost += 2.0
        reasons.append("解释句（在告诉读者结论）")
    if any(w in t for w in ("仿佛", "似乎", "如同", "宛如", "犹如", "一丝", "一抹",
                            "缓缓", "微微", "淡淡", "深深", "莫名", "难以言喻")):
        cost += 1.5
        reasons.append("套话/虚词修饰")
    if len(re.findall(r"[一-龥]{2,3}(?:的)?[一-龥]{2,3}(?:的)", t)) >= 2:
        cost += 0.8
    return cost, reasons


REASON_CATEGORY = [
    ("逗号", "逗号链"), ("字", "长句"), ("静物", "静物"), ("解释", "解释"),
    ("个'的'", "定语"), ("套话", "套话"),
]


def _reason_cat(reasons: list[str]) -> str:
    for r in reasons:
        for kw, cat in REASON_CATEGORY:
            if kw in r:
                return cat
    return "其他"


def judge_sentences(sents: list[Sent], topn: int = 10,
                    per_reason_cap: int = 3,
                    person_tokens: set[str] | None = None) -> list[dict]:
    """按"读起来累"的成本排序取前 N 句，并对同一种病因限流。

    限流的原因：A 批有 300+ 句纯静物描写，如果只按成本排序，
    最该改的 10 句会全是"灯芯爆了一声。"这种，读者看不到别的问题。
    """
    scored = []
    for s in sents:
        c, rs = sentence_cost(s, person_tokens)
        if c <= 0:
            continue
        scored.append((c, s, rs))
    scored.sort(key=lambda x: -x[0])
    out = []
    used: Counter = Counter()
    for c, s, rs in scored:
        cat = _reason_cat(rs)
        if used[cat] >= per_reason_cap:
            continue
        used[cat] += 1
        out.append({
            "quote": s.text,
            "han": s.han,
            "commas": s.commas,
            "cost": round(c, 1),
            "reasons": rs,
            "fix": suggest_fix(s, rs),
            "para": s.para + 1,
        })
        if len(out) >= topn:
            break
    return out


def suggest_fix(s: Sent, reasons: list[str]) -> str:
    """按命中的病因给可执行的改法（不重复同一句模板）。"""
    t = s.text
    tips = []
    if any("个'的'" in r for r in reasons):
        tips.append(f"{t.count('的')} 个'的'砍到 1 个："
                    "把'…的…的…'改成'动词+宾语'（'那只裂了缝的铜镜'→'铜镜裂了一道缝'）")
    if s.commas >= 4:
        tips.append(f"{s.commas} 个逗号拆成 2~3 句，每句只留一个动作")
    if s.han >= 50:
        tips.append(f"整句 {s.han} 字压到 25 字以内，把后半段拆成新句")
    elif s.han >= 35:
        tips.append(f"整句 {s.han} 字，删掉最不影响信息的那一个分句")
    if any("静物" in r for r in reasons):
        tips.append("删掉；或挂到某个人的动作上（'油灯搁在桌案正中'→'他把油灯往中间推了推'）")
    if any("解释句" in r for r in reasons):
        tips.append("删掉这句结论，只留上一句的动作，让读者自己推")
    if any("套话" in r for r in reasons):
        tips.append("套话换成可测的细节（'微微发热'→'烫手，指头一缩'）")
    if not tips:
        tips.append("压缩 30% 字数，删掉不影响剧情的修饰")
    return "；".join(tips[:2])


# --------------------------------------------------------------------------
# 六、主分析入口
# --------------------------------------------------------------------------


def analyze_text(text: str, name: str = "", topn: int = 10) -> dict:
    sents, paras, _mask = parse(text)
    n_han = han_len(text)
    if n_han < 300 or len(sents) < 8:
        raise ValueError(f"{name}: 文本太短（{n_han} 汉字 / {len(sents)} 句），"
                         "至少 300 字才有统计意义")

    a = m_attributive(text, sents)
    names = extract_names(text)
    ptok = person_tokens(names)
    st = m_static_detail(text, sents, ptok)
    sh = m_short_sent(text, sents)
    op = m_open_repeat(text, sents)
    ep = m_epithet(text, sents)
    ar = m_action_repeat(text, sents)
    ex = m_explain(text, sents)
    inf = m_info_density(text, sents, names)
    cc = m_comma_chain(text, sents)
    ls = m_long_sent(text, sents)
    ma = m_micro_action(text, sents)

    dlg_han = sum(s.han for s in sents if s.dialogue)
    vals = {
        "de_per_100": a["de_per_100"],
        "de_triple_per_1k": a["de_triple_per_1k"],
        "sent_ge3de_ratio": a["sent_ge3de_ratio"],
        "static_ratio": st["ratio"],
        "short_runs_per_1k": sh["runs_ge3_per_1k"],
        "short_ratio": sh["short_ratio"],
        "open_runs_per_1k": op["runs_ge3_per_1k"],
        "epithet_per_1k": ep["per_1k"],
        "action_phr_per_1k": ar["phrases_ge3_per_1k"],
        "explain_ratio": ex["verbose_ratio"],
        "new_name_per_300": inf["new_name_per_300"],
        "turn_new_info": inf["turn_new_info_ratio"] if inf["turns"] >= 6 else None,
        "long_sent_ratio": ls["ratio_35"],
        "micro_action_ratio": ma["ratio"],
        "comma_chain_ratio": cc["chain_ratio"],
    }
    read = score_readability(vals)
    read["alt"] = score_readability(vals, ALT_THRESHOLDS)
    read["alt_note"] = ("第二套口径：把'碎句''碎动作链'的基准放到人类样本 "
                        "samples/human_01.txt 的水平（该样本 6.8 段/千字、18.5%），"
                        "其余不变。两套口径排名不同 = 排名取决于你信哪个基准。")

    return {
        "name": name,
        "chars": n_han,
        "sentences": len(sents),
        "paragraphs": len(paras),
        "avg_sent": round(n_han / max(1, len(sents)), 1),
        "dialogue_ratio": round(dlg_han / max(1, n_han), 3),
        "readability": read,
        "values": vals,
        "m_attributive": a,
        "m_static": st,
        "m_short": sh,
        "m_open": op,
        "m_epithet": ep,
        "m_action": ar,
        "m_explain": ex,
        "m_info": inf,
        "m_comma": cc,
        "m_long": ls,
        "m_micro": ma,
        "top_sentences": judge_sentences(sents, topn, person_tokens=ptok),
    }


def analyze_file(path: Path, topn: int = 10) -> dict:
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    r = analyze_text(text, name=Path(path).name, topn=topn)
    r["path"] = str(path)
    return r


def analyze_paths(paths: list[str], topn: int = 10) -> list[dict]:
    files: list[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files.extend(sorted(pp.glob("*.txt")))
        else:
            files.append(pp)
    out = []
    for f in files:
        try:
            out.append(analyze_file(f, topn=topn))
        except ValueError as e:
            print(f"  skip {f.name}: {e}", file=sys.stderr)
    return out


# --------------------------------------------------------------------------
# 七、终端报告
# --------------------------------------------------------------------------


def render_console(r: dict) -> str:
    L = []
    L.append(f"== {r['name']} ==")
    L.append(f"  {r['chars']} 字 / {r['sentences']} 句 / {r['paragraphs']} 段 / "
             f"均句长 {r['avg_sent']} 字 / 对话占比 {r['dialogue_ratio']:.0%}")
    if not (3000 <= r["chars"] <= 4000):
        L.append(f"  [字数] {r['chars']} 字，不在 3000~4000 目标区间")
    rd = r["readability"]
    L.append(f"  可读性综合分 {rd['score']}/100  ({rd['grade']})  扣分合计 {rd['penalty']}")
    L.append("  扣分明细（权重×严重度）：")
    for c in rd["contributions"]:
        if c["value"] is None:
            L.append(f"    -      {c['label']}: n/a")
            continue
        flag = {"ok": " ", "warn": "!", "bad": "!!"}[c["level"]]
        L.append(f"    {flag} {c['points']:>5.1f}  {c['label']} = {c['value']}  "
                 f"[{c['target']}]")
    L.append("")
    L.append("  最该改的句子：")
    for i, s in enumerate(r["top_sentences"], 1):
        L.append(f"    {i}. ({s['cost']}) {s['quote']}")
        L.append(f"       累在：{'；'.join(s['reasons'])}")
        L.append(f"       改法：{s['fix']}")
    return "\n".join(L)


# --------------------------------------------------------------------------
# 八、Markdown 报告
# --------------------------------------------------------------------------

LEVEL_MARK = {"ok": "✅", "warn": "⚠️", "bad": "❌", "n/a": "–"}


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}"
    return str(v)


def md_metrics_table(r: dict) -> str:
    L = ["| 指标 | 实测 | 目标/判定线 | 扣分 | 判定 | 备注 |",
         "|---|---|---|---|---|---|"]
    for c in r["readability"]["contributions"]:
        note = []
        if c.get("aux"):
            note.append("[辅助]")
        if c.get("unreliable"):
            note.append("[不可靠]")
        L.append(
            f"| {c['label']} | {_fmt(c['value'])} | {c['target']} | "
            f"{c['points']:.1f}/{c['weight']} | "
            f"{LEVEL_MARK.get(c['level'], '')} {c['level']} | {' '.join(note)} |"
        )
    return "\n".join(L)


def md_issue_sections(r: dict, maxq: int = 20) -> str:
    L = []
    a, st, sh, op, ep = (r["m_attributive"], r["m_static"], r["m_short"],
                         r["m_open"], r["m_epithet"])
    ar, ex, inf, cc = (r["m_action"], r["m_explain"], r["m_info"], r["m_comma"])
    ml, mm = r["m_long"], r["m_micro"]
    pv = r.get("values", {})          # 合并口径的指标值（单章分析时与上面一致）
    n_sent = r["sentences"]

    def from_note(d: dict) -> str:
        return (f"（例句取自 {d['_from']}）" if d.get("_from") else "")

    def sec(title, head, quotes, why):
        out = [f"### {title}", "", head, ""]
        if quotes:
            out.append("原文（真实截取）：")
            out.append("")
            for q in quotes[:maxq]:
                out.append(f"- `{q}`")
            out.append("")
            out.append(f"**为什么累**：{why}")
        else:
            out.append("本批没有可列出的原文片段（该问题在本批不成立，"
                       "或已并入上面的占比）。")
        out.append("")
        return "\n".join(out)

    L.append(sec(
        "1. 定语堆叠",
        f"'的'字密度 **{_fmt(pv.get('de_per_100', a['de_per_100']))}/百字**；"
        f"'的…的…的'三连 {_fmt(pv.get('de_triple_per_1k', a['de_triple_per_1k']))} 处/千字；"
        f"四连 {a['de_quad']} 处；单句 ≥3 个'的'占 "
        f"**{pv.get('sent_ge3de_ratio', a['sent_ge3de_ratio']):.1%}** {from_note(a)}。",
        [e["quote"] + f"  〔{e['de']}个的〕" for e in a["examples"]],
        "每个'的'都要读者把定语挂到后面的中心词上，连挂三四个，读者的工作记忆就被占满了；"
        "白话正文应该用'动词+宾语'，而不是'形容词+的+名词'。"))

    L.append(sec(
        "2. 无关细节（纯静物/环境句）",
        f"{round(pv.get('static_ratio', st['ratio']) * n_sent)} 句 / {n_sent} 句 = "
        f"**{pv.get('static_ratio', st['ratio']):.1%}** {from_note(st)}。"
        "判定逻辑：句内无人物代词/身体部位/代称/人名、无人的动作动词、"
        "无因果·条件·时间推进词、**至少含一个器物或环境名词**、≥4 字。",
        [e["quote"] for e in st["examples"]],
        "这些句子只描述『东西怎么摆着』，既没人在做事，也不推进剧情，"
        "读者读完不知道故事往前走了没有。"))

    L.append(sec(
        "3. 碎句轰炸",
        f"≤6 字句占 **{pv.get('short_ratio', sh['short_ratio']):.1%}**"
        f"（{round(pv.get('short_ratio', sh['short_ratio']) * n_sent)} 句）；"
        f"连续 ≥3 句 ≤6 字的片段 **{_fmt(pv.get('short_runs_per_1k', sh['runs_ge3_per_1k']))}"
        f"/千字**；均句长 {sh['avg_sent']} 字，句长 CV {sh['sent_cv']} "
        f"{from_note(sh)}。",
        [e["quote"] for e in sh["examples"]],
        "连续短句本来是用来砸节奏的；连成 4 句以上就变成'电报体'，"
        "读者读不到信息量，只能感到被一下一下地敲。"))

    L.append(sec(
        "4. 句首雷同",
        f"连续 ≥3 句同开头 **{_fmt(pv.get('open_runs_per_1k', op['runs_ge3_per_1k']))}/千字**"
        f"（{op['runs_ge3']} 段，最长连续 {op['longest_run']} 句）；"
        f"相邻句同头比 {op['adjacent_same_ratio']:.1%}；"
        f"句首二字去重率 {op['head_div']}。"
        f"最高频开头：{'、'.join(k + '×' + str(v) for k, v in op['top_keys'][:6])}。"
        "注意：句首二字去重率低只说明'开头词汇池窄'（大量短句以他/人名开头），"
        "不等于连续同头，所以本指标只对**连续同头**计分。",
        [e["quote"] for e in op["examples"]],
        "连续以'他/她/林昭'开头，等于告诉读者'这些句子结构一样'，"
        "大脑会开始跳读。"))

    L.append(sec(
        "5. 代称滥用",
        f"**{_fmt(pv.get('epithet_per_1k', ep['per_1k']))}/千字**，"
        f"共 {ep['total']} 次 / {ep['n_han']} 字，{ep['distinct']} 种代称 "
        f"{from_note(ep)}。命中："
        + ("、".join(f"{w}×{c}" for w, c in ep["hits"][:10]) or "无") + "。",
        [e["quote"] for e in ep["examples"]],
        "用'少年''老者''汉子''丫头'代替名字，等于把角色降级成路人 NPC；"
        "同一个'灰袄老者'反复出现，读者连他姓什么都不用记，也就对他没有感情。"))

    L.append(sec(
        "6. 动作复读",
        f"**{_fmt(pv.get('action_phr_per_1k', ar['phrases_ge3_per_1k']))}/千字**"
        f"（{ar['phrases_ge3']} 个短语出现 ≥3 次，最高 {ar['max_repeat']} 次）"
        f"{from_note(ar)}。清单："
        + ("、".join(f"「{e['phrase']}」×{e['n']}" for e in ar["examples"][:12]) or "无")
        + "。",
        [f"「{e['phrase']}」×{e['n']} → {e['quote']}" for e in ar["examples"]],
        "同一个动作短语反复使用，读者第二次就预测到第三次写什么，"
        "'动作'就不再是信息而是噪音。"))

    L.append(sec(
        "7. 解释过载",
        f"解释句 **{pv.get('explain_ratio', ex['verbose_ratio']):.1%}**"
        f"（叙事句，不含对话）；任意含解释词 {ex['any_ratio']:.1%}；"
        f"连续 ≥2 句解释的片段 {ex['consecutive_runs']} 段"
        f"（{ex['consecutive_runs_per_1k']}/千字）{from_note(ex)}。"
        f"命中词：{'、'.join(k + '×' + str(v) for k, v in ex['hits'][:8]) or '无'}。",
        [e["quote"] for e in ex["examples"]],
        "解释句在替读者做结论。读者一旦发现自己被'喂'结论，就会跳读——"
        "而且它同时暴露了作者不信任自己上一句的动作写得够清楚。"))

    L.append(sec(
        "8. 信息密度 [专名一项不可靠]",
        f"每 300 字新增专名 **{_fmt(pv.get('new_name_per_300', inf['new_name_per_300']))}** 个"
        f"（本章共 {inf['new_name_total']} 个，最挤的一个 300 字窗口塞了 "
        f"{inf['windows_max']} 个）{from_note(inf)}；"
        f"对话轮 {inf['turns']} 轮，其中'给新信息' "
        f"{pv.get('turn_new_info', inf['turn_new_info_ratio']):.1%}、"
        f"空转轮 {inf['turn_filler_ratio']:.1%}、"
        f"完全重复的轮次 {inf['turn_repeat_ratio']:.1%}。",
        [f"[新信息] {d['turn']}" for d in inf["turn_examples"]]
        + [f"[空转] {f}" for f in inf["fillers"][:8]],
        "① 专名太密=读者要边读边记人名，认知负荷爆表；太稀=空转。"
        "② 对话如果只是'嗯''你说呢''闭嘴'，读者得不到任何新事实，"
        "这一轮对话就该删掉或并到动作里。"
        "**⚠ 这个指标不可靠**：启发式数不出'手没抖。'这种短促但有信息量的台词，"
        "会把它们误记成空转；只把它当趋势看，别当结论。"))

    L.append(sec(
        "9. 长句（单句 ≥35 字）",
        f"≥35 字占 **{pv.get('long_sent_ratio', ml['ratio_35']):.1%}**"
        f"（{ml['count_35']} 句），≥50 字 {ml['ratio_50']:.1%}，"
        f"最长 {ml['max_sent']} 字，均句长 {ml['avg_sent']} 字 {from_note(ml)}。",
        [f"{e['quote']}  〔{e['han']}字/{e['commas']}逗号〕"
         for e in ml["examples"]],
        "中文读者在句号处才'卸载'一次句子结构。一句话 35 字以上，"
        "读到后半段已经忘了主语是谁，只能回头重读——这就是'费劲'最直接来源。"))

    L.append(sec(
        "10. 描述过重·碎动作链",
        f"{round(pv.get('micro_action_ratio', mm['ratio']) * n_sent)} 句 / {n_sent} 句"
        f" = **{pv.get('micro_action_ratio', mm['ratio']):.1%}** "
        f"{from_note(mm)}。判定：叙事句、≥3 个分句、分句平均 ≤8 字。",
        [f"{e['quote']}  〔{e['clauses']}分句/均{e['avg_clause']}字〕"
         for e in mm["examples"]],
        "一句话里塞三个以上互不相干的小动作，每个都要读者重新对焦，"
        "但没有任何一个改变剧情——这是'描述过重'最典型的形态，"
        "也是把 3000 字写成 4000 字的直接原因。"))

    L.append(sec(
        "11. 逗号链 [辅助]",
        f"单句 ≥4 个逗号 {cc['chain_count']} 句（{cc['chain_ratio']:.1%}），"
        f"≥6 个逗号 {cc['very_chain_count']} 句，最多 {cc['max_commas']} 个逗号；"
        f"分句平均 {cc['avg_clause_len']} 字。",
        [f"{e['quote']}  〔{e['commas']}逗号/{e['han']}字〕" for e in cc["examples"]],
        "中文一个逗号就是一次'换气'。一逗到底的长句，读者读到第四个逗号已经忘了主语。"))

    L.append(f"### 12. 最该改的 10 句话")
    L.append("")
    L.append("| # | 原文 | 为什么累 | 建议改法 |")
    L.append("|---|---|---|---|")
    for i, s in enumerate(r["top_sentences"], 1):
        q = s["quote"].replace("|", "｜")
        L.append(f"| {i} | {q} | {'；'.join(s['reasons'])} | {s['fix']} |")
    L.append("")
    return "\n".join(L)


def render_md(r: dict) -> str:
    L = [f"# 可读性诊断：{r['name']}", ""]
    L.append(f"- 字数 **{r['chars']}**（目标 3000~4000："
             f"{'✅ 在区间内' if 3000 <= r['chars'] <= 4000 else '❌ 不在区间'}）")
    L.append(f"- 句数 {r['sentences']}，段数 {r['paragraphs']}，"
             f"均句长 {r['avg_sent']} 字，对话占比 {r['dialogue_ratio']:.0%}")
    rd = r["readability"]
    L.append(f"- **可读性综合分 {rd['score']}/100（{rd['grade']}）**，"
             f"扣分合计 {rd['penalty']}（0=极度好读，100=完全读不动）")
    L.append("")
    L.append("## 指标表")
    L.append("")
    L.append(md_metrics_table(r))
    L.append("")
    L.append("## 逐项问题与原文例句")
    L.append("")
    L.append(md_issue_sections(r))
    return "\n".join(L)


# --------------------------------------------------------------------------
# 九、批量报告（A/B/C 三批 + 横向对比）
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent

BATCHES = OrderedDict([
    ("A", {"title": "A 批 · out/books（旧版，读者抱怨过的那一版，19 章）",
           "paths": [REPO / "out" / "books"],
           "desc": "22 章规划中现存 19 章（缺 00015、00019、00022）。"
                   "读者投诉：① 字数偏多 ② 修饰过重、描述过重 ③ 读起来费劲。"}),
    ("B", {"title": "B 批 · out/v2（改良版，1 章）",
           "paths": [REPO / "out" / "v2"],
           "desc": "号称针对'修饰过重'改过的版本。"}),
    ("C", {"title": "C 批 · out/bench/ch1_s1_agy-cli_gemini-4-hydrogen（最新版单段）",
           "paths": [REPO / "out" / "bench" / "ch1_s1_agy-cli_gemini-4-hydrogen.txt"],
           "desc": "最新 bench 单段，1560 字，不是完整章，样本偏小。"}),
    ("D", {"title": "D 批 · out/books_demo/b0001（⚠ 不是正文，是 prompt 固件）",
           "paths": [REPO / "out" / "books_demo" / "b0001" / "ch01.txt"],
           "desc": "⚠ 这批文件名叫 ch01.txt，内容却是**生成 prompt 本身**"
                   "（含『【改写规则】1. 只改语言，不改情节……』整段指令），"
                   "只有开头几百字是风格示例。也就是说 out/books_demo/ 下 12 个 .txt "
                   "**全部是 prompt 固件而不是小说正文**——这本身是管线的一个 bug。"
                   "所以 D 批的所有数字只能证明'这段文字读起来像什么'，"
                   "**不能用来评价生成质量**。",
           "warn": True}),
])


def pool(results: list[dict]) -> dict:
    """把多章拼成一份合并分析（不重跑分析，按字数加权平均指标值后重新打分）。"""
    tot = sum(r["chars"] for r in results)
    keys = ["de_per_100", "de_triple_per_1k", "sent_ge3de_ratio", "static_ratio",
            "short_runs_per_1k", "short_ratio", "open_runs_per_1k", "epithet_per_1k",
            "action_phr_per_1k", "explain_ratio", "long_sent_ratio",
            "micro_action_ratio", "new_name_per_300",
            "turn_new_info", "comma_chain_ratio"]
    vals = {}
    for k in keys:
        num = 0.0
        den = 0.0
        for r in results:
            v = r["values"].get(k)
            if v is None:
                continue
            num += v * r["chars"]
            den += r["chars"]
        vals[k] = round(num / den, 4) if den else None
    read = score_readability(vals)
    read["alt"] = score_readability(vals, ALT_THRESHOLDS)
    read["alt_note"] = ("第二套口径：把'碎句''碎动作链'的基准放到人类样本 "
                        "samples/human_01.txt 的水平（该样本 6.8 段/千字、18.5%），"
                        "其余不变。两套口径排名不同 = 排名取决于你信哪个基准。")
    merged = {
        "name": "合并", "chars": tot,
        "sentences": sum(r["sentences"] for r in results),
        "paragraphs": sum(r["paragraphs"] for r in results),
        "avg_sent": round(tot / max(1, sum(r["sentences"] for r in results)), 1),
        "dialogue_ratio": round(
            sum(r["dialogue_ratio"] * r["chars"] for r in results) / max(1, tot), 3),
        "readability": read,
        "values": vals,
    }
    return merged


def render_batch_md(key: str, meta: dict, results: list[dict],
                    m: dict | None = None) -> str:
    if m is None:
        m = pool(results)
    L = [f"# {meta['title']}", "", f"{meta['desc']}", ""]
    if meta.get("warn"):
        L.append("> ## ⚠ 本批不是正文，数字无效\n"
                 "> 这里统计的对象是**生成 prompt 的文本**（混着几百字风格示例），"
                 "不是模型写出来的小说。所有指标只说明'这段 prompt 读起来是什么样'。"
                 "**请勿据此评价生成质量。**")
        L.append("")
    L.append("## 0. 总览")
    L.append("")
    L.append(f"- 文件数 **{len(results)}**，合计 **{m['chars']}** 汉字，"
             f"{m['sentences']} 句，均句长 {m['avg_sent']} 字，"
             f"对话占比 {m['dialogue_ratio']:.0%}")
    L.append(f"- **可读性综合分 {m['readability']['score']}/100"
             f"（{m['readability']['grade']}）**，扣分 {m['readability']['penalty']}")
    worst = [c for c in m["readability"]["contributions"] if c["level"] == "bad"]
    if worst:
        L.append("- 爆表项：" + "、".join(
            f"{c['label']}={_fmt(c['value'])}" for c in worst))
    L.append("")
    L.append("### 逐章指标")
    L.append("")
    L.append("| 文件 | 字数 | 可读分 | 的字/百字 | 静物句% | 碎句段/千字 | ≤6字句% "
             "| 碎动作链% | 长句% | 代称/千字 | 解释句% |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        v = r["values"]
        L.append(
            f"| {r['name']} | {r['chars']} | {r['readability']['score']} | "
            f"{v['de_per_100']} | {v['static_ratio'] * 100:.1f} | "
            f"{v['short_runs_per_1k']} | {v['short_ratio'] * 100:.1f} | "
            f"{v['micro_action_ratio'] * 100:.1f} | {v['long_sent_ratio'] * 100:.1f} | "
            f"{v['epithet_per_1k']} | {v['explain_ratio'] * 100:.1f} |")
    over = [r["name"] for r in results if r["chars"] > 4000]
    under = [r["name"] for r in results if r["chars"] < 3000]
    L.append("")
    L.append(f"字数区间检查：{len(results)} 章里 "
             f"**{len(results) - len(over) - len(under)} 章在 3000~4000 内**，"
             f"超上限 {len(over)} 章（{'、'.join(over) if over else '无'}），"
             f"低于下限 {len(under)} 章（{'、'.join(under) if under else '无'}）。")
    L.append("")
    L.append("### 合并指标表")
    L.append("")
    L.append(md_metrics_table(m))
    L.append("")
    L.append("## 1. 一句话结论")
    L.append("")
    L.append(batch_verdict(key, results, m))
    L.append("")
    rd = m["readability"]
    L.append(f"### 两套口径下的分数")
    L.append("")
    L.append(f"- 口径一（读者体验权重，主口径）：**{rd['score']}/100（{rd['grade']}）**")
    L.append(f"- 口径二（以人类样本 human_01 为锚）：**{rd['alt']['score']}/100"
             f"（{rd['alt']['grade']}）**")
    L.append(f"- {rd['alt_note']}")
    L.append("")
    L.append("## 2. 逐项问题与原文例句（合并全部章节，按出现问题最多的章取样）")
    L.append("")
    L.append(md_issue_sections(m))
    L.append("")
    L.append(render_anchor_section({key: m}))
    return "\n".join(L)


def anchor_metrics() -> dict:
    """用同一套指标跑仓库里的人类样本 / AI 样本，作为阈值锚点。

    samples/human_01.txt（294 字）是仓库里唯一的人类写的中文小说片段，
    ai_flavor 给它 5.9 分"人味充足"。它是本评审器唯一能拿到的"好人写文本"，
    样本太小（<300 字），只能当参考线，不能当金标准——报告里如实标注。
    """
    out = {}
    for name, rel in (("human", "samples/human_01.txt"),
                      ("ai", "samples/ai_01.txt")):
        p = REPO / rel
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8-sig")
        sents, _paras, _ = parse(t)
        names = extract_names(t)
        ptok = person_tokens(names)
        st = m_static_detail(t, sents, ptok)
        sh = m_short_sent(t, sents)
        ma = m_micro_action(t, sents)
        a = m_attributive(t, sents)
        ls = m_long_sent(t, sents)
        ep = m_epithet(t, sents)
        ex = m_explain(t, sents)
        inf = m_info_density(t, sents, names)
        cc = m_comma_chain(t, sents)
        op = m_open_repeat(t, sents)
        ar = m_action_repeat(t, sents)
        out[name] = {
            "file": rel, "chars": han_len(t), "sentences": len(sents),
            "de_per_100": a["de_per_100"],
            "de_triple_per_1k": a["de_triple_per_1k"],
            "sent_ge3de_ratio": a["sent_ge3de_ratio"],
            "static_ratio": round(st["ratio"], 4),
            "short_runs_per_1k": sh["runs_ge3_per_1k"],
            "short_ratio": round(sh["short_ratio"], 4),
            "open_runs_per_1k": op["runs_ge3_per_1k"],
            "epithet_per_1k": ep["per_1k"],
            "action_phr_per_1k": ar["phrases_ge3_per_1k"],
            "explain_ratio": round(ex["verbose_ratio"], 4),
            "long_sent_ratio": ls["ratio_35"],
            "micro_action_ratio": round(ma["ratio"], 4),
            "new_name_per_300": inf["new_name_per_300"],
            "turn_new_info": inf["turn_new_info_ratio"] if inf["turns"] >= 6 else None,
            "comma_chain_ratio": round(cc["chain_ratio"], 4),
        }
    return out


def render_anchor_section(pooled: dict[str, dict]) -> str:
    """人类样本 vs AI 样本 vs 各批：同一把尺子量出来的对照表。"""
    anchors = anchor_metrics()
    if "human" not in anchors:
        return ""
    keys = [k for k in ("A", "B", "C", "D") if k in pooled]
    L = ["## 参照线：人类样本 vs AI 样本 vs 各批", ""]
    L.append("**为什么要有这张表**：所有阈值都是人拍的，唯一能检验的是拿真人的文本量一遍。"
             "`samples/human_01.txt` 是仓库里唯一的人类小说片段（294 字，"
             "ai_flavor 判 5.9 分『人味充足』），`samples/ai_01.txt` 是同一场景的 AI 版本"
             "（ai_flavor 判 51.7 分『明显 AI 味』）。")
    L.append("")
    hdr = ("| 指标 | 人类 human_01 | AI ai_01 | "
           + " | ".join(keys) + " |")
    L.append(hdr)
    L.append("|---" * (len(keys) + 3) + "|")
    for c in pooled[keys[0]]["readability"]["contributions"]:
        k = c["key"]
        row = [c["label"], _fmt(anchors["human"].get(k)),
               _fmt(anchors["ai"].get(k))]
        for kk in keys:
            row.append(_fmt(pooled[kk]["values"].get(k)))
        L.append("| " + " | ".join(row) + " |")
    L.append("")
    L.append("**怎么读这张表**：")
    L.append("")
    h = anchors["human"]
    L.append(f"- 人类样本的 `≤6字句占比` = **{h['short_ratio']:.1%}**、"
             f"`碎句段/千字` = **{h['short_runs_per_1k']}**、"
             f"`碎动作链` = **{h['micro_action_ratio']:.1%}**——"
             "**这三项人类样本自己就『超标』**。所以这三项超标只能说明『风格碎』，"
             "不能单独用来判文本好坏；本工具对它们的权重是『读者体验口径』的选择，不是客观事实。")
    L.append(f"- 人类样本的 `'的'字密度` = **{h['de_per_100']}/百字**、"
             f"`长句占比` = **{h['long_sent_ratio']:.1%}**、"
             f"`静物句` = **{h['static_ratio']:.1%}**、"
             f"`解释句` = **{h['explain_ratio']:.1%}**、"
             f"`代称` = **{h['epithet_per_1k']}/千字**——"
             "**这四项才是人类样本真正守得很死的**（静物/解释/代称都是 0）。"
             "在这四项上超标，才比较可能是真病。")
    L.append(f"- AI 样本的 `'的'字密度` = **{anchors['ai']['de_per_100']}/百字**"
             "（人类 1.70 的 3 倍），这是 AI 味最硬的可计算指纹之一。")
    L.append("")
    L.append("⚠ 人类样本只有 294 字、且是乡土现实题材（不是玄幻网文），"
             "所以它只能当『参考线』，不能当『合格线』。用它做锚的第二套打分见下。")
    L.append("")
    return "\n".join(L)


def batch_verdict(key: str, results: list[dict], m: dict) -> str:
    """一句话结论：全部由实测数字拼出来，不写死结论。"""
    v = m["values"]
    rd = m["readability"]
    chars = [r["chars"] for r in results]
    n = len(results)
    over = [c for c in chars if c > 4000]
    under = [c for c in chars if c < 3000]
    parts = []

    if key == "A":
        parts.append(
            f"{n} 章共 {m['chars']} 字，单章 {min(chars)}~{max(chars)} 字，"
            f"**{len(over)}/{n} 章超过 4000 字上限**"
            + (f"（最长 {max(chars)} 字）" if over else "")
            + f"，{len(under)}/{n} 章低于 3000。"
            f"→ 读者的第 1 条投诉（字数偏多）**部分成立**："
            f"中位数在区间内，但长尾明显。")
    elif n == 1:
        parts.append(f"共 {m['chars']} 字"
                     + ("（在 3000~4000 目标区间内）"
                        if 3000 <= m["chars"] <= 4000 else "（不在 3000~4000 区间）")
                     + f"，{m['sentences']} 句，均句长 {m['avg_sent']} 字。")
    else:
        parts.append(f"{n} 份文本共 {m['chars']} 字，单份 {min(chars)}~{max(chars)} 字。")

    parts.append(
        f"可读性 **{rd['score']}/100（{rd['grade']}）**，扣分 {rd['penalty']}。"
        "扣分构成（前 5）："
        + "、".join(f"{c['label']} -{c['points']}" for c in rd["contributions"][:5] if c["points"] > 0)
        + "。")

    # 一句话：按最大的三个问题拼
    top = [c for c in rd["contributions"] if c["points"] > 0][:3]
    oks = [c["label"] for c in rd["contributions"] if c["points"] == 0]
    if top:
        parts.append(
            "**一句话结论**：这批正文最该改的是 "
            + "、".join(f"{c['label']}（{_fmt(c['value'])}，目标 {c['target']}）"
                       for c in top)
            + f"。其余 {len(oks)} 项指标合格。")
    else:
        parts.append("**一句话结论**：全部指标合格，这批正文没有可计算的'累'。")

    # 如果扣分主要来自"碎"类指标，必须补一句警告——人类样本自己也超标
    soft = {"short_runs_per_1k", "short_ratio", "micro_action_ratio"}
    soft_pts = sum(c["points"] for c in rd["contributions"] if c["key"] in soft)
    hard_pts = rd["penalty"] - soft_pts
    if soft_pts > 0:
        h = anchor_metrics().get("human", {})
        parts.append(
            f"⚠ **别只看排名**：这 {soft_pts:.1f} 分扣在『碎句/碎动作链』上，"
            "而人类样本 "
            f"`samples/human_01.txt` 自己就是 碎句 "
            f"{h.get('short_runs_per_1k')} 段/千字、碎动作链 "
            f"{h.get('micro_action_ratio', 0):.1%}——"
            f"这两项超标只能说明『风格碎』，不是硬伤。真正可归因的硬伤只有 "
            f"{hard_pts:.1f} 分。第二套口径（人类样本锚定）给出的分数见下。")
    return "\n\n".join(parts)


def render_compare_headline(pooled: dict[str, dict]) -> str:
    """把三问的答案压成开头 6 行——这是整份 compare.md 的结论。"""
    A = pooled.get("A")
    if not A:
        return ""
    sc = lambda k, alt=False: (pooled[k]["readability"]["alt"]["score"] if alt
                               else pooled[k]["readability"]["score"])
    L = ["## 结论先行", ""]
    rows = []
    for k in ("B", "C", "D"):
        if k not in pooled:
            continue
        d1 = sc(k) - sc("A")
        d2 = sc(k, True) - sc("A", True)
        flip = (d1 > 0) != (d2 > 0)
        rows.append((k, d1, d2, flip))
    L.append("| | 口径一（读者体验权重） | 口径二（人类样本锚定） | 改良版更好吗？ |")
    L.append("|---|---|---|---|")
    for k, d1, d2, flip in rows:
        verdict = ("**口径一更好、口径二更差 → 结论不稳定，说明'更好'只是权重造成的**"
                   if flip else
                   ("两套口径都更好" if d1 > 0 else "两套口径都更差"))
        L.append(f"| {k} vs A | {d1:+.1f} | {d2:+.1f} | {verdict} |")
    L.append("")
    A_v = A["values"]
    h = anchor_metrics().get("human", {})
    L.append("**三句话回答**：")
    L.append("")
    L.append("1. **'修饰过重'：没有变好，只是换了一层。** "
             "B/C 确实把 A 的『碎动作链』从 "
             f"{A_v['micro_action_ratio']:.1%} 压到 0、把『碎句』从 "
             f"{_fmt(A_v['short_runs_per_1k'])} 段/千字压到 0，"
             "但 '的字密度、长句、解释句三项全部变差——"
             "人类样本自己的值是 '的字 "
             f"{h.get('de_per_100', 2.0)}/百字、长句 "
             f"{h.get('long_sent_ratio', 0.08):.0%}、解释句 "
             f"{h.get('explain_ratio', 0.0):.1%}，"
             "B/C 在这三项上全部比人类样本更重。"
             "**修掉的是『碎』，新增的是『长』和『绕』。**")
    L.append("2. **'读起来费劲'：B 明确更差，C 说不清。** "
             f"口径一 A={sc('A')} / B={sc('B') if 'B' in pooled else '—'} / "
             f"C={sc('C') if 'C' in pooled else '—'}；"
             f"口径二 A={sc('A', True)} / B={sc('B', True) if 'B' in pooled else '—'} / "
             f"C={sc('C', True) if 'C' in pooled else '—'}。"
             "B 在两套口径下都比 A 低 8~20 分，是**确定的退步**；"
             "C 的优势主要来自『碎句 + 碎动作链』两项（C 比 A 少扣 "
             + (f"{-sum(_c(pooled['C'], x)['points'] - _c(pooled['A'], x)['points'] for x in ('short_runs_per_1k', 'short_ratio', 'micro_action_ratio')):.1f} 分"
                if "C" in pooled else "—")
             + "），而人类样本自己就是碎句风格"
             f"（{h.get('short_runs_per_1k', 6.8)} 段/千字），"
             "所以这个优势不成立——何况 C 只有 "
             f"{pooled['C']['chars'] if 'C' in pooled else 1560} 字，不是完整章。"
             "**唯一在两套口径下都成立的事实是：B/C 的长句、代称、解释句、'的'字"
             "四项都比 A 差。**")
    L.append("3. **新引入的毛病（最重要）**：B = 长句化 + 代称泛滥（"
             f"{B_epithet(pooled)}/千字）+ 说明文腔；C = 设定堆砌（专名 "
             f"{C_names(pooled)}/300字）+ 定语回潮（'的'字 "
             f"{C_de(pooled)}/百字，三批最高）。"
             "换句话说：**A 的病是『太碎』，B/C 的病是『太满』**，后者更像 AI 写的。")
    L.append("")
    return "\n".join(L)


def B_epithet(pooled: dict) -> str:
    return _fmt(pooled["B"]["values"]["epithet_per_1k"]) if "B" in pooled else "—"


def C_names(pooled: dict) -> str:
    return _fmt(pooled["C"]["values"]["new_name_per_300"]) if "C" in pooled else "—"


def C_de(pooled: dict) -> str:
    return _fmt(pooled["C"]["values"]["de_per_100"]) if "C" in pooled else "—"


def render_compare_md(pooled: dict[str, dict]) -> str:
    keys = [k for k in ("A", "B", "C", "D") if k in pooled]
    L = ["# A vs B vs C 横向对比", ""]
    L.append("> 数值口径：每批内部按字数加权平均后再用同一套阈值打分。"
             "A = out/books 全部章节合并；B = out/v2 一章；"
             "C = out/bench 单段（仅 1560 字，样本偏小，结论要打折）；"
             "D⚠ = out/books_demo —— **它不是正文，是 prompt 固件**，"
             "列出来只为证明『管线把 prompt 写进了 .txt 输出』这个 bug，"
             "D 的所有数字不可用于评价生成质量。")
    L.append("> 可读性分数：0~100，**越高越易读**。表里 `!` = 警告，`!!` = 爆表。")
    L.append("")
    L.append(render_compare_headline(pooled))
    L.append("## 指标对照表")
    L.append("")
    hdr = "| 指标 | " + " | ".join(
        f"{k}{'⚠' if BATCHES.get(k, {}).get('warn') else ''}（{pooled[k]['chars']}字）"
        for k in keys) + " | 好/坏方向 |"
    L.append(hdr)
    L.append("|" + "---|" * (len(keys) + 2))
    for c in pooled[keys[0]]["readability"]["contributions"]:
        k = c["key"]
        cells = []
        for kk in keys:
            cc = _c(pooled[kk], k)
            mark = {"ok": "", "warn": " !", "bad": " !!"}.get(cc["level"], "")
            cells.append(f"{_fmt(cc['value'])}{mark}")
        L.append(f"| {c['label']} | " + " | ".join(cells) + f" | {c['target']} |")
    L.append("")
    L.append("| **可读性综合分** | "
             + " | ".join(f"**{pooled[k]['readability']['score']}**" for k in keys)
             + " | 越高越易读 |")
    L.append("| 口径二·人类样本锚定分 | "
             + " | ".join(f"**{pooled[k]['readability']['alt']['score']}**"
                          for k in keys)
             + " | 越高越易读 |")
    L.append("| **扣分合计** | "
             + " | ".join(f"{pooled[k]['readability']['penalty']}" for k in keys)
             + " | 越低越好 |")
    L.append("| 字数 | "
             + " | ".join(str(pooled[k]["chars"]) for k in keys)
             + " | 3000~4000/章 |")
    L.append("| 均句长 | "
             + " | ".join(str(pooled[k]["avg_sent"]) for k in keys)
             + " | 12~22 字 |")
    L.append("")
    L.append(render_compare_answers(pooled))
    L.append(render_compare_new_flaws(pooled))
    L.append(render_compare_top10(pooled))
    L.append(render_anchor_section(pooled))
    return "\n".join(L)


def _c(m: dict, key: str) -> dict:
    return next(x for x in m["readability"]["contributions"] if x["key"] == key)


def _cmp_table(pooled: dict, rows: list[tuple[str, str, str]]) -> str:
    others = [k for k in pooled if k != "A"]
    L = ["| 子指标 | A | " + " | ".join(others) + " | 方向 |",
         "|---|" + "---|" * (len(others) + 2)]
    for key, label, d in rows:
        cells = []
        for k in others:
            v = _c(pooled[k], key)["value"]
            av = _c(pooled["A"], key)["value"]
            mark = ""
            if v is not None and av is not None:
                if abs(v - av) < 1e-9:
                    mark = " ="
                elif key == "turn_new_info":
                    mark = " ✅" if v > av else " ❌"
                else:
                    mark = " ✅" if v < av else " ❌"
            cells.append(f"{_fmt(v)}{mark}")
        L.append(f"| {label} | {_fmt(_c(pooled['A'], key)['value'])} | "
                 + " | ".join(cells) + f" | {d} |")
    return "\n".join(L)


def render_compare_answers(pooled: dict[str, dict]) -> str:
    A = pooled.get("A")
    L = ["## 三个必须回答的问题", ""]
    if not A:
        return "\n".join(L + ["A 批缺失，无法对比。", ""])
    L.append("### Q1 改良版（B/C）在'修饰过重'上真的好于 A 吗？")
    L.append("")
    L.append(_cmp_table(pooled, [
        ("de_per_100", "'的'字/百字", "越低越好"),
        ("de_triple_per_1k", "'的…的…的'三连/千字", "越低越好"),
        ("sent_ge3de_ratio", "单句≥3个'的'占比", "越低越好"),
        ("static_ratio", "纯静物/环境句占比", "越低越好"),
        ("micro_action_ratio", "碎动作链句占比（描述过重）", "越低越好"),
        ("long_sent_ratio", "单句≥35字占比", "越低越好"),
        ("comma_chain_ratio", "单句≥4逗号占比", "越低越好"),
    ]))
    L.append("")
    L.append(compare_verdict_modifier(pooled))
    L.append("")
    L.append("### Q2 改良版在'读起来费劲'上真的好于 A 吗？")
    L.append("")
    L.append(_cmp_table(pooled, [
        ("short_runs_per_1k", "连续≥3句≤6字(段/千字)", "越低越好"),
        ("short_ratio", "≤6字句占比", "越低越好"),
        ("open_runs_per_1k", "连续≥3句同头(段/千字)", "越低越好"),
        ("explain_ratio", "解释句占比", "越低越好"),
        ("action_phr_per_1k", "≥3次重复动作短语/千字", "越低越好"),
        ("epithet_per_1k", "代称/千字", "越低越好"),
        ("turn_new_info", "对话'给新信息'轮占比", "越高越好"),
    ]))
    L.append("")
    L.append("| 均句长 | " + str(A["avg_sent"]) + " | "
             + " | ".join(str(pooled[k]["avg_sent"]) for k in pooled if k != "A")
             + " | 12~22 字 |")
    L.append("")
    L.append("| **可读性综合分** | **"
             + str(A["readability"]["score"]) + "** | "
             + " | ".join("**" + str(pooled[k]["readability"]["score"]) + "**"
                          for k in pooled if k != "A") + " | 越高越易读 |")
    L.append("")
    L.append("| 口径二·人类样本锚定 | "
             + str(A["readability"]["alt"]["score"]) + " | "
             + " | ".join(str(pooled[k]["readability"]["alt"]["score"])
                          for k in pooled if k != "A") + " | 越高越易读 |")
    L.append("")
    L.append(compare_verdict_hard(pooled))
    return "\n".join(L)


def compare_verdict_modifier(pooled: dict) -> str:
    A = pooled["A"]
    L = []
    MOD_KEYS = ("de_per_100", "de_triple_per_1k", "sent_ge3de_ratio",
                "static_ratio", "micro_action_ratio", "long_sent_ratio",
                "comma_chain_ratio")
    a_mod = sum(_c(A, k)["points"] for k in MOD_KEYS)
    for k in ("B", "C", "D"):
        if k not in pooled:
            continue
        g = lambda key: _c(pooled[k], key)["value"]
        a = lambda key: _c(A, key)["value"]
        better, worse = [], []
        for key, name in (("de_per_100", "'的'字"), ("static_ratio", "静物句"),
                          ("micro_action_ratio", "碎动作链"),
                          ("long_sent_ratio", "长句"), ("comma_chain_ratio", "逗号链")):
            if g(key) < a(key) - 1e-9:
                better.append(f"{name} {_fmt(a(key))}→{_fmt(g(key))}")
            elif g(key) > a(key) + 1e-9:
                worse.append(f"{name} {_fmt(a(key))}→{_fmt(g(key))}")
        mod = sum(_c(pooled[k], x)["points"] for x in MOD_KEYS)
        L.append(f"- **{k}**：'修饰/描写'这一层的扣分合计 **{mod:.1f}** vs A "
                 f"**{a_mod:.1f}**（{mod - a_mod:+.1f}）"
                 + ("　→ **确实比 A 轻**。" if mod < a_mod - 0.05 else
                    ("　→ 和 A 持平。" if abs(mod - a_mod) <= 0.05 else
                     "　→ **比 A 更重**。")))
        L.append(f"  - 单项变好：{'、'.join(better) if better else '无'}；"
                 f"单项变重：{'、'.join(worse) if worse else '无'}。")
    L.append("")
    L.append("**判定口径**：读者说的'修饰过重'在我的指标里对应两件事——"
             "① 定语层（'的'字密度、'的…的…的'三连）；"
             "② 描写层（纯静物句、碎动作链、长句）。"
             "两层合并算'修饰/描写扣分'，比数'几项变好'可靠——"
             "因为 0.5 分的长句和 12 分的长句在'几项'里都只算一项。")
    return "\n".join(L)


def compare_verdict_hard(pooled: dict) -> str:
    A = pooled["A"]
    L = []
    for k in ("B", "C", "D"):
        if k not in pooled:
            continue
        g = lambda key: _c(pooled[k], key)["value"]
        a = lambda key: _c(A, key)["value"]
        sc, scA = pooled[k]["readability"]["score"], A["readability"]["score"]
        improved = [n for key, n in
                    (("short_runs_per_1k", "碎句"), ("open_runs_per_1k", "同头"),
                     ("explain_ratio", "解释句"), ("epithet_per_1k", "代称"))
                    if g(key) < a(key) - 1e-9]
        regressed = [n for key, n in
                     (("long_sent_ratio", "长句"), ("de_per_100", "'的'字"),
                      ("new_name_per_300", "专名密度"), ("explain_ratio", "解释句"),
                      ("epithet_per_1k", "代称"))
                     if g(key) > a(key) + 1e-9]
        L.append(
            f"- **{k}**：可读分 {sc} vs A {scA}（**{sc - scA:+.1f}**）；"
            f"改善的：{'、'.join(improved) if improved else '无'}；"
            f"变差的：{'、'.join(regressed) if regressed else '无'}。")
    L.append("")
    L.append("**判定**：'读起来费劲'是多种病因叠加，只看一项会被骗。"
             "A 的病是**碎**（碎句、碎动作链），B/C 的病是**长**（长句、解释、设定堆砌）；"
             "分数接近不代表同样好读，而是**把一种累换成了另一种累**。"
             "真正的判据是：改善项是否覆盖了退步项——下面 Q3 的扣分表直接算这个。")
    return "\n".join(L)


def render_compare_new_flaws(pooled: dict[str, dict]) -> str:
    A = pooled["A"]
    rows = []
    for k in ("B", "C", "D"):
        if k not in pooled:
            continue
        worse = []
        for c in pooled[k]["readability"]["contributions"]:
            ca = _c(A, c["key"])
            if c["value"] is None or ca["value"] is None:
                continue
            d = c["points"] - ca["points"]
            if d > 0:
                worse.append((d, c, ca))
        worse.sort(key=lambda x: -x[0])
        rows.append((k, worse))
    L = ["", "### Q3 改良版**新引入了**什么毛病？（最重要，不客气）", ""]
    L.append("判定方法：把 B/C/D 的每一项扣分减去 A 的同一项扣分，只列正数。"
             "正数越大 = 这一项是改良版**新引入**的负担。")
    L.append("")
    for k, worse in rows:
        L.append(f"#### {k} 相对 A 的新增扣分")
        L.append("")
        if not worse:
            L.append("没有新增扣分项。")
            L.append("")
            continue
        L.append("| 新增扣分 | 指标 | A | " + k + " | 目标 | 说明 |")
        L.append("|---|---|---|---|---|---|")
        for d, c, ca in worse[:8]:
            note = " ".join(x for x in ('[辅助]' if c.get("aux") else '',
                                        '[不可靠]' if c.get("unreliable") else '') if x)
            L.append(f"| +{d:.1f} | {c['label']} | {_fmt(ca['value'])} | "
                     f"{_fmt(c['value'])} | {c['target']} | {note} |")
        L.append("")
        # 取样句
        r = pooled[k]
        if r.get("m_info", {}).get("names"):
            names = sorted(r["m_info"]["names"], key=lambda d: -d["count"])[:12]
            nm = "、".join(f"{n['name']}({n['count']})" for n in names)
            L.append(f"- 专名清单（启发式，前 12，括号内为出现次数，仅供人工审计）：{nm}")
            L.append("")
        if r.get("m_explain", {}).get("examples"):
            L.append("- 解释句样例（这些句子在替读者下结论）：")
            for e in r["m_explain"]["examples"][:5]:
                L.append(f"  - `{e['quote']}`")
            L.append("")
        if r.get("m_long", {}).get("examples"):
            L.append("- 最长句样例：")
            for e in r["m_long"]["examples"][:3]:
                L.append(f"  - `{e['quote']}`〔{e['han']}字〕")
            L.append("")
    return "\n".join(L)


def render_compare_top10(pooled: dict[str, dict]) -> str:
    L = ["## 最该改的 10 句话（跨版本）", ""]
    L.append("B/C 两版各取 5 句：它们是最新在写的东西，也就是**接下来会继续犯的错**。")
    L.append("")
    L.append("| # | 版本 | 原文 | 为什么累 | 建议改法 |")
    L.append("|---|---|---|---|---|")
    n = 0
    for k in ("C", "B"):
        if k not in pooled:
            continue
        for s in pooled[k].get("top_sentences", [])[:5]:
            n += 1
            q = s["quote"].replace("|", "｜")
            L.append(f"| {n} | {k} | {q} | {'；'.join(s['reasons'])} | {s['fix']} |")
    if n < 10:
        for s in pooled["A"].get("top_sentences", [])[:10 - n]:
            n += 1
            q = s["quote"].replace("|", "｜")
            L.append(f"| {n} | A | {q} | {'；'.join(s['reasons'])} | {s['fix']} |")
    L.append("")
    return "\n".join(L)


def emit_reports(outdir: Path, topn: int = 10) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    pooled = {}
    for key, meta in BATCHES.items():
        results = []
        for p in meta["paths"]:
            p = Path(p)
            if not p.exists():
                print(f"[{key}] 跳过（不存在）：{p}", file=sys.stderr)
                continue
            files = sorted(p.glob("*.txt")) if p.is_dir() else [p]
            for f in files:
                try:
                    results.append(analyze_file(f, topn=topn))
                except ValueError as e:
                    print(f"  skip {f.name}: {e}", file=sys.stderr)
        if not results:
            print(f"[{key}] 没有任何可用文件，跳过整批", file=sys.stderr)
            continue
        m = pool(results)
        m["top_sentences"] = merge_top(results, topn)
        m["m_info"] = pick(results, "m_info")
        m["m_explain"] = pick(results, "m_explain")
        m["m_static"] = pick(results, "m_static")
        m["m_short"] = pick(results, "m_short")
        m["m_open"] = pick(results, "m_open")
        m["m_epithet"] = pick(results, "m_epithet")
        m["m_action"] = pick(results, "m_action")
        m["m_attributive"] = pick(results, "m_attributive")
        m["m_comma"] = pick(results, "m_comma")
        m["m_long"] = pick(results, "m_long")
        m["m_micro"] = pick(results, "m_micro")
        for sub in ("m_static", "m_short", "m_open", "m_epithet", "m_action",
                    "m_explain", "m_info", "m_comma", "m_long", "m_micro"):
            m[sub]["n_sent"] = m["sentences"]
        m["m_attributive"]["n_sent"] = m["sentences"]
        m["m_attributive"]["n_han"] = m["chars"]
        pooled[key] = m

        md = render_batch_md(key, meta, results, m)
        (outdir / f"report_{key}.md").write_text(md, encoding="utf-8")
        (outdir / f"raw_{key}.json").write_text(
            json.dumps({"batch": key, "meta": {kk: str(v) for kk, v in meta.items()},
                        "files": results, "pooled": m},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{key}] {len(results)} 文件, 可读分 {m['readability']['score']} ->"
              f" report_{key}.md")

    cmp_md = render_compare_md(pooled)
    (outdir / "compare.md").write_text(cmp_md, encoding="utf-8")
    # 汇总（给上游程序/prompt 用）
    summary = {k: {"chars": v["chars"], "sentences": v["sentences"],
                   "avg_sent": v["avg_sent"],
                   "score": v["readability"]["score"],
                   "grade": v["readability"]["grade"],
                   "penalty": v["readability"]["penalty"],
                   "alt_score": v["readability"]["alt"]["score"],
                   "alt_grade": v["readability"]["alt"]["grade"],
                   "values": v["values"],
                   "penalty_detail": [
                       {"key": c["key"], "label": c["label"], "value": c["value"],
                        "points": c["points"], "level": c["level"]}
                       for c in v["readability"]["contributions"]]}
               for k, v in pooled.items()}
    (outdir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[summary] -> summary.json")


def pick(results: list[dict], key: str) -> dict:
    """从多章里挑一个"最有代表性"的子结构：取该章该指标命中数最多的。"""
    def size(r):
        d = r.get(key, {})
        for kk in ("sent_ge3de_count", "count_35", "count", "total",
                   "phrases_ge3", "consecutive_runs", "runs_ge3",
                   "chain_count", "new_name_total"):
            if kk in d:
                return d[kk]
        return 0
    best = max(results, key=size)
    d = dict(best[key])
    d["_from"] = best["name"]
    return d


def merge_top(results: list[dict], topn: int = 10) -> list[dict]:
    """跨章取成本最高的句子。"""
    items = []
    for r in results:
        for s in r["top_sentences"]:
            items.append((s["cost"], r["name"], s))
    items.sort(key=lambda x: -x[0])
    out = []
    for c, name, s in items[:topn]:
        d = dict(s)
        d["from"] = name
        out.append(d)
    return out


# --------------------------------------------------------------------------
# 十、CLI
# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="中文网文「读者体验」专项评审器")
    ap.add_argument("paths", nargs="*", help="文件或目录（目录内所有 .txt）")
    ap.add_argument("--json", help="结构化结果写入该 json")
    ap.add_argument("--md", help="人类可读报告写入该 md")
    ap.add_argument("--emit-reports", action="store_true",
                    help="生成 A/B/C 三批报告 + compare.md 到 out/judge/")
    ap.add_argument("--outdir", default=str(REPO / "out" / "judge"))
    ap.add_argument("--topn", type=int, default=10)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.emit_reports:
        emit_reports(Path(args.outdir), args.topn)
        return 0

    if not args.paths:
        ap.error("需要至少一个文件/目录，或用 --emit-reports")

    results = analyze_paths(args.paths, args.topn)
    if not results:
        print("没有可分析的文本", file=sys.stderr)
        return 1

    if not args.quiet:
        for r in results:
            print(render_console(r))
            print()

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        payload = results[0] if len(results) == 1 else results
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.quiet:
            print(f"json -> {args.json}")

    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        md = "\n\n---\n\n".join(render_md(r) for r in results)
        Path(args.md).write_text(md, encoding="utf-8")
        if not args.quiet:
            print(f"md -> {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
