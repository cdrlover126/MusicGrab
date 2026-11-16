"""生成 CSDN 博文插图（GUI 截图）。开发工具。

用法: python packaging/make_screenshots.py
输出: docs/images/*.png
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = root / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

WORK = Path(r"C:\Users\cdrlover\Music")
WORK.mkdir(parents=True, exist_ok=True)

SAMPLES = [
    ("示例视频A", "0x2563eb"),
    ("示例视频B", "0x7c3aed"),
    ("示例视频C", "0x059669"),
    ("示例视频D", "0xea580c"),
    ("示例视频E", "0xdc2626"),
]
DURATION = 600

_orig_exec = QApplication.exec


def make_samples() -> list[Path]:
    from musicgrab.converter import find_ffmpeg

    ff = find_ffmpeg()
    paths: list[Path] = []
    for title, color in SAMPLES:
        dst = WORK / f"{title}.mp4"
        if not dst.exists() or dst.stat().st_size < 10000:
            subprocess.run(
                [ff, "-y", "-hide_banner",
                 "-f", "lavfi", "-i", f"sine=frequency=440:duration={DURATION}",
                 "-f", "lavfi", "-i", f"color=c={color}:s=320x180:d={DURATION}",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", str(dst)],
                capture_output=True,
            )
        paths.append(dst)
    return paths


def grab(win, name: str) -> None:
    pix = win.grab()
    path = OUT / name
    pix.save(str(path))
    print(f"  saved {name}  {pix.width()}x{pix.height()}")


def close_dialogs() -> None:
    for w in QApplication.topLevelWidgets():
        if isinstance(w, QMessageBox) and w.isVisible():
            w.close()


def patched(self):
    def find():
        for x in self.topLevelWidgets():
            if hasattr(x, "tabs"):
                return x
        return None

    def log_text(win) -> str:
        try:
            return win.log_edit.toPlainText()
        except Exception:
            return ""

    def step1():
        win = find()
        if win is None:
            self.quit()
            return
        print("[1/4] 主界面 · 输出设置")
        win.tabs.setCurrentIndex(0)
        self.processEvents()
        grab(win, "01-主界面-输出设置.png")

        print("[2/4] 多行粘贴 · 下拉工具条")
        win.links_edit.setPlainText(
            "7.92 复制打开抖音，看看【某某的作品】 https://v.douyin.com/iAbCdEf/\n"
            "https://v.kuaishou.com/nmqf0KDZ\n"
            "https://www.kugou.com/mixsong/g5jy4e47.html\n"
            "https://www.bilibili.com/video/BV1rcn56hEoT\n"
            "https://music.163.com/song?id=347230"
        )
        self.processEvents()
        grab(win, "02-多行粘贴-下拉工具条.png")

        print("[3/4] 详情日志 · 真实处理过程")
        win.links_edit.setPlainText("\n".join(str(p) for p in sample_paths))
        win.tabs.setCurrentIndex(1)
        win.start()
        QTimer.singleShot(3000, step3)

    def step3():
        win = find()
        if win is None:
            self.quit()
            return
        grab(win, "03-详情日志-实时过程.png")
        print("[4/4] 等待转换完成")
        state["tries"] = 0
        QTimer.singleShot(1000, step4)

    def step4():
        win = find()
        if win is None:
            self.quit()
            return
        state["tries"] += 1
        text = log_text(win)
        done = "报告已保存" in text or ("完成：成功" in text and "完成 ->" not in text.split("完成：成功")[-1])
        if not done and state["tries"] < 180:
            QTimer.singleShot(1000, step4)
            return
        close_dialogs()
        self.processEvents()
        win.tabs.setCurrentIndex(1)
        self.processEvents()
        grab(win, "04-详情日志-完成汇总.png")
        print("日志尾部:")
        for line in text.strip().splitlines()[-8:]:
            print("   ", line)
        self.quit()

    state = {"tries": 0}
    QTimer.singleShot(700, step1)
    return _orig_exec()


QApplication.exec = patched

sample_paths = make_samples()
print("示例视频:", [p.name for p in sample_paths])

from musicgrab.gui import run_gui  # noqa: E402

run_gui()
print("插图输出目录:", OUT)
