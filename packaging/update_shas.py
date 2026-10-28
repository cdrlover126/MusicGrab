"""回填发布产物 SHA256 到三份文档（开发工具）。

用法: python packaging/update_shas.py <旧exeSHA> <新exeSHA> <旧zipSHA> <新zipSHA>
"""

from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DOCS = [
    "docs/releases/v1.8.0.md",
    "docs/blog/CSDN-技术博文.md",
    "docs/blog/CSDN-发布信息.md",
]

old_exe, new_exe, old_zip, new_zip = sys.argv[1:5]

for name in DOCS:
    path = pathlib.Path(name)
    text = path.read_text(encoding="utf-8")
    counts = (text.count(old_zip), text.count(old_exe))
    text = text.replace(old_zip, new_zip).replace(old_exe, new_exe)
    path.write_text(text, encoding="utf-8", newline="")
    print(f"{name}: 替换 zip {counts[0]} 处、exe {counts[1]} 处")
