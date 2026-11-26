#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dashboard.py —— 一键重建可视化大屏

    python src/build_dashboard.py

流程：导出数据 → 注入模板 → 输出 out/dashboard.html
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main() -> int:
    py = sys.executable
    # 1) 导出数据
    r = subprocess.run([py, str(HERE / "export_dashboard.py")],
                       cwd=str(ROOT))
    if r.returncode != 0:
        print("❌ 数据导出失败")
        return 1

    # 2) 注入模板
    tpl_p = ROOT / "out" / "dashboard_template.html"
    data_p = ROOT / "out" / "dashboard_data.json"
    out_p = ROOT / "out" / "dashboard.html"

    if not tpl_p.exists():
        print(f"❌ 找不到模板 {tpl_p}")
        return 1

    tpl = tpl_p.read_text(encoding="utf-8")
    data = data_p.read_text(encoding="utf-8")
    html = tpl.replace("__DATA__", data)
    if "__DATA__" in html:
        print("❌ 模板占位符未替换")
        return 1
    out_p.write_text(html, encoding="utf-8")

    print(f"\n✅ 已生成 {out_p}")
    print(f"   {len(html):,} 字符")
    print(f"\n   用浏览器打开：")
    print(f"   file:///{out_p.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
