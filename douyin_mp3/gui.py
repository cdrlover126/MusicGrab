from __future__ import annotations

import sys
from pathlib import Path

from .batch import BatchProcessor
from .config import (
    AUDIO_SOURCE_CHOICES,
    AUDIO_SOURCE_LABELS,
    COOKIE_BROWSER_CHOICES,
    DEFAULT_OUTPUT_DIR,
    ENGINE_CHOICES,
    ENGINE_LABELS,
    QUALITY_PRESETS,
    ConvertOptions,
)


def run_gui() -> int:
    try:
        from PySide6.QtCore import Qt, QThread, Signal
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QFileDialog,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QProgressBar,
            QPushButton,
            QSpinBox,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print("未安装 PySide6，无法启动图形界面。请执行: pip install PySide6", file=sys.stderr)
        return 2

    from . import APP_NAME, __version__

    class Worker(QThread):
        log = Signal(str)
        item_start = Signal(int, int, str)
        item_done = Signal(object)
        finished_all = Signal(object)

        def __init__(self, options: ConvertOptions, lines: list[str]):
            super().__init__()
            self.processor = BatchProcessor(options)
            self.lines = lines
            self.processor.on_log = self.log.emit
            self.processor.on_item_start = lambda i, t, u: self.item_start.emit(i, t, u)
            self.processor.on_item_done = self.item_done.emit
            self.processor.on_all_done = self.finished_all.emit

        def run(self) -> None:  # noqa: A003
            self.processor.run(self.lines)

        def stop(self) -> None:
            self.processor.cancel()

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(f"{APP_NAME} v{__version__} — 视频音乐批量转MP3（抖音/快手/B站/微博等）")
            self.resize(880, 640)
            self.worker: Worker | None = None

            root = QVBoxLayout()
            intro = QLabel(
                "粘贴视频分享文本或链接（每行一条）：内置解析抖音、快手；"
                "B站/微博/网易云/西瓜/YouTube 等站点走 yt-dlp，自动识别平台"
            )
            intro.setWordWrap(True)
            root.addWidget(intro)

            self.links_edit = QPlainTextEdit()
            self.links_edit.setPlaceholderText(
                "例：\n7.99 复制打开抖音 https://v.douyin.com/xxxxxxx/ 看看热门歌曲\n"
                "https://v.kuaishou.com/xxxxxx\n"
                "https://www.bilibili.com/video/BV1xx411c7mD\n"
                "https://www.weibo.com/tv/show/1034:xxxxxxxx"
            )
            root.addWidget(self.links_edit, stretch=3)

            box = QGroupBox("输出设置")
            grid = QGridLayout(box)

            grid.addWidget(QLabel("音质（车机兼容推荐192）:"), 0, 0)
            self.quality_box = QComboBox()
            for preset in QUALITY_PRESETS.values():
                self.quality_box.addItem(f"{preset.label}（{preset.note}）", preset.key)
            self.quality_box.setCurrentIndex(1)
            grid.addWidget(self.quality_box, 0, 1)

            grid.addWidget(QLabel("自定义kbps:"), 0, 2)
            self.custom_quality = QSpinBox()
            self.custom_quality.setRange(32, 320)
            self.custom_quality.setSpecialValueText("跟随上方预设")
            self.custom_quality.setValue(0)
            grid.addWidget(self.custom_quality, 0, 3)

            grid.addWidget(QLabel("音频来源:"), 1, 0)
            self.source_box = QComboBox()
            for key in AUDIO_SOURCE_CHOICES:
                self.source_box.addItem(AUDIO_SOURCE_LABELS[key], key)
            grid.addWidget(self.source_box, 1, 1)

            grid.addWidget(QLabel("条数间隔(秒):"), 1, 2)
            self.delay_spin = QSpinBox()
            self.delay_spin.setRange(0, 30)
            self.delay_spin.setValue(2)
            grid.addWidget(self.delay_spin, 1, 3)

            grid.addWidget(QLabel("解析引擎:"), 2, 0)
            self.engine_box = QComboBox()
            for key in ENGINE_CHOICES:
                self.engine_box.addItem(ENGINE_LABELS[key], key)
            grid.addWidget(self.engine_box, 2, 1)

            grid.addWidget(QLabel("代理(境外站点需要):"), 2, 2)
            self.proxy_edit = QLineEdit()
            self.proxy_edit.setPlaceholderText("如 http://127.0.0.1:7890，留空直连")
            grid.addWidget(self.proxy_edit, 2, 3)

            grid.addWidget(QLabel("cookies 文件:"), 3, 0)
            self.cookies_edit = QLineEdit()
            self.cookies_edit.setPlaceholderText("用于西瓜/小红书/QQ音乐等需登录站点，可留空")
            grid.addWidget(self.cookies_edit, 3, 1, 1, 2)
            cookies_btn = QPushButton("选择…")
            cookies_btn.clicked.connect(self.pick_cookies)
            grid.addWidget(cookies_btn, 3, 3)

            grid.addWidget(QLabel("或读取浏览器 cookies:"), 4, 0)
            self.browser_box = QComboBox()
            self.browser_box.addItem("不使用", "")
            for name in COOKIE_BROWSER_CHOICES:
                self.browser_box.addItem(name, name)
            grid.addWidget(self.browser_box, 4, 1)

            grid.addWidget(QLabel("输出目录:"), 5, 0)
            self.dir_edit = QLineEdit(str(DEFAULT_OUTPUT_DIR))
            grid.addWidget(self.dir_edit, 5, 1, 1, 2)
            browse = QPushButton("浏览…")
            browse.clicked.connect(self.pick_dir)
            grid.addWidget(browse, 5, 3)
            root.addWidget(box)

            btn_row = QHBoxLayout()
            self.start_btn = QPushButton("开始转换")
            self.start_btn.setMinimumHeight(36)
            self.start_btn.clicked.connect(self.start)
            self.stop_btn = QPushButton("停止")
            self.stop_btn.setEnabled(False)
            self.stop_btn.clicked.connect(self.stop)
            btn_row.addWidget(self.start_btn)
            btn_row.addWidget(self.stop_btn)
            root.addLayout(btn_row)

            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            root.addWidget(self.progress)

            self.log_edit = QPlainTextEdit()
            self.log_edit.setReadOnly(True)
            font = QFont("Consolas", 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            self.log_edit.setFont(font)
            root.addWidget(self.log_edit, stretch=2)

            central = QWidget()
            central.setLayout(root)
            self.setCentralWidget(central)

        def pick_dir(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, "选择输出目录", self.dir_edit.text())
            if chosen:
                self.dir_edit.setText(chosen)

        def pick_cookies(self) -> None:
            chosen, _ = QFileDialog.getOpenFileName(
                self, "选择 cookies 文件（Netscape 格式）", "", "Cookies (*.txt);;所有文件 (*)"
            )
            if chosen:
                self.cookies_edit.setText(chosen)

        def append_log(self, msg: str) -> None:
            self.log_edit.appendPlainText(msg)

        def start(self) -> None:
            lines = [
                line.strip()
                for line in self.links_edit.toPlainText().splitlines()
                if line.strip()
            ]
            if not lines:
                QMessageBox.warning(self, APP_NAME, "请先粘贴至少一条链接或分享文本")
                return
            if self.custom_quality.value() >= 32:
                quality = str(self.custom_quality.value())
            else:
                quality = self.quality_box.currentData()
            options = ConvertOptions(
                output_dir=Path(self.dir_edit.text()).expanduser(),
                quality=quality,
                audio_source=self.source_box.currentData(),
                engine=self.engine_box.currentData(),
                delay=self.delay_spin.value() / 1.0,
                proxy=self.proxy_edit.text().strip() or None,
                cookies_file=self.cookies_edit.text().strip() or None,
                cookies_from_browser=self.browser_box.currentData() or None,
            )
            self.worker = Worker(options, lines)
            self.worker.log.connect(self.append_log)
            self.worker.item_start.connect(self._on_item_start)
            self.worker.item_done.connect(self._on_item_done)
            self.worker.finished_all.connect(self._on_finished)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.progress.setValue(0)
            self.worker.start()

        def _on_item_start(self, index: int, total: int, _url: str) -> None:
            self.progress.setMaximum(total)
            self.progress.setValue(index - 1)
            self.append_log(f"—— 第 {index}/{total} 条 ——")

        def stop(self) -> None:
            if self.worker:
                self.append_log("正在停止…（等待当前任务结束）")
                self.worker.stop()
                self.stop_btn.setEnabled(False)

        def _on_item_done(self, result: object) -> None:
            status = getattr(result, "status", "")
            if status == "ok":
                self.progress.setValue(self.progress.value() + 1)

        def _on_finished(self, summary: object) -> None:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            ok = getattr(summary, "succeeded", 0)
            fail = getattr(summary, "failed", 0)
            self.progress.setValue(self.progress.maximum())
            QMessageBox.information(self, APP_NAME, f"全部完成：成功 {ok} 个，失败 {fail} 个")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()
