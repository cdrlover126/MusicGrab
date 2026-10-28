"""生成「详情日志」页截图（开发工具）。

用法: python packaging/capture_log_shots.py
输出: docs/images/03-详情日志-实时过程.png
      docs/images/04-详情日志-完成汇总.png
"""

from __future__ import annotations

import sys
from pathlib import Path

root = Path(r"E:\ai\opencode\内网web自动化开发\douyin-mp3")
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_orig_exec = QApplication.exec

FILES = [
    r"C:\Users\cdrlover\Music\示例视频A.mp4",
    r"C:\Users\cdrlover\Music\示例视频B.mp4",
    r"C:\Users\cdrlover\Music\示例视频C.mp4",
    r"C:\Users\cdrlover\Music\示例视频D.mp4",
    r"C:\Users\cdrlover\Music\示例视频E.mp4",
]

HEADER = """路由模式：智能（按站点自动选择：国内直连 / 境外走代理）
规则：国内平台直连，境外站点优先用指定代理，无代理时尝试系统代理/直连
代理：未填写（国内平台直连，境外站点将提示需要代理）
共 0 条链接 + 5 个本地文件，输出目录：C:\\Users\\cdrlover\\Music\\MusicGrab，质量：320k，格式：MP3（通用，车机首选）"""

DONE_LINES = """[1/5] 本地文件《示例视频A》(.mp4)
[1/5] 完成 -> 001_示例视频A.mp3（22.9 MB）
[2/5] 本地文件《示例视频B》(.mp4)
[2/5] 完成 -> 002_示例视频B.mp3（22.9 MB）
[3/5] 本地文件《示例视频C》(.mp4)
[3/5] 完成 -> 003_示例视频C.mp3（22.9 MB）
[4/5] 本地文件《示例视频D》(.mp4)
[4/5] 完成 -> 004_示例视频D.mp3（22.9 MB）
[5/5] 本地文件《示例视频E》(.mp4)
[5/5] 完成 -> 005_示例视频E.mp3（22.9 MB）
报告已保存：C:\\Users\\cdrlover\\Music\\MusicGrab\\转换报告.csv
完成：成功 5，失败 0"""


def patched_exec(self):
    def later():
        win = None
        for w in self.topLevelWidgets():
            if hasattr(w, "log_edit") and hasattr(w, "results_table"):
                win = w
                break
        if win is None:
            print("window not found")
            self.quit()
            return

        win.resize(980, 900)
        win.links_edit.setPlainText("\n".join(FILES))
        win.tabs.setCurrentIndex(1)
        self.processEvents()

        # 实时过程
        win.log_edit.setPlainText(HEADER + "\n" + DONE_LINES.splitlines()[0] + "\n" + DONE_LINES.splitlines()[1])
        win.hint_label.setText("正在转换 5 条…")
        win.start_btn.setEnabled(False)
        win.stop_btn.setEnabled(True)
        win.progress.setRange(0, 5)
        win.progress.setValue(1)
        win.progress.setFormat("第 1 条 · %p%")
        self.processEvents()
        out1 = root / "docs" / "images" / "03-详情日志-实时过程.png"
        win.grab().save(str(out1))
        print("captured ->", out1)

        # 完成汇总
        win.log_edit.setPlainText(HEADER + "\n" + DONE_LINES)
        win.hint_label.setText("完成：成功 5 / 失败 0")
        win.start_btn.setEnabled(True)
        win.stop_btn.setEnabled(False)
        win.progress.setRange(0, 5)
        win.progress.setValue(5)
        win.progress.setFormat("完成：成功 5 / 失败 0 · %p%")
        self.processEvents()
        out2 = root / "docs" / "images" / "04-详情日志-完成汇总.png"
        win.grab().save(str(out2))
        print("captured ->", out2)

        self.quit()

    QTimer.singleShot(500, later)
    return _orig_exec()


QApplication.exec = patched_exec
from douyin_mp3.gui import run_gui  # noqa: E402

raise SystemExit(run_gui())
