import pathlib

p = pathlib.Path(r'D:\qwq\DSHPLU\novel-lab\src\write.py')
s = p.read_text(encoding='utf-8')

# 1) token 预算：推理会吃掉大量 token，必须给足
old1 = 'txt = self.llm.chat(prompt, max_tokens=target * 2).strip()'
new1 = 'txt = self.llm.chat(prompt, max_tokens=max(4500, target * 3)).strip()'
assert old1 in s
s = s.replace(old1, new1)

# 2) 英文清理函数
anchor = 'def check_segment(text: str, min_chars: int = 900,'
new_fn = '''def clean_english(text: str) -> str:
    """
    清理免费模型混入的英文。

    实测 workbuddy/hy4flash-free 会在中文里插入英文词，
    如「陆家小子，你爹欠咱 three hundred 两银子」。
    这些必须清掉，否则读者一眼看出是机器写的。
    """
    NUM_MAP = {
        "one": "一", "two": "两", "three": "三", "four": "四",
        "five": "五", "six": "六", "seven": "七", "eight": "八",
        "nine": "九", "ten": "十", "hundred": "百", "thousand": "千",
        "twenty": "二十", "thirty": "三十", "fifty": "五十",
    }
    for en, zh in NUM_MAP.items():
        text = re.sub(r"\\b" + en + r"\\b", zh, text, flags=re.I)
    text = re.sub(r"\\s*\\b[A-Za-z]{3,}\\b\\s*", "", text)
    text = re.sub(r"\\s*\\b[A-Za-z]{1,2}\\b\\s*(?=[\\u4e00-\\u9fff])", "", text)
    text = re.sub(r"[\\uff0c]{2,}", "\\uff0c", text)
    text = re.sub(r"[\\u3002]{2,}", "\\u3002", text)
    text = re.sub(r"[\\uff08\\uff09\\u3010\\u3011]", "", text)
    return text


def check_segment(text: str, min_chars: int = 900,'''
assert anchor in s
s = s.replace(anchor, new_fn, 1)

# 3) 应用清理
old3 = '''                try:
                    txt = self.llm.chat(prompt, max_tokens=max(4500, target * 3)).strip()'''
new3 = '''                try:
                    txt = self.llm.chat(prompt, max_tokens=max(4500, target * 3)).strip()
                    txt = clean_english(txt)'''
assert old3 in s
s = s.replace(old3, new3)

# 4) 默认并发 10
s = s.replace('ap.add_argument("--workers", type=int, default=6)',
              'ap.add_argument("--workers", type=int, default=10)')

p.write_text(s, encoding='utf-8')
import ast
ast.parse(s)
print('patched write.py')
