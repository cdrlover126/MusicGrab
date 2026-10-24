"""启动 GUI 截图，用于排查布局问题（开发工具）。

用法: python packaging/probe_layout.py [tab_index]
"""
import sys
from pathlib import Path

root = Path(r"E:\ai\opencode\内网web自动化开发\douyin-mp3")
sys.path.insert(0, str(root))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

tab_index = int(sys.argv[1]) if len(sys.argv) > 1 else 0

_orig_exec = QApplication.exec


def patched_exec(self):
    def later():
        win = None
        for w in self.topLevelWidgets():
            if hasattr(w, "tabs"):
                win = w
                break
        if win is None:
            print("window not found")
            self.quit()
            return
        win.tabs.setCurrentIndex(tab_index)
        self.processEvents()
        pix = win.grab()
        out = root / "packaging" / "layout_probe.png"
        pix.save(str(out))
        print("captured(qt)", pix.width(), "x", pix.height(), "tab=", tab_index, "->", out)
        self.quit()

    QTimer.singleShot(700, later)
    return _orig_exec()


QApplication.exec = patched_exec

from douyin_mp3.gui import run_gui  # noqa: E402

run_gui()
