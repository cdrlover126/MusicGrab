"""Windows 控制台窗口抑制（开发工具无关，运行期生效）。

打包为 GUI 子系统的程序（PyInstaller ``--windowed``）自身不附带控制台。
此时任何**控制台程序**子进程（ffmpeg、ffprobe 等）在被创建时，
Windows 会为它新建一个控制台窗口 —— 表现为运行过程中黑色终端窗口
一闪而过。

本模块在导入时对 ``subprocess.Popen`` 做一次全局包装：
仅当**父进程本身没有控制台**时，为子进程补上 ``CREATE_NO_WINDOW``。
命令行模式下父进程有控制台，子进程照常继承，行为完全不变。
"""
from __future__ import annotations

import os
import subprocess

_PATCHED = False


def parent_has_console() -> bool:
    """当前进程是否已附着控制台。"""
    if os.name != "nt":
        return True
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        return True


def apply() -> bool:
    """安装补丁；返回是否真正生效。"""
    global _PATCHED
    if _PATCHED or os.name != "nt":
        return _PATCHED
    if parent_has_console():
        # 命令行模式：父进程已有控制台，子进程直接继承即可
        _PATCHED = True
        return False

    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    original_init = subprocess.Popen.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = create_no_window
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = patched_init  # type: ignore[method-assign]
    _PATCHED = True
    return True


def is_patched() -> bool:
    return _PATCHED
