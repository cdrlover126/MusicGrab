"""乐取 MusicGrab 图形界面启动器（双击运行，不显示控制台窗口）。

Windows 下 .pyw 关联 pythonw.exe，启动时不会出现黑色控制台窗口。
命令行模式请使用 `python -m douyin_mp3 convert ...`。
"""
from douyin_mp3.gui import run_gui

if __name__ == "__main__":
    run_gui()
