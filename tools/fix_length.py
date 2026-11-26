import pathlib

p = pathlib.Path(r'D:\qwq\DSHPLU\novel-lab\src\write.py')
s = p.read_text(encoding='utf-8')

# 1) 新增 trim_to_length，并把 max_chars 放宽
old = '''def check_segment(text: str, min_chars: int = 900,
                  max_chars: int = 2200) -> list[str]:'''
new = '''def trim_to_length(text: str, max_chars: int) -> str:
    """
    超长文本截断到自然段边界。

    为什么不在超长时重试：模型经常一次写 4000+ 字（它以为在写整章）。
    如果判失败重试，会陷入死循环——实测 7 分钟只推进 1 章。
    截断是正确做法：多出来的部分本来就不属于这一段。
    """
    if n_han(text) <= max_chars:
        return text
    paras = text.split("\\n")
    out, total = [], 0
    for para in paras:
        k = n_han(para)
        if total + k > max_chars and out:
            break
        out.append(para)
        total += k
    return "\\n".join(out) if out else text[:max_chars * 2]


def check_segment(text: str, min_chars: int = 900,
                  max_chars: int = 3200) -> list[str]:'''
assert old in s
s = s.replace(old, new)

# 2) 去掉超长判失败
bad = '''    if n > max_chars:
        problems.append(f"字数 {n} > {max_chars}")
'''
assert bad in s
s = s.replace(bad, '')

# 3) 生成后先 trim 再检查
old3 = '                    txt = clean_english(txt)'
new3 = '''                    txt = clean_english(txt)
                    txt = trim_to_length(txt, int(target * 1.6))'''
assert old3 in s
s = s.replace(old3, new3)

p.write_text(s, encoding='utf-8')
import ast
ast.parse(s)
print('patched')
