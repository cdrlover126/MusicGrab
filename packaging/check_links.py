"""校验 Markdown 文档的内部锚点与相对路径链接（开发工具）。

用法: python packaging/check_links.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 需要检查的 Markdown 文件
DOCS = [
    ROOT / "README.md",
    ROOT / "docs" / "blog" / "CSDN-技术博文.md",
    ROOT / "docs" / "blog" / "CSDN-发布信息.md",
    ROOT / "docs" / "releases" / "v1.7.0.md",
    ROOT / "docs" / "releases" / "v1.8.0.md",
    ROOT / "docs" / "SUPPORTED_SITES.md",
    ROOT / "docs" / "PRIVACY_POLICY.md",
    ROOT / "docs" / "STORE_CHECKLIST.md",
]


def slug(text: str) -> str:
    """GitHub 风格的锚点 slug。"""
    out = text.strip().lower()
    out = re.sub(r"[^\w一-鿿\- ]", "", out)
    return out.replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    """收集文档内所有标题生成的锚点。"""
    found: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            found.add(slug(m.group(2)))
    return found


problems = 0
for doc in DOCS:
    if not doc.exists():
        print(f"[跳过] {doc.relative_to(ROOT)} 不存在")
        continue
    text = doc.read_text(encoding="utf-8")
    anchors = anchors_of(text)
    print(f"\n=== {doc.relative_to(ROOT)} ===")

    # 1) 相对路径链接
    for m in re.finditer(r"\]\(([^)#][^)]*)\)", text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        resolved = (doc.parent / path_part).resolve()
        if not resolved.exists():
            print(f"  [缺失文件] {target}")
            problems += 1

    # 2) 内部锚点
    for m in re.finditer(r"\]\(#([^)]+)\)", text):
        anchor = m.group(1).strip()
        if anchor not in anchors:
            print(f"  [缺失锚点] #{anchor}")
            problems += 1

    # 3) 指向本文档标题的链接（跨文件 #锚点）
    for m in re.finditer(r"\]\((?!http)([^)]*)#([^)]+)\)", text):
        target, anchor = m.group(1), m.group(2)
        if not target:
            continue
        other = (doc.parent / target).resolve()
        if other.exists() and other.suffix == ".md":
            other_anchors = anchors_of(other.read_text(encoding="utf-8"))
            if anchor not in other_anchors:
                print(f"  [缺失锚点] {target}#{anchor}")
                problems += 1

print()
print("=" * 60)
print("结论:", "全部通过" if problems == 0 else f"发现 {problems} 处问题")
