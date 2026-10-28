"""启动 GUI 截图，用于排查布局问题（开发工具）。

用法: python packaging/probe_layout.py [tab_index]
"""
import sys
from pathlib import Path

root = Path(r"E:\ai\opencode\内网web自动化开发\douyin-mp3")
sys.path.insert(0, str(root))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

tab_index = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else 0

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
        if "--paste5" in sys.argv:
            win.links_edit.setPlainText(
                "7.92 复制打开抖音，看看【某人的作品】 https://v.douyin.com/iAbCdEf/\n"
                "https://v.kuaishou.com/nmqf0KDZ\n"
                "https://www.kugou.com/mixsong/g5jy4e47.html\n"
                "https://www.bilibili.com/video/BV1rcn56hEoT\n"
                "https://music.163.com/song?id=347230"
            )
        elif "--paste" in sys.argv:
            win.links_edit.setPlainText(
                "7.92 复制打开抖音，看看【某人的作品】 https://v.douyin.com/iAbCdEf/\n"
                "https://v.kuaishou.com/nmqf0KDZ\n"
                "https://www.kugou.com/mixsong/g5jy4e47.html\n"
                "https://www.bilibili.com/video/BV1rcn56hEoT"
            )
        if "--save" in sys.argv:
            win.resize(980, 980)
        self.processEvents()
        pix = win.grab()
        out = root / "packaging" / "layout_probe.png"
        if "--save" in sys.argv:
            index = sys.argv.index("--save") + 1
            if index < len(sys.argv):
                out = Path(sys.argv[index])
                if not out.is_absolute():
                    out = root / out
        pix.save(str(out))
        print("captured(qt)", pix.width(), "x", pix.height(), "tab=", tab_index, "->", out)
        self.quit()

    QTimer.singleShot(700, later)
    return _orig_exec()


QApplication.exec = patched_exec

from douyin_mp3.gui import run_gui  # noqa: E402

run_gui()
