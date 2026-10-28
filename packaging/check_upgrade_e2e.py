"""端到端验证：真实网络自检 + 真实下载安装 + 覆盖层生效。

开发工具（需要联网），不属于单元测试。
用法: python packaging/check_upgrade_e2e.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"E:\ai\opencode\内网web自动化开发\douyin-mp3")
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from douyin_mp3 import updater  # noqa: E402

print("=" * 68)
print("[1] 真实网络自检")
print("=" * 68)
statuses = updater.check_components()
for s in statuses:
    flag = "有更新" if s.has_update else "已是最新"
    print(f"  {s.label}: {s.current or '未知'} -> {s.latest}  [{flag}]  来源={s.source}")
    if s.error:
        print(f"     错误: {s.error}")

yt = next((s for s in statuses if s.key == updater.YTDLP), None)
if yt is None or not yt.has_update:
    print("\nyt-dlp 无更新可用，跳过下载验证。")
    raise SystemExit(0)

print()
print("=" * 68)
print("[2] 真实下载并安装到临时覆盖层")
print("=" * 68)
tmp = Path(tempfile.mkdtemp(prefix="mg_overlay_"))
updater.overlay_root = lambda: tmp  # type: ignore[assignment]

last = [0, 0]


def progress(done: int, total: int) -> None:
    if total and (done * 20 // max(total, 1)) > last[0]:
        last[0] = done * 20 // max(total, 1)
        print(f"  下载中 {done * 100 // max(total, 1)}%")


result = updater.upgrade_component(yt, on_progress=progress)
print("  安装结果:", result)
print("  覆盖层目录:", updater.ytdlp_overlay_dir())
print("  覆盖层版本:", updater.current_ytdlp_version())

print()
print("=" * 68)
print("[3] 新进程验证覆盖层是否真的优先生效")
print("=" * 68)
probe = tmp / "probe.py"
probe.write_text(
    "import sys\n"
    f"sys.path.insert(0, {str(ROOT)!r})\n"
    "from douyin_mp3 import updater\n"
    f"updater.overlay_root = lambda: {str(tmp)!r}\n"
    "updater.apply_overlay()\n"
    "import yt_dlp\n"
    "print('  实际加载:', yt_dlp.__file__)\n"
    "print('  实际版本:', yt_dlp.__version__)\n"
    "from yt_dlp.version import __version__\n"
    "print('  version.py:', __version__)\n",
    encoding="utf-8",
)
proc = subprocess.run(
    [sys.executable, str(probe)], capture_output=True, text=True, encoding="utf-8", errors="replace"
)
print(proc.stdout or proc.stderr)

print("=" * 68)
print("[4] 清理")
print("=" * 68)
import shutil  # noqa: E402

shutil.rmtree(tmp, ignore_errors=True)
print("  已删除临时覆盖层:", tmp, "->", not tmp.exists())
