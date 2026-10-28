"""启动 GUI 并强制显示「组件更新」横幅，用于截图与布局校验（开发工具）。

用法: python packaging/probe_update_banner.py
输出: packaging/update_banner_probe.png
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(r"E:\ai\opencode\内网web自动化开发\douyin-mp3")
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from douyin_mp3 import updater  # noqa: E402

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

        # 伪造一个「发现新版本」的自检结果
        statuses = [
            updater.ComponentStatus(
                key=updater.YTDLP,
                label=updater.COMPONENT_LABELS[updater.YTDLP],
                current="2026.08.19",
                latest="2026.10.26",
                has_update=True,
                source="pypi.org",
            )
        ]
        win._pending_updates = statuses
        win._on_check_done(statuses)
        win.resize(980, 900)
        self.processEvents()
        pix = win.grab()
        out = root / "docs" / "images" / "08-组件更新横幅.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out))
        print(f"captured {pix.width()}x{pix.height()} -> {out}")
        print("横幅文案:", win.update_label.text())

        # 再抓一张加高窗口的，确认「组件更新」设置行渲染正常（仅本地校验用）
        win.resize(900, 1180)
        self.processEvents()
        pix2 = win.grab()
        out2 = root / "packaging" / "update_settings_probe.png"
        pix2.save(str(out2))
        print(f"captured {pix2.width()}x{pix2.height()} -> {out2}")
        self.quit()

    QTimer.singleShot(800, later)
    return _orig_exec()


QApplication.exec = patched_exec

from douyin_mp3.gui import run_gui  # noqa: E402

run_gui()
