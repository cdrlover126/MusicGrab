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
            QToolButton,
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

    class CollapsibleBox(QWidget):
        def __init__(self, title: str, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.toggle_button = QToolButton()
            self.toggle_button.setStyleSheet("QToolButton { border: none; font-weight: bold; text-align: left; padding: 4px; }")
            self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.toggle_button.setArrowType(Qt.RightArrow)
            self._collapsed_text = title
            self._expanded_text = title.replace("点击展开", "点击收起")
            self.toggle_button.setText(self._collapsed_text)
            self.toggle_button.setCheckable(True)
            self.toggle_button.setChecked(False)
            self.toggle_button.clicked.connect(self.on_toggled)

            self.content_area = QFrame()
            self.content_area.setFrameShape(QFrame.StyledPanel)
            self.content_area.setStyleSheet("QFrame { background: transparent; }")
            self.content_area.setVisible(False)

            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            lay.addWidget(self.toggle_button)
            lay.addWidget(self.content_area)

            self.content_layout = QGridLayout(self.content_area)
            self.content_layout.setContentsMargins(18, 16, 18, 16)
            self.content_layout.setHorizontalSpacing(16)
            self.content_layout.setVerticalSpacing(14)
            self.content_layout.setColumnMinimumWidth(0, 116)
            self.content_layout.setColumnStretch(1, 1)

        def on_toggled(self) -> None:
            checked = self.toggle_button.isChecked()
            self.content_area.setVisible(checked)
            self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
            self.toggle_button.setText(self._expanded_text if checked else self._collapsed_text)

        def add_row(self, row: int, label: str, widget: QWidget) -> None:
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #374151;")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumWidth(110)
            self.content_layout.addWidget(lbl, row, 0)
            self.content_layout.addWidget(widget, row, 1)

        def add_widget(self, widget: QWidget, row: int, col: int, row_span: int = 1, col_span: int = 1) -> None:
            self.content_layout.addWidget(widget, row, col, row_span, col_span)

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(f"{APP_NAME} {APP_NAME_EN} v{__version__}")
            self.resize(900, 700)
            self.setMinimumSize(820, 560)
            self.worker: Worker | None = None
            self._log_visible = False

            self.setStyleSheet(
                """
                QMainWindow { background: #f7f7f9; }
                QPlainTextEdit { background: #ffffff; border: 1px solid #d8d8e0; border-radius: 6px; padding: 8px; }
                QLineEdit, QComboBox { background: #ffffff; border: 1px solid #d8d8e0; border-radius: 5px; padding: 7px 9px; min-height: 26px; }
                QLineEdit:focus, QComboBox:focus { border: 1px solid #2563eb; }
                QSpinBox { background: #ffffff; border: 1px solid #d8d8e0; border-radius: 5px; padding: 7px 0px 7px 9px; min-height: 26px; }
                QSpinBox:focus { border: 1px solid #2563eb; }
                QComboBox::drop-down { border: none; width: 22px; }
                QPushButton { background: #2563eb; color: white; border: none; border-radius: 5px; padding: 8px 18px; }
                QPushButton:hover { background: #1d4ed8; }
                QPushButton:disabled { background: #9ca3af; color: #f3f4f6; }
                QToolButton { color: #1f2937; }
                QProgressBar { border: 1px solid #d8d8e0; border-radius: 5px; text-align: center; background: #ffffff; height: 20px; }
                QProgressBar::chunk { background: #22c55e; border-radius: 5px; }
                QLabel { color: #1f2937; }
                """
            )

            root = QVBoxLayout()
            root.setContentsMargins(18, 16, 18, 14)
            root.setSpacing(10)

            title = QLabel("批量提取各平台音轨，转为车机可播放的 MP3")
            title.setStyleSheet("font-size: 15px; font-weight: bold;")
            title_policy = title.sizePolicy()
            title_policy.setVerticalPolicy(QSizePolicy.Fixed)
            title.setSizePolicy(title_policy)
            root.addWidget(title)

            sub = QLabel("支持抖音、快手、酷狗、B站、微博、网易云等 1500+ 站点，自动识别平台与登录态")
            sub.setStyleSheet("color: #4b5563;")
            sub_policy = sub.sizePolicy()
            sub_policy.setVerticalPolicy(QSizePolicy.Fixed)
            sub.setSizePolicy(sub_policy)
            root.addWidget(sub)

            self.links_edit = QPlainTextEdit()
            self.links_edit.setPlaceholderText(
                "粘贴分享链接或口令（每行一条）\n"
                "例：https://v.douyin.com/xxxxxxx/\n"
                "https://v.kuaishou.com/xxxxxx\n"
                "https://www.kugou.com/mixsong/xxxxxx.html\n"
                "https://www.bilibili.com/video/BVxxxx"
            )
            self.links_edit.setMinimumHeight(150)
            self.links_edit.setMaximumHeight(190)
            links_policy = self.links_edit.sizePolicy()
            links_policy.setVerticalPolicy(QSizePolicy.Fixed)
            self.links_edit.setSizePolicy(links_policy)
            root.addWidget(self.links_edit)

            self.adv_box = CollapsibleBox("输出设置（点击展开）")
            adv = self.adv_box

            adv.add_row(0, "音质", self._make_quality_row())
            adv.add_row(1, "音频来源", self._make_source_row())
            adv.add_row(2, "解析引擎", self._make_engine_row())
            adv.add_row(3, "条数间隔（秒）", self._make_delay_row())
            adv.add_row(4, "代理", self._make_proxy_row())
            adv.add_row(5, "Cookies 文件", self._make_cookies_row())
            adv.add_row(6, "读取浏览器 Cookies", self._make_browser_row())
            adv.add_row(7, "输出目录", self._make_dir_row())

            root.addWidget(self.adv_box)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(8)
            self.start_btn = QPushButton("开始转换")
            self.start_btn.setMinimumHeight(34)
            self.start_btn.clicked.connect(self.start)
            self.stop_btn = QPushButton("停止")
            self.stop_btn.setMinimumHeight(34)
            self.stop_btn.setStyleSheet("QPushButton { background: #dc2626; } QPushButton:hover { background: #b91c1c; } QPushButton:disabled { background: #9ca3af; }")
            self.stop_btn.setEnabled(False)
            self.stop_btn.clicked.connect(self.stop)
            self.log_toggle = QPushButton("显示详情日志")
            self.log_toggle.setMinimumHeight(34)
            self.log_toggle.setStyleSheet("QPushButton { background: #ffffff; color: #374151; border: 1px solid #d8d8e0; } QPushButton:hover { background: #f3f4f6; border-color: #9ca3af; }")
            self.log_toggle.clicked.connect(self.toggle_log)

            btn_row.addWidget(self.start_btn)
            btn_row.addWidget(self.stop_btn)
            btn_row.addStretch()
            btn_row.addWidget(self.log_toggle)
            root.addLayout(btn_row)

            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("%p%")
            self.progress.setTextVisible(True)
            self.progress.setMinimumHeight(20)
            root.addWidget(self.progress)

            self.log_edit = QPlainTextEdit()
            self.log_edit.setReadOnly(True)
            font = QFont("Consolas", 9)
            font.setStyleHint(QFont.StyleHint.Monospace)
            self.log_edit.setFont(font)
            self.log_edit.setMinimumHeight(140)
            self.log_edit.setVisible(False)
            root.addWidget(self.log_edit)

            central = QWidget()
            central.setLayout(root)

            # 用滚动区承载内容，展开「输出设置」或显示日志时不会被裁切
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setStyleSheet(
                "QScrollArea { background: #f7f7f9; border: none; }"
                "QScrollArea > QWidget > QWidget { background: #f7f7f9; }"
            )
            scroll.setWidget(central)
            self.setCentralWidget(scroll)
            self._content = central

            adv.toggle_button.clicked.connect(self._sync_window_height)

        def _sync_window_height(self) -> None:
            """展开/收起「输出设置」时自动调整窗口高度，保证内容完整可见。"""
            self._content.layout().activate()
            needed = self._content.sizeHint().height() + 56
            screen = QApplication.primaryScreen()
            limit = screen.availableGeometry().height() - 80 if screen else needed
            target = max(self.minimumHeight(), min(needed, limit))
            if abs(target - self.height()) > 8:
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
            btn.setStyleSheet(
                "QPushButton { background: #ffffff; color: #374151; border: 1px solid #d8d8e0; } QPushButton:hover { background: #f3f4f6; border-color: #9ca3af; }"
            )
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
            btn.setStyleSheet(
                "QPushButton { background: #ffffff; color: #374151; border: 1px solid #d8d8e0; } QPushButton:hover { background: #f3f4f6; border-color: #9ca3af; }"
            )
            btn.clicked.connect(self.pick_dir)
            h.addWidget(self.dir_edit, 1)
            h.addWidget(btn, 0)
            return w

        def toggle_log(self) -> None:
            self._log_visible = not self._log_visible
            self.log_edit.setVisible(self._log_visible)
            self.log_toggle.setText("隐藏详情日志" if self._log_visible else "显示详情日志")
            if self._log_visible and self.log_edit.toPlainText():
                self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

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
            if self._log_visible:
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
            self.adv_box.setEnabled(False)
            self.links_edit.setReadOnly(True)
            self.progress.setRange(0, len(lines))
            self.progress.setValue(0)
            self.progress.setFormat(f"%p%（{len(lines)} 条）")
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

        def _on_item_done(self, result: object) -> None:
            status = getattr(result, "status", "")
            if status == "ok":
                self.progress.setValue(self.progress.value() + 1)

        def _on_finished(self, summary: object) -> None:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.adv_box.setEnabled(True)
            self.links_edit.setReadOnly(False)
            ok = getattr(summary, "succeeded", 0)
            fail = getattr(summary, "failed", 0)
            total = getattr(summary, "total", 0)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(total)
            self.progress.setFormat(f"完成：成功 {ok} / 失败 {fail} · %p%")
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
