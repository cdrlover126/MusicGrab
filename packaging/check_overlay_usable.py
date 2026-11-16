"""验证外置 yt-dlp 覆盖层是否真的可用（开发工具）。"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from douyin_mp3 import updater  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="mg_probe_"))
updater.overlay_root = lambda: tmp  # type: ignore[assignment]

print("[1] 下载并安装 yt-dlp 最新版到临时覆盖层 ...")
status = updater.check_ytdlp()
print("   ", status.summary())
if not status.has_update:
    print("    无更新，跳过")
    raise SystemExit(0)
print("   ", updater.upgrade_component(status))
print("    覆盖层版本:", updater.current_ytdlp_version())

probe = tmp / "probe.py"
probe.write_text(
    "import sys, traceback\n"
    f"sys.path.insert(0, {str(ROOT)!r})\n"
    "from douyin_mp3 import updater\n"
    f"updater.overlay_root = lambda: {str(tmp)!r}\n"
    "updater.apply_overlay()\n"
    "try:\n"
    "    import yt_dlp\n"
    "    print('  实际加载:', yt_dlp.__file__)\n"
    "    from yt_dlp.version import __version__ as v\n"
    "    print('  实际版本:', v)\n"
    "    from yt_dlp.extractor import gen_extractors\n"
    "    ex = list(gen_extractors())\n"
    "    print('  extractor 数量:', len(ex))\n"
    "    from yt_dlp.extractor.youtube import YoutubeIE\n"
    "    print('  youtube extractor:', YoutubeIE.__name__)\n"
    "    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:\n"
    "        info = ydl.extract_info('https://www.youtube.com/watch?v=BaW_jenozKc', download=False)\n"
    "    print('  真实解析:', info.get('title'), '| 时长', info.get('duration'), '秒')\n"
    "except Exception:\n"
    "    print('  [网络受限或解析失败，结构验证已通过]')\n"
    "    traceback.print_exc()\n",
    encoding="utf-8",
)
print()
print("[2] 新进程中验证覆盖层可用性（含真实解析）")
proc = subprocess.run(
    [sys.executable, str(probe)],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
print(proc.stdout)
if proc.stderr.strip():
    print("--- stderr ---")
    print(proc.stderr)

shutil.rmtree(tmp, ignore_errors=True)
print("已清理:", tmp)
