"""启动 GUI 并填充「任务结果」页，用于截图与布局校验（开发工具）。

用法: python packaging/probe_results_tab.py
输出: docs/images/09-任务结果-单条重试.png
"""

from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from musicgrab.batch import TaskResult  # noqa: E402

_orig_exec = QApplication.exec


def patched_exec(self):
    def later():
        win = None
        for w in self.topLevelWidgets():
            if hasattr(w, "results_table"):
                win = w
                break
        if win is None:
            print("window not found")
            self.quit()
            return

        out_dir = Path.home() / "Music" / "MusicGrab"
        rows = [
            TaskResult(
                1,
                "https://v.douyin.com/aaaaaa/",
                "ok",
                "成功",
                str(out_dir / "001_起风了.mp3"),
                "起风了",
                "买辣椒也用券",
                312,
                12_682_112,
            ),
            TaskResult(
                2,
                "https://www.bilibili.com/video/BV1xx411c7mD",
                "ok",
                "成功",
                str(out_dir / "002_夜航星.m4a"),
                "夜航星",
                "不才",
                245,
                8_913_408,
            ),
            TaskResult(
                3,
                "https://www.kugou.com/mixsong/xxxx.html",
                "failed",
                "该酷狗歌曲为VIP/付费歌曲，未登录无法获取播放地址",
            ),
            TaskResult(
                4,
                "https://v.kuaishou.com/bbbbbb",
                "ok",
                "成功",
                str(out_dir / "004_海阔天空.flac"),
                "海阔天空",
                "Beyond",
                326,
                34_271_232,
            ),
        ]
        win._reset_results()
        for row in rows:
            win._upsert_result(row)
        win.tabs.setCurrentWidget(win.results_page)
        win.resize(980, 720)
        self.processEvents()

        pix = win.grab()
        out = root / "docs" / "images" / "09-任务结果-单条重试.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out))
        print(f"captured {pix.width()}x{pix.height()} -> {out}")
        print("汇总:", win.results_summary.text())
        self.quit()

    QTimer.singleShot(500, later)
    return _orig_exec()


QApplication.exec = patched_exec
from musicgrab.gui import run_gui  # noqa: E402

raise SystemExit(run_gui())
