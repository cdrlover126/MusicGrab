"""GUI 拖放冒烟测试（开发工具）。

覆盖三种真实来源：
    1. Chrome / Edge 拖标签页：原始 ``text/uri-list`` + ``text/plain``
    2. Firefox 拖标签页：``text/x-moz-url``
    3. 资源管理器拖文件 / 文件夹：``QMimeData.urls()`` 里的 ``file:///``

并验证「拖到窗口里的子控件（日志框）上」也能被接住（应用层拦截器）。
"""

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


def chrome_tab_mime(url: str, title: str = "示例页面") -> QMimeData:
    """模拟 Chrome 拖标签页：只有原始 text/uri-list 与 text/plain。"""
    mime = QMimeData()
    mime.setData("text/uri-list", f"{url}\r\n".encode())
    mime.setText(f"{title}\n{url}")
    return mime


def fire(target, mime, pos=QPoint(10, 10)):
    enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(target, enter)
    drop = QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(target, drop)
    return enter.isAccepted(), drop.isAccepted()


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

        print("== 1. Chrome 拖标签页（原始 text/uri-list）==")
        mime = chrome_tab_mime("https://www.bilibili.com/video/BV1xx411c7mD")
        accepted = fire(win.links_edit.viewport(), mime)
        print("事件被接受:", accepted)
        print(win.links_edit.toPlainText())
        print("提示:", win.hint_label.text())

        print("== 2. Firefox 拖标签页（text/x-moz-url）==")
        win.links_edit.clear()
        mime = QMimeData()
        mime.setData("text/x-moz-url", b"https://v.douyin.com/abc123/\n\xe6\x8a\x96\xe9\x9f\xb3")
        accepted = fire(win.links_edit.viewport(), mime)
        print("事件被接受:", accepted)
        print(win.links_edit.toPlainText())

        print("== 3. 资源管理器拖文件夹（file:/// URL）==")
        win.links_edit.clear()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(base))])
        accepted = fire(win.links_edit.viewport(), mime)
        print("事件被接受:", accepted)
        print(win.links_edit.toPlainText())
        print("提示:", win.hint_label.text())

        print("== 4. 拖到窗口里的日志框上（应用层拦截器）==")
        win.links_edit.clear()
        mime = chrome_tab_mime("https://v.kuaishou.com/bbbbbb")
        accepted = fire(win.log_edit.viewport(), mime)
        print("事件被接受:", accepted)
        print("输入框内容:", win.links_edit.toPlainText())

        print("== 5. 重复拖入同一批内容（去重）==")
        mime = chrome_tab_mime("https://v.kuaishou.com/bbbbbb")
        fire(win.links_edit.viewport(), mime)
        print("行数:", len(win.links_edit.toPlainText().splitlines()))
        print("提示:", win.hint_label.text())

        print("== 6. 拖入不支持的文件 ==")
        bad = QMimeData()
        bad.setUrls([QUrl.fromLocalFile(str(base / "说明.txt"))])
        fire(win.links_edit.viewport(), bad)
        print("提示:", win.hint_label.text())

        print("== 7. 转换报告下拉 ==")
        print("选项:", [win.report_box.itemText(i) for i in range(win.report_box.count())])
        print("默认:", win.report_box.currentData())

        self.quit()

    QTimer.singleShot(500, later)
    return _orig_exec()


QApplication.exec = patched_exec
from douyin_mp3.gui import run_gui  # noqa: E402

raise SystemExit(run_gui())
