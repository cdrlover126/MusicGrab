"""拖放数据观察器（开发工具）。

启动一个接受拖放的窗口，把拖进来的 QMimeData 的全部格式与内容打印出来，
用于研究 Chrome / Edge 拖标签页时到底提供了哪些 MIME 数据。

用法: python packaging/probe_drop_target.py [日志文件路径]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("drop_target.log")
_lines: list[str] = []


def dump(tag: str, mime) -> None:
    lines = [f"===== {tag} ====="]
    try:
        formats = list(mime.formats() or [])
    except Exception as exc:  # noqa: BLE001
        formats = []
        lines.append(f"formats() 异常: {exc}")
    lines.append(f"formats(): {formats}")
    lines.append(f"hasUrls(): {mime.hasUrls()}")
    try:
        lines.append(f"urls(): {[u.toString() for u in mime.urls()]}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"urls() 异常: {exc}")
    lines.append(f"text(): {mime.text()!r}")
    for fmt in formats:
        try:
            data = mime.data(fmt)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"  {fmt}: 读取异常 {exc}")
            continue
        raw = bytes(data) if not isinstance(data, bytes) else data
        head = raw[:120]
        lines.append(f"  {fmt}: len={len(raw)} head={head!r}")
        for enc in ("utf-8", "utf-16", "gb18030"):
            try:
                lines.append(f"      {enc} -> {raw.decode(enc)[:160]!r}")
                break
            except Exception:  # noqa: BLE001
                continue
    text = "\n".join(lines)
    _lines.append(text)
    print(text)
    print("-" * 60)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(text + "\n" + "-" * 60 + "\n")


class DropTarget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MusicGrab Drop Inspector")
        self.setAcceptDrops(True)
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        label = QLabel("把 Chrome 的标签页 / 链接拖到这里")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        dump("DragEnter", event.mimeData())
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        dump("Drop", event.mimeData())
        event.setDropAction(Qt.CopyAction)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    win = DropTarget()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
