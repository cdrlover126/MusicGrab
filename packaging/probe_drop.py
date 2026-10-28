"""GUI 拖放冒烟测试（开发工具）。

按 Qt 的真实规则模拟：``findDnDTarget()`` 会把拖放交给
「从光标处向上第一个 acceptDrops 的控件」，因此覆盖：

1. Chrome / Edge 拖标签页：原始 ``text/uri-list`` + ``text/plain``（当前会被忽略）
2. Chromium 自定义格式：``text/uri-list;charset=utf-8``（当前会被忽略）
3. Firefox 拖标签页：``text/x-moz-url``（当前会被忽略）
4. 资源管理器拖文件 / 文件夹：应当正常导入
5. 拖到日志框、输出目录等子控件上：验证不会被它们截胡
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
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

_orig_exec = QApplication.exec

base = Path(tempfile.mkdtemp(prefix="musicgrab_drop_"))
(base / "子目录").mkdir()
(base / "a.mp4").write_bytes(b"x")
(base / "子目录" / "b.flac").write_bytes(b"x")
(base / "说明.txt").write_text("ignore", encoding="utf-8")


def chrome_tab_mime(url: str, title: str = "示例页面") -> QMimeData:
    """模拟 Chrome 拖标签页：原始 text/uri-list + text/plain。"""
    mime = QMimeData()
    mime.setData("text/uri-list", f"{url}\r\n".encode())
    mime.setText(f"{title}\n{url}")
    return mime


def chromium_custom_mime(url: str, title: str = "小红书 - 你访问的页面不见了？") -> QMimeData:
    """模拟 Chromium 自定义格式：网址只在 text/uri-list;charset=utf-8 里。"""
    mime = QMimeData()
    mime.setData("text/plain", title.encode("utf-8"))
    mime.setData("text/uri-list;charset=utf-8", f"{url}\r\n".encode())
    return mime


def moz_mime(url: str, title: str = "YouTube") -> QMimeData:
    mime = QMimeData()
    mime.setData("text/x-moz-url", f"{url}\n{title}\n".encode())
    return mime


def file_mime(*paths: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def find_drop_target(widget: QWidget, pos: QPoint) -> QWidget:
    """复刻 Qt 的 findDnDTarget()：向上找第一个 acceptDrops 的控件。"""
    child = widget.childAt(pos)
    if child is None:
        child = widget
    while child is not None and not child.isWindow() and not child.acceptDrops():
        child = child.parentWidget()
    if child is not None and not child.acceptDrops():
        child = None
    return child


def fire(window: QWidget, child: QWidget, mime: QMimeData, pos: QPoint):
    """模拟真实拖放：事件发给 findDnDTarget() 选中的那个控件。"""
    target = find_drop_target(window, pos)
    if target is None:
        return None, None
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

        hijackers = [
            type(w).__name__
            for w in win.findChildren(QWidget)
            if w is not win.links_edit and w.acceptDrops()
        ]
        print("仍会截胡拖放的子控件:", hijackers or "无")
        print("主窗口 acceptDrops:", win.acceptDrops())
        print("输入框 acceptDrops:", win.links_edit.acceptDrops())

        print("\n== 1. Chrome 拖标签页（链接拖放暂时关闭）==")
        win.links_edit.clear()
        ok = fire(win, win.links_edit.viewport(), chrome_tab_mime("https://www.bilibili.com/video/BV1xx411c7mD"), QPoint(10, 10))
        print("接受:", ok, "| 输入框:", repr(win.links_edit.toPlainText()))
        print("提示:", win.hint_label.text())

        print("\n== 2. Chromium 自定义格式 ==")
        win.links_edit.clear()
        ok = fire(win, win.links_edit.viewport(), chromium_custom_mime("https://www.xiaohongshu.com/explore/123456"), QPoint(10, 10))
        print("接受:", ok, "| 输入框:", repr(win.links_edit.toPlainText()))
        print("提示:", win.hint_label.text())

        print("\n== 3. Firefox 拖标签页 ==")
        win.links_edit.clear()
        ok = fire(win, win.links_edit.viewport(), moz_mime("https://v.douyin.com/abc123/"), QPoint(10, 10))
        print("接受:", ok, "| 输入框:", repr(win.links_edit.toPlainText()))
        print("提示:", win.hint_label.text())

        print("\n== 4. 资源管理器拖文件夹（应当正常导入）==")
        win.links_edit.clear()
        ok = fire(win, win.links_edit.viewport(), file_mime(base), QPoint(10, 10))
        print("接受:", ok)
        print(win.links_edit.toPlainText())
        print("提示:", win.hint_label.text())

        print("\n== 5. 拖到「详情日志」区域（以前会被日志框截胡）==")
        win.links_edit.clear()
        win.tabs.setCurrentIndex(1)
        self.processEvents()
        target = find_drop_target(win, QPoint(0, 0))
        print("命中目标控件:", type(target).__name__ if target else None)
        ok = fire(win, win.log_edit.viewport(), file_mime(base / "a.mp4"), QPoint(10, 10))
        print("接受:", ok, "| 输入框:", win.links_edit.toPlainText().replace("\n", " | "))

        print("\n== 6. 拖到「输出目录」输入框上（QLineEdit 默认会截胡）==")
        win.links_edit.clear()
        win.tabs.setCurrentIndex(0)
        self.processEvents()
        target = find_drop_target(win, win.dir_edit.mapTo(win, QPoint(5, 5)))
        print("命中目标控件:", type(target).__name__ if target else None)
        ok = fire(win, win.dir_edit, file_mime(base / "a.mp4"), QPoint(5, 5))
        print("接受:", ok, "| 输入框:", win.links_edit.toPlainText().replace("\n", " | "))
        print("输出目录框内容（应保持不变）:", win.dir_edit.text())

        print("\n== 7. 重复拖入同一批内容（去重）==")
        fire(win, win.links_edit.viewport(), file_mime(base / "a.mp4"), QPoint(10, 10))
        print("行数:", len(win.links_edit.toPlainText().splitlines()))
        print("提示:", win.hint_label.text())

        print("\n== 8. 拖入不支持的文件 ==")
        win.links_edit.clear()
        fire(win, win.links_edit.viewport(), file_mime(base / "说明.txt"), QPoint(10, 10))
        print("输入框:", repr(win.links_edit.toPlainText()))
        print("提示:", win.hint_label.text())

        print("\n== 9. 转换报告下拉 ==")
        print("默认:", win.report_box.currentData())

        self.quit()

    QTimer.singleShot(500, later)
    return _orig_exec()


QApplication.exec = patched_exec
from douyin_mp3.gui import run_gui  # noqa: E402

raise SystemExit(run_gui())
