"""GUI 拖放冒烟测试（开发工具）：文件夹递归展开 + 浏览器链接 + 去重。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

root = Path(r"E:\ai\opencode\内网web自动化开发\douyin-mp3")
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QMimeData, QPoint, QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_orig_exec = QApplication.exec

base = Path(tempfile.mkdtemp(prefix="musicgrab_drop_"))
(base / "子目录").mkdir()
(base / "a.mp4").write_bytes(b"x")
(base / "子目录" / "b.flac").write_bytes(b"x")
(base / "说明.txt").write_text("ignore", encoding="utf-8")


def patched_exec(self):
    def later():
        win = None
        for w in self.topLevelWidgets():
            if hasattr(w, "links_edit"):
                win = w
                break
        if win is None:
            print("window not found")
            self.quit()
            return

        mime = QMimeData()
        mime.setUrls(
            [
                QUrl.fromLocalFile(str(base)),
                QUrl("https://v.douyin.com/aaaaaa/"),
                QUrl("https://www.bilibili.com/video/BV1xx411c7mD"),
            ]
        )
        mime.setText("【标题】 https://www.bilibili.com/video/BV1xx411c7mD")

        # 走真实事件链：viewer -> QPlainTextEdit.viewportEvent -> dropEvent
        viewport = win.links_edit.viewport()
        pos = viewport.rect().center()
        enter = QDragEnterEvent(
            pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        QApplication.sendEvent(viewport, enter)
        print("dragEnter accepted:", enter.isAccepted())
        drop = QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(viewport, drop)
        print("drop accepted:", drop.isAccepted())

        text1 = win.links_edit.toPlainText()
        print("第一次拖入:")
        print(text1)
        print("提示:", win.hint_label.text())

        # 再拖一次同样的内容，验证去重
        win.handle_drop(mime)
        print("第二次拖入后行数:", len(win.links_edit.toPlainText().splitlines()))
        print("提示:", win.hint_label.text())

        # 拖入不支持的文件
        bad = QMimeData()
        bad.setUrls([QUrl.fromLocalFile(str(base / "说明.txt"))])
        win.handle_drop(bad)
        print("拖入不支持文件后提示:", win.hint_label.text())

        # 窗口级拖放（例如拖到日志/表格区域）
        win2_mime = QMimeData()
        win2_mime.setUrls([QUrl("https://v.kuaishou.com/bbbbbb")])
        win_enter = QDragEnterEvent(
            QPoint(10, 10), Qt.CopyAction, win2_mime, Qt.LeftButton, Qt.NoModifier
        )
        QApplication.sendEvent(win, win_enter)
        print("窗口 dragEnter accepted:", win_enter.isAccepted())
        win_drop = QDropEvent(
            QPoint(10, 10), Qt.CopyAction, win2_mime, Qt.LeftButton, Qt.NoModifier
        )
        QApplication.sendEvent(win, win_drop)
        print("窗口 drop 后末行:", win.links_edit.toPlainText().splitlines()[-1])

        self.quit()

    QTimer.singleShot(500, later)
    return _orig_exec()


QApplication.exec = patched_exec
from douyin_mp3.gui import run_gui  # noqa: E402

raise SystemExit(run_gui())
