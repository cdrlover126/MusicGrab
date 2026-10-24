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


def _icon_path() -> Path | None:
    """定位应用图标（PNG），兼容源码运行与 PyInstaller 打包后的运行环境。"""
    candidates: list[Path] = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.append(Path(base) / "assets" / "icon.png")
    candidates.append(Path(__file__).resolve().parents[1] / "assets" / "icon.png")
    for path in candidates:
        if path.is_file():
            return path
    return None


def run_gui() -> int:
    try:
        from PySide6.QtCore import Qt, QThread, Signal
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QFileDialog,
            QFrame,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QProgressBar,
            QPushButton,
            QScrollArea,
            QSizePolicy,
            QSpinBox,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print("未安装 PySide6，无法启动图形界面。请执行: pip install PySide6", file=sys.stderr)
        return 2

    from . import APP_NAME, APP_NAME_EN, __version__

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

        def run(self) -> None:
            self.processor.run(self.lines)

        def stop(self) -> None:
            self.processor.cancel()

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(f"{APP_NAME} {APP_NAME_EN} v{__version__}")
            self.resize(900, 700)
            self.setMinimumSize(820, 560)
            self.worker: Worker | None = None

            self.setStyleSheet(
                """
                QMainWindow { background: #f7f7f9; }
                QPlainTextEdit { background: #ffffff; border: 1px solid #d8d8e0; border-radius: 6px; padding: 8px; }
                QLineEdit, QComboBox, QPushButton { min-height: 30px; }
                QSpinBox { min-height: 26px; }
                QLineEdit, QComboBox { background: #ffffff; border: 1px solid #d8d8e0; border-radius: 5px; padding: 0px 9px; }
                QSpinBox { background: #ffffff; border: 1px solid #d8d8e0; border-radius: 5px; padding: 0px 0px 0px 9px; }
                QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #2563eb; }
                QComboBox::drop-down { border: none; width: 22px; }
                QSpinBox::up-button { height: 13px; }
                QSpinBox::down-button { height: 13px; }
                QPushButton { background: #2563eb; color: white; border: 1px solid transparent; border-radius: 5px; padding: 0px 20px; }
                QPushButton:hover { background: #1d4ed8; }
                QPushButton:disabled { background: #9ca3af; color: #f3f4f6; }
                QPushButton[secondary="true"] { background: #ffffff; color: #374151; border-color: #d8d8e0; }
                QPushButton[secondary="true"]:hover { background: #f3f4f6; border-color: #9ca3af; }
                QPushButton[danger="true"] { background: #dc2626; }
                QPushButton[danger="true"]:hover { background: #b91c1c; }
                QPushButton[danger="true"]:disabled { background: #9ca3af; color: #f3f4f6; }
                QTabWidget { background: #ffffff; }
                QTabWidget::pane { border: 1px solid #d8d8e0; border-top: none; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; background: #ffffff; top: -1px; }
                QTabBar { background: #ffffff; }
                QTabBar::tab { background: #ececf2; color: #4b5563; border: 1px solid #d8d8e0; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 7px 22px; margin-right: 3px; }
                QTabBar::tab:selected { background: #ffffff; color: #111827; font-weight: bold; }
                QTabBar::tab:hover:!selected { background: #f3f4f6; }
                QProgressBar { border: 1px solid #d8d8e0; border-radius: 5px; text-align: center; background: #ffffff; height: 20px; }
                QProgressBar::chunk { background: #22c55e; border-radius: 5px; }
                QLabel { color: #1f2937; }
                """
            )

            root = QVBoxLayout()
            root.setContentsMargins(18, 16, 18, 12)
            root.setSpacing(10)

            body = QVBoxLayout()
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(10)

            title = QLabel("批量提取各平台音轨，转为车机可播放的 MP3")
            title.setStyleSheet("font-size: 15px; font-weight: bold;")
            title_policy = title.sizePolicy()
            title_policy.setVerticalPolicy(QSizePolicy.Fixed)
            title.setSizePolicy(title_policy)
            body.addWidget(title)

            sub = QLabel("支持抖音、快手、酷狗、B站、微博、网易云等 1500+ 站点，自动识别平台与登录态")
            sub.setStyleSheet("color: #4b5563;")
            sub_policy = sub.sizePolicy()
            sub_policy.setVerticalPolicy(QSizePolicy.Fixed)
            sub.setSizePolicy(sub_policy)
            body.addWidget(sub)

            self.links_edit = QPlainTextEdit()
            self.links_edit.setPlaceholderText(
                "粘贴分享链接或口令（每行一条）\n"
                "例：https://v.douyin.com/xxxxxxx/\n"
                "https://v.kuaishou.com/xxxxxx\n"
                "https://www.kugou.com/mixsong/xxxxxx.html\n"
                "https://www.bilibili.com/video/BVxxxx"
            )
            self.links_edit.setFixedHeight(150)
            body.addWidget(self.links_edit)

            # 主操作按钮置于选项页之上
            btn_row = QHBoxLayout()
            btn_row.setSpacing(10)
            self.start_btn = QPushButton("开始转换")
            self.start_btn.setMinimumWidth(112)
            self.start_btn.clicked.connect(self.start)
            self.stop_btn = QPushButton("停止")
            self.stop_btn.setMinimumWidth(88)
            self.stop_btn.setProperty("danger", True)
            self.stop_btn.setEnabled(False)
            self.stop_btn.clicked.connect(self.stop)
            btn_row.addWidget(self.start_btn)
            btn_row.addWidget(self.stop_btn)
            btn_row.addStretch(1)
            self.hint_label = QLabel("就绪")
            self.hint_label.setStyleSheet("color: #6b7280;")
            btn_row.addWidget(self.hint_label)
            body.addLayout(btn_row)

            # 「输出设置」与「详情日志」以选项页切换
            self.tabs = QTabWidget()
            self.tabs.setDocumentMode(True)

            self.settings_page = QWidget()
            self.settings_grid = QGridLayout(self.settings_page)
            self.settings_grid.setContentsMargins(16, 14, 16, 14)
            self.settings_grid.setHorizontalSpacing(14)
            self.settings_grid.setVerticalSpacing(10)
            self.settings_grid.setColumnMinimumWidth(0, 112)
            self.settings_grid.setColumnStretch(1, 1)
            self._add_setting(0, "音质", self._make_quality_row())
            self._add_setting(1, "音频来源", self._make_source_row())
            self._add_setting(2, "解析引擎", self._make_engine_row())
            self._add_setting(3, "条数间隔（秒）", self._make_delay_row())
            self._add_setting(4, "代理", self._make_proxy_row())
            self._add_setting(5, "Cookies 文件", self._make_cookies_row())
            self._add_setting(6, "读取浏览器 Cookies", self._make_browser_row())
            self._add_setting(7, "输出目录", self._make_dir_row())
            self.tabs.addTab(self.settings_page, "输出设置")

            self.log_page = QWidget()
            log_layout = QVBoxLayout(self.log_page)
            log_layout.setContentsMargins(8, 8, 8, 8)
            self.log_edit = QPlainTextEdit()
            self.log_edit.setReadOnly(True)
            self.log_edit.setPlaceholderText("转换过程中的详细信息会显示在这里")
            font = QFont("Consolas", 9)
            font.setStyleHint(QFont.StyleHint.Monospace)
            self.log_edit.setFont(font)
            log_layout.addWidget(self.log_edit)
            self.tabs.addTab(self.log_page, "详情日志")
            body.addWidget(self.tabs)

            central = QWidget()
            central.setLayout(body)
            self._content = central

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setStyleSheet(
                "QScrollArea { background: #f7f7f9; border: none; }"
                "QScrollArea > QWidget > QWidget { background: #f7f7f9; }"
            )
            scroll.setWidget(central)
            root.addWidget(scroll, 1)

            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("%p%")
            self.progress.setTextVisible(True)
            self.progress.setFixedHeight(20)
            root.addWidget(self.progress)

            shell = QWidget()
            shell.setLayout(root)
            self.setCentralWidget(shell)
            self._fit_tabs()

        def _add_setting(self, row: int, label: str, widget: QWidget) -> None:
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #374151;")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumWidth(106)
            self.settings_grid.addWidget(lbl, row, 0)
            self.settings_grid.addWidget(widget, row, 1)

        def _fit_tabs(self) -> None:
            """依据设置页实际高度固定选项页高度，并让窗口一次容纳全部内容。"""
            self.settings_page.adjustSize()
            page_h = max(self.settings_page.sizeHint().height(), 320)
            self.tabs.setFixedHeight(page_h + 40)

            self._content.adjustSize()
            needed = self._content.sizeHint().height() + 70
            screen = QApplication.primaryScreen()
            limit = screen.availableGeometry().height() - 80 if screen else needed
            target = max(self.minimumHeight(), min(needed, limit))
            if target > self.height():
                self.resize(self.width(), target)

        def _make_quality_row(self) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            self.quality_box = QComboBox()
            self.quality_box.addItem("自定义（在右侧输入）", "")
            for preset in QUALITY_PRESETS.values():
                self.quality_box.addItem(f"{preset.label}", preset.key)
            self.quality_box.setCurrentIndex(2)
            self.custom_quality = QSpinBox()
            self.custom_quality.setRange(0, 320)
            self.custom_quality.setSuffix(" kbps")
            self.custom_quality.setSpecialValueText("跟随预设")
            self.custom_quality.setValue(0)
            self.custom_quality.setFixedWidth(132)
            self.custom_quality.setToolTip("留空则使用左侧预设；填写 32~320 可自定义码率")
            self.quality_box.currentIndexChanged.connect(self._on_preset_changed)
            self.custom_quality.valueChanged.connect(self._on_custom_quality_changed)
            h.addWidget(self.quality_box, 1)
            h.addWidget(self.custom_quality, 0)
            return w

        def _on_preset_changed(self) -> None:
            """选择预设时清空自定义码率。"""
            if self.quality_box.currentData():
                self.custom_quality.setValue(0)

        def _on_custom_quality_changed(self, value: int) -> None:
            """填写自定义码率时，下拉框切换到「自定义」项。"""
            if value > 0 and self.quality_box.currentIndex() != 0:
                self.quality_box.blockSignals(True)
                self.quality_box.setCurrentIndex(0)
                self.quality_box.blockSignals(False)

        def _make_source_row(self) -> QWidget:
            self.source_box = QComboBox()
            for key in AUDIO_SOURCE_CHOICES:
                self.source_box.addItem(AUDIO_SOURCE_LABELS[key], key)
            return self.source_box

        def _make_engine_row(self) -> QWidget:
            self.engine_box = QComboBox()
            for key in ENGINE_CHOICES:
                self.engine_box.addItem(ENGINE_LABELS[key], key)
            return self.engine_box

        def _make_delay_row(self) -> QWidget:
            self.delay_spin = QSpinBox()
            self.delay_spin.setRange(0, 30)
            self.delay_spin.setSuffix(" 秒")
            self.delay_spin.setValue(2)
            self.delay_spin.setFixedWidth(132)
            self.delay_spin.setToolTip("每条任务之间的等待秒数，用于降低平台风控概率")
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            h.addWidget(self.delay_spin, 0)
            h.addStretch(1)
            return w

        def _make_proxy_row(self) -> QWidget:
            self.proxy_edit = QLineEdit()
            self.proxy_edit.setPlaceholderText("http://127.0.0.1:7890（留空直连，境外站点必填）")
            self.proxy_edit.setToolTip("仅当目标站点需要代理时填写，例如 http://127.0.0.1:7890")
            return self.proxy_edit

        def _make_cookies_row(self) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            self.cookies_edit = QLineEdit()
            self.cookies_edit.setPlaceholderText("Netscape 格式 cookies.txt（留空）")
            btn = QPushButton("浏览…")
            btn.setFixedWidth(88)
            btn.setProperty("secondary", True)
            btn.clicked.connect(self.pick_cookies)
            h.addWidget(self.cookies_edit, 1)
            h.addWidget(btn, 0)
            return w

        def _make_browser_row(self) -> QWidget:
            self.browser_box = QComboBox()
            self.browser_box.addItem("不使用", "")
            for name in COOKIE_BROWSER_CHOICES:
                self.browser_box.addItem(name.capitalize(), name)
            return self.browser_box

        def _make_dir_row(self) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            self.dir_edit = QLineEdit(str(DEFAULT_OUTPUT_DIR))
            self.dir_edit.setToolTip("MP3 输出目录，可直接粘贴路径")
            btn = QPushButton("浏览…")
            btn.setFixedWidth(88)
            btn.setProperty("secondary", True)
            btn.clicked.connect(self.pick_dir)
            h.addWidget(self.dir_edit, 1)
            h.addWidget(btn, 0)
            return w

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
            self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

        def start(self) -> None:
            lines = [
                line.strip()
                for line in self.links_edit.toPlainText().splitlines()
                if line.strip()
            ]
            if not lines:
                QMessageBox.warning(self, APP_NAME, "请先粘贴至少一条链接或分享文本")
                return
            custom = self.custom_quality.value()
            if custom > 0:
                quality = str(custom)
            else:
                quality = self.quality_box.currentData() or "192"
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
            self.tabs.setEnabled(False)
            self.links_edit.setReadOnly(True)
            self.progress.setRange(0, len(lines))
            self.progress.setValue(0)
            self.progress.setFormat(f"%p%（{len(lines)} 条）")
            self.hint_label.setText(f"正在转换 {len(lines)} 条…")
            self.worker.start()

        def _on_item_start(self, index: int, total: int, _url: str) -> None:
            self.progress.setRange(0, total)
            self.progress.setValue(index - 1)
            self.progress.setFormat(f"第 {index}/{total} 条 · %p%")

        def stop(self) -> None:
            if self.worker and self.worker.isRunning():
                self.append_log("正在停止…（等待当前任务结束）")
                self.worker.stop()
                self.stop_btn.setEnabled(False)
                self.hint_label.setText("正在停止…")

        def _on_item_done(self, result: object) -> None:
            status = getattr(result, "status", "")
            if status == "ok":
                self.progress.setValue(self.progress.value() + 1)

        def _on_finished(self, summary: object) -> None:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.tabs.setEnabled(True)
            self.links_edit.setReadOnly(False)
            ok = getattr(summary, "succeeded", 0)
            fail = getattr(summary, "failed", 0)
            total = getattr(summary, "total", 0)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(total)
            self.progress.setFormat(f"完成：成功 {ok} / 失败 {fail} · %p%")
            self.hint_label.setText(f"完成：成功 {ok} / 失败 {fail}")
            QMessageBox.information(self, APP_NAME, f"转换完成\n成功：{ok}\n失败：{fail}")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon_file = _icon_path()
    if icon_file is not None:
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(str(icon_file)))
    window = MainWindow()
    if icon_file is not None:
        from PySide6.QtGui import QIcon

        window.setWindowIcon(QIcon(str(icon_file)))
    window.show()
    return app.exec()
