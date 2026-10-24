"""启动 GUI 并展开「输出设置」后截图，用于排查布局问题（开发工具）。"""
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

from PIL import Image

root = Path(r"E:\ai\opencode\内网web自动化开发\douyin-mp3")
sys.path.insert(0, str(root))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.PrintWindow.restype = wt.BOOL
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                             ctypes.c_void_p, wt.UINT]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


def capture(hwnd, path, widget=None):
    """用 Qt 自身渲染抓取（绕开 OS 合成差异）。"""
    if widget is not None:
        pix = widget.grab()
        pix.save(str(path))
        print("captured(qt)", pix.width(), "x", pix.height(), "->", path)
        return
    raise RuntimeError("widget required")


def later(app):
    for w in app.topLevelWidgets():
        if hasattr(w, "adv_box"):
            print("collapsed size:", w.width(), w.height())
            w.adv_box.toggle_button.click()
            app.processEvents()
            print("expanded:", w.adv_box.content_area.isVisible(), "size:", w.width(), w.height())
            capture(int(w.winId()), root / "packaging" / "layout_probe.png", widget=w)
            app.quit()
            return
    print("window not found")
    app.quit()


_orig_exec = QApplication.exec


def patched_exec(self):
    QTimer.singleShot(700, lambda: later(self))
    return _orig_exec()


QApplication.exec = patched_exec

from douyin_mp3.gui import run_gui  # noqa: E402

run_gui()
