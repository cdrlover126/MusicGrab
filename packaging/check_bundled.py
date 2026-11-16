"""检查打包后的 exe 里内嵌的组件版本（开发工具）。"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

exe = root / "dist" / "MusicGrab.exe"
print("exe:", exe.name, f"{exe.stat().st_size / 1024 / 1024:.1f} MB")

from PyInstaller.archive.readers import CArchiveReader

reader = CArchiveReader(str(exe))
names = list(reader.toc)

for pkg in ("yt_dlp", "musicgrab", "imageio_ffmpeg"):
    hits = [n for n in names if n.startswith(pkg.replace(".", "\\"))]
    print(f"{pkg:16} 内嵌条目 {len(hits):5}")

for rel in ("yt_dlp\\version.py", "musicgrab\\updater.py", "musicgrab\\__init__.py"):
    print(f"  {rel:32} {'存在' if rel in names else '缺失!!'}")

raw = reader.extract("yt_dlp\\version.py")
text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
for line in text.splitlines():
    if "__version__" in line:
        print("  内嵌 yt-dlp 版本:", line.strip())

# 版本资源（version_info.txt）
raw2 = reader.toc.get("version_info.txt")
print("  version_info 条目:", "存在" if raw2 else "缺失")
