"""验证「自检进行中关闭程序」不会崩溃（回归测试，开发工具）。

场景：启动 GUI → 触发后台自检（正在联网）→ 立刻退出程序。
若用 QThread 且未等待，会触发 "QThread: Destroyed while thread is still running"
并让进程异常终止。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "packaging" / "_quit_while_checking.py"


def _locked(path: Path) -> bool:
    """文件是否仍被其他进程占用。"""
    try:
        path.unlink()
        return False
    except PermissionError:
        return True
    except OSError:
        return True

PROBE.write_text(
    "import sys\n"
    f"sys.path.insert(0, {str(ROOT)!r})\n"
    "from PySide6.QtCore import QTimer\n"
    "from PySide6.QtWidgets import QApplication\n"
    "_orig = QApplication.exec\n"
    "def patched(self):\n"
    "    # 100ms 后退出：此时 900ms 的自检定时器还没触发\n"
    "    QTimer.singleShot(100, self.quit)\n"
    "    return _orig()\n"
    "QApplication.exec = patched\n"
    "from douyin_mp3.gui import run_gui\n"
    "sys.exit(run_gui())\n",
    encoding="utf-8",
)

print("[1] 启动后 100ms 立即退出（自检尚未开始）")
proc = subprocess.run(
    [sys.executable, str(PROBE)], capture_output=True, text=True, encoding="utf-8", errors="replace"
)
print("    退出码:", proc.returncode)
if "Destroyed while thread" in (proc.stderr or ""):
    print("    !! 检测到 QThread 销毁告警")
else:
    print("    无线程销毁告警")

print()
print("[2] 启动后 1.6s 退出（自检正在联网）")
PROBE.write_text(
    "import sys\n"
    f"sys.path.insert(0, {str(ROOT)!r})\n"
    "from PySide6.QtCore import QTimer\n"
    "from PySide6.QtWidgets import QApplication\n"
    "_orig = QApplication.exec\n"
    "def patched(self):\n"
    "    QTimer.singleShot(1600, self.quit)\n"
    "    return _orig()\n"
    "QApplication.exec = patched\n"
    "from douyin_mp3.gui import run_gui\n"
    "sys.exit(run_gui())\n",
    encoding="utf-8",
)
proc = subprocess.run(
    [sys.executable, str(PROBE)], capture_output=True, text=True, encoding="utf-8", errors="replace"
)
print("    退出码:", proc.returncode)
err = proc.stderr or ""
if "Destroyed while thread" in err:
    print("    !! 检测到 QThread 销毁告警")
elif "QThread" in err:
    print("    stderr 含 QThread 相关输出:", err.strip()[:200])
else:
    print("    无线程销毁告警，进程干净退出")

print()
print("[3] 转换进行中退出（Worker 正在跑）")
WORK = ROOT / "packaging" / "_race_sample.mp4"
if not WORK.exists():
    import subprocess

    from douyin_mp3.converter import find_ffmpeg

    subprocess.run(
        [find_ffmpeg(), "-y", "-hide_banner",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=600",
         "-f", "lavfi", "-i", "color=c=0x2563eb:s=320x180:d=600",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(WORK)],
        capture_output=True,
    )
PROBE.write_text(
    "import sys\n"
    f"sys.path.insert(0, {str(ROOT)!r})\n"
    "from PySide6.QtCore import QTimer\n"
    "from PySide6.QtWidgets import QApplication\n"
    "_orig = QApplication.exec\n"
    "def patched(self):\n"
    "    def go():\n"
    "        for w in self.topLevelWidgets():\n"
    "            if hasattr(w, 'tabs'):\n"
    f"                w.links_edit.setPlainText(r'{WORK}')\n"
    "                w.start()\n"
    "                break\n"
    "    QTimer.singleShot(300, go)\n"
    "    # 转换开始 1.5s 后直接退出（不等转换结束）\n"
    "    QTimer.singleShot(1800, self.quit)\n"
    "    return _orig()\n"
    "QApplication.exec = patched\n"
    "from douyin_mp3.gui import run_gui\n"
    "sys.exit(run_gui())\n",
    encoding="utf-8",
)
proc = subprocess.run(
    [sys.executable, str(PROBE)], capture_output=True, text=True, encoding="utf-8", errors="replace"
)
print("    退出码:", proc.returncode)
err = proc.stderr or ""
if "Destroyed while thread" in err:
    print("    !! 检测到 QThread 销毁告警")
elif "Traceback" in err:
    print("    !! stderr 有异常:\n", err.strip()[:600])
else:
    print("    转换中退出：无线程销毁告警、无异常")
WORK.unlink(missing_ok=True) if not _locked(WORK) else print(
    "    （示例文件仍被转码进程占用，稍后手动清理）"
)

PROBE.unlink(missing_ok=True)
print()
print("结论:", "通过" if proc.returncode == 0 else "失败（退出码非 0）")
