from __future__ import annotations

import sys
from pathlib import Path

from .batch import BatchProcessor
from .config import (
    AUDIO_EXTENSIONS,
    AUDIO_SOURCE_CHOICES,
    AUDIO_SOURCE_LABELS,
    COOKIE_BROWSER_CHOICES,
    DEFAULT_OUTPUT_DIR,
    ENGINE_CHOICES,
    ENGINE_LABELS,
    OUTPUT_FORMATS,
    QUALITY_PRESETS,
    VIDEO_EXTENSIONS,
    ConvertOptions,
)
from .parser import PLATFORM_LABELS, classify_platform, extract_urls
from .proxy import ROUTE_MODE_LABELS, ROUTE_MODES
from . import updater


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
        from PySide6.QtCore import Qt, QObject, QTimer, Signal
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QDialog,
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

    def _safe_emit(signal, *args) -> None:
        """投递信号；窗口已销毁时静默忽略（否则抛 RuntimeError）。"""
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    class WorkerSignals(QObject):
        """批量转换的结果投递通道。"""

        log = Signal(str)
        item_start = Signal(int, int, str)
        item_done = Signal(object)
        finished_all = Signal(object)

    class Worker:
        """批量转换后台任务。

        与组件自检一样用 **daemon 线程**而非 QThread：转换过程中用户关闭窗口时，
        QThread 会被「运行中销毁」，Qt 直接 terminate 掉进程；daemon 线程则会
        随解释器退出，配合 ``processor.cancel()`` 让当前任务尽快收尾。
        """

        def __init__(self, options: ConvertOptions, lines: list[str], signals: WorkerSignals):
            self.processor = BatchProcessor(options)
            self.lines = lines
            self.signals = signals
            self._running = False
            self.processor.on_log = lambda msg: _safe_emit(signals.log, msg)
            self.processor.on_item_start = lambda i, t, u: _safe_emit(signals.item_start, i, t, u)
            self.processor.on_item_done = lambda res: _safe_emit(signals.item_done, res)
            self.processor.on_all_done = lambda s: _safe_emit(signals.finished_all, s)

        def start(self) -> None:
            import threading

            def run() -> None:
                try:
                    self.processor.run(self.lines)
                finally:
                    self._running = False

            self._running = True
            threading.Thread(target=run, daemon=True, name="mg-batch").start()

        def isRunning(self) -> bool:
            return self._running

        def stop(self) -> None:
            self.processor.cancel()

    class UpdateSignals(QObject):
        """后台自检 / 升级的结果投递通道。

        用 **daemon 线程 + Qt 信号** 而不是 QThread：QThread 在「运行中被销毁」
        时会触发 ``QThread: Destroyed while thread is still running`` 并直接
        终止进程——用户启动后立刻关闭程序就会踩到。daemon 线程随解释器退出，
        窗口销毁后 emit 抛 RuntimeError 会被吞掉，不会有任何崩溃。
        """

        checked = Signal(object)
        progress = Signal(int, int)
        message = Signal(str)
        succeeded = Signal(str)
        failed = Signal(str)

    class UpdateChecker:
        """后台自检（daemon 线程）。"""

        def __init__(self, signals: "UpdateSignals") -> None:
            self.signals = signals

        def start(self) -> None:
            import threading

            def worker() -> None:
                try:
                    result = updater.check_components()
                except Exception as exc:
                    result = exc
                try:
                    self.signals.checked.emit(result)
                except RuntimeError:
                    pass  # 窗口已销毁

            threading.Thread(target=worker, daemon=True, name="mg-check").start()

    class UpgradeWorker:
        """后台下载与安装（daemon 线程）。"""

        def __init__(self, signals: "UpdateSignals", statuses: list) -> None:
            self.signals = signals
            self.statuses = list(statuses)

        def start(self) -> None:
            import threading

            def emit(sig, *args) -> None:
                try:
                    sig.emit(*args)
                except RuntimeError:
                    pass  # 对话框已销毁

            def worker() -> None:
                done: list[str] = []
                try:
                    for status in self.statuses:
                        emit(self.signals.message, f"正在获取 {status.label} 的更新…")
                        emit(self.signals.progress, 0, 0)
                        result = updater.upgrade_component(
                            status,
                            on_progress=lambda d, t: emit(self.signals.progress, d, t),
                        )
                        done.append(result)
                except Exception as exc:
                    emit(self.signals.failed, str(exc))
                    return
                emit(self.signals.succeeded, "；".join(done))

            threading.Thread(target=worker, daemon=True, name="mg-upgrade").start()

    class UpgradeDialog(QDialog):
        """组件升级对话框。"""

        def __init__(self, parent, statuses: list) -> None:
            super().__init__(parent)
            self.setWindowTitle("组件升级")
            self.setMinimumWidth(580)
            self.statuses = list(statuses)
            self.signals = UpdateSignals(self)
            self.done_ok = False

            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 16, 18, 14)
            layout.setSpacing(10)

            intro = QLabel(
                "组件过旧会导致部分站点解析失败、音频转码异常。"
                "升级包来自 PyPI 官方仓库（国内自动切换镜像），"
                "仅下载到本机并替换本程序自带的那一份。"
            )
            intro.setWordWrap(True)
            intro.setStyleSheet("color: #4b5563;")
            layout.addWidget(intro)

            self.checks: dict[str, QCheckBox] = {}
            for status in self.statuses:
                box = QCheckBox(status.summary())
                if status.detail:
                    box.setToolTip(status.detail)
                box.setChecked(True)
                self.checks[status.key] = box
                layout.addWidget(box)

            self.status_label = QLabel("就绪")
            self.status_label.setStyleSheet("color: #4b5563;")
            layout.addWidget(self.status_label)

            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFixedHeight(20)
            layout.addWidget(self.progress)

            self.signals.message.connect(self._on_message)
            self.signals.progress.connect(self._on_progress)
            self.signals.succeeded.connect(self._on_success)
            self.signals.failed.connect(self._on_failure)

            buttons = QHBoxLayout()
            self.start_btn = QPushButton("开始升级")
            self.start_btn.setMinimumWidth(112)
            self.start_btn.clicked.connect(self.start_upgrade)
            close_btn = QPushButton("关闭")
            close_btn.setProperty("secondary", True)
            close_btn.setMinimumWidth(88)
            close_btn.clicked.connect(self.reject)
            buttons.addWidget(self.start_btn)
            buttons.addWidget(close_btn)
            buttons.addStretch(1)
            layout.addLayout(buttons)

        def start_upgrade(self) -> None:
            selected = [s for s in self.statuses if self.checks[s.key].isChecked()]
            if not selected:
                QMessageBox.information(self, "组件升级", "请至少勾选一个要升级的组件。")
                return
            self.start_btn.setEnabled(False)
            self.progress.setValue(0)
            worker = UpgradeWorker(self.signals, selected)
            worker.start()

        def _on_message(self, text: str) -> None:
            self.status_label.setText(text)
            self.progress.setValue(0)

        def _on_progress(self, done: int, total: int) -> None:
            if total > 0:
                self.progress.setRange(0, total)
                self.progress.setValue(done)
                self.status_label.setText(f"正在下载… {done * 100 // total}%")
            else:
                self.progress.setRange(0, 0)

        def _on_success(self, text: str) -> None:
            self.done_ok = True
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.status_label.setText(f"{text}。重启程序后新版本才会生效。")
            self.start_btn.setEnabled(True)
            self.start_btn.setText("已完成")
            if getattr(sys, "frozen", False):
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Information)
                box.setWindowTitle("组件升级完成")
                box.setText(f"{text}\n\n重启程序后新版本才会生效。")
                restart_btn = box.addButton("立即重启", QMessageBox.AcceptRole)
                box.addButton("稍后再说", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is restart_btn:
                    self._restart()
            else:
                QMessageBox.information(
                    self, "组件升级完成", f"{text}\n\n重启程序后新版本才会生效。"
                )

        def _on_failure(self, text: str) -> None:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.status_label.setText("升级失败")
            self.start_btn.setEnabled(True)
            self.start_btn.setText("重试")
            QMessageBox.warning(self, "组件升级失败", f"{text}\n\n已保留原有组件，可继续正常使用。")

        def _restart(self) -> None:
            import subprocess

            try:
                subprocess.Popen([sys.executable])
            except OSError:
                pass
            self.accept()
            QApplication.quit()

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
                #updateBanner { background: #fffbeb; border: 1px solid #fcd34d; border-radius: 6px; }
                QLabel { color: #1f2937; }
                """
            )

            root = QVBoxLayout()
            root.setContentsMargins(18, 16, 18, 12)
            root.setSpacing(10)

            body = QVBoxLayout()
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(10)

            # 顶部更新横幅：启动自检发现组件有新版本时出现
            self.update_banner = QFrame()
            self.update_banner.setObjectName("updateBanner")
            banner_layout = QHBoxLayout(self.update_banner)
            banner_layout.setContentsMargins(14, 8, 10, 8)
            banner_layout.setSpacing(10)
            self.update_label = QLabel()
            self.update_label.setWordWrap(True)
            self.update_label.setStyleSheet("color: #78350f;")
            banner_layout.addWidget(self.update_label, 1)
            self.update_btn = QPushButton("立即升级")
            self.update_btn.setMinimumWidth(92)
            self.update_btn.clicked.connect(self.open_upgrade_dialog)
            banner_layout.addWidget(self.update_btn)
            self.ignore_btn = QPushButton("忽略此版本")
            self.ignore_btn.setProperty("secondary", True)
            self.ignore_btn.setMinimumWidth(96)
            self.ignore_btn.clicked.connect(self.ignore_updates)
            banner_layout.addWidget(self.ignore_btn)
            self.update_banner.setVisible(False)
            body.addWidget(self.update_banner)

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
            self.links_edit.setAcceptDrops(True)
            body.addWidget(self.links_edit)

            # 链接区下方：常驻按钮行（添加本地文件 / 清空）
            file_row = QHBoxLayout()
            file_row.setSpacing(10)
            add_file_btn = QPushButton("添加本地文件…")
            add_file_btn.setProperty("secondary", True)
            add_file_btn.setMinimumWidth(126)
            add_file_btn.clicked.connect(self.pick_local_files)
            clear_btn = QPushButton("清空")
            clear_btn.setProperty("secondary", True)
            clear_btn.setMinimumWidth(72)
            clear_btn.clicked.connect(self.clear_links)
            file_row.addWidget(add_file_btn)
            file_row.addWidget(clear_btn)
            file_row.addStretch(1)
            body.addLayout(file_row)

            # 多行粘贴时自动出现的下拉工具条
            self.toolbar = QFrame()
            self.toolbar.setObjectName("bulkToolbar")
            self.toolbar.setFrameShape(QFrame.StyledPanel)
            self.toolbar.setStyleSheet(
                "#bulkToolbar { background: #ffffff; border: 1px solid #e3e4ea; border-radius: 6px; }"
            )
            toolbar_layout = QHBoxLayout(self.toolbar)
            toolbar_layout.setContentsMargins(14, 8, 10, 8)
            toolbar_layout.setSpacing(10)
            self.stats_label = QLabel("已识别 0 条")
            self.stats_label.setStyleSheet("color: #374151;")
            toolbar_layout.addWidget(self.stats_label)
            toolbar_layout.addStretch(1)
            self.bulk_box = QComboBox()
            self.bulk_box.setMinimumWidth(148)
            self.bulk_box.setProperty("secondary", True)
            self.bulk_box.addItem("批量操作…", "")
            for label, action in (
                ("提取纯链接", "extract"),
                ("去除重复", "dedupe"),
                ("按平台排序", "sort"),
                ("载入示例", "sample"),
                ("清空全部", "clear"),
            ):
                self.bulk_box.addItem(label, action)
            self.bulk_box.currentIndexChanged.connect(self._on_bulk_action)
            toolbar_layout.addWidget(self.bulk_box)
            self.toolbar.setVisible(False)
            body.addWidget(self.toolbar)
            self.links_edit.textChanged.connect(self._on_links_changed)

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
            self._add_setting(1, "输出格式", self._make_format_row())
            self._add_setting(2, "音频来源", self._make_source_row())
            self._add_setting(3, "解析引擎", self._make_engine_row())
            self._add_setting(4, "条数间隔（秒）", self._make_delay_row())
            self._add_setting(5, "代理", self._make_proxy_row())
            self._add_setting(6, "Cookies 文件", self._make_cookies_row())
            self._add_setting(7, "读取浏览器 Cookies", self._make_browser_row())
            self._add_setting(8, "输出目录", self._make_dir_row())
            self._add_setting(9, "组件更新", self._make_update_row())
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

            # 组件自检（启动后异步进行，不阻塞界面）
            self._pending_updates: list = []
            self._update_signals = UpdateSignals(self)
            self._update_signals.checked.connect(self._on_check_done)
            self._check_started = False
            QTimer.singleShot(900, self.start_update_check)

        def _add_setting(self, row: int, label: str, widget: QWidget) -> None:
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #374151;")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumWidth(106)
            self.settings_grid.addWidget(lbl, row, 0)
            self.settings_grid.addWidget(widget, row, 1)

        def _fit_tabs(self) -> None:
            """依据设置页实际高度固定选项页高度。"""
            self.settings_page.adjustSize()
            page_h = max(self.settings_page.sizeHint().height(), 320)
            self.tabs.setFixedHeight(page_h + 40)
            self._sync_height()

        def _sync_height(self) -> None:
            """让窗口高度跟随内容（工具条出现/消失时），避免出现滚动条。"""
            self._content.adjustSize()
            needed = self._content.sizeHint().height() + 70
            screen = QApplication.primaryScreen()
            limit = screen.availableGeometry().height() - 80 if screen else needed
            target = max(self.minimumHeight(), min(needed, limit))
            if abs(target - self.height()) > 4:
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
            self.quality_box.setCurrentIndex(4)
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

        def _make_format_row(self) -> QWidget:
            self.format_box = QComboBox()
            for key, spec in OUTPUT_FORMATS.items():
                self.format_box.addItem(f"{spec.label}  ·  .{spec.ext}", key)
            self.format_box.setToolTip(
                "MP3 兼容性最好、车机首选；FLAC/WAV 无损但体积大；"
                "Opus 压缩率最高；WMA 适合老车机"
            )
            return self.format_box

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
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            self.route_box = QComboBox()
            for key in ROUTE_MODES:
                self.route_box.addItem(ROUTE_MODE_LABELS[key], key)
            self.route_box.setToolTip(
                "智能：国内平台直连，境外站点优先使用下方代理，\n"
                "无代理时尝试系统代理/直连（境外用户亦可正常工作）。\n"
                "全部直连：忽略系统代理，全部走直连。\n"
                "全部代理：所有请求都走下方填写的代理。"
            )
            self.proxy_edit = QLineEdit()
            self.proxy_edit.setPlaceholderText("代理地址，如 http://127.0.0.1:7890（智能模式下仅境外站点使用）")
            self.proxy_edit.setToolTip("仅当目标站点需要代理时填写，例如 http://127.0.0.1:7890")
            h.addWidget(self.route_box, 0)
            h.addWidget(self.proxy_edit, 1)
            return w

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

        def _make_update_row(self) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            self.auto_check_box = QCheckBox("启动时检查 yt-dlp / ffmpeg 更新")
            self.auto_check_box.setToolTip(
                "yt-dlp 与 ffmpeg 被打包在程序内部，不会自动更新；\n"
                "开启后每次启动会联网比对官方最新版本并提示升级。"
            )
            self.auto_check_box.setChecked(bool(updater.load_state().get("auto_check", True)))
            self.auto_check_box.toggled.connect(self._on_auto_check_toggled)
            h.addWidget(self.auto_check_box)
            h.addStretch(1)
            self.check_now_btn = QPushButton("立即检查")
            self.check_now_btn.setProperty("secondary", True)
            self.check_now_btn.setFixedWidth(88)
            self.check_now_btn.clicked.connect(lambda: self.start_update_check(manual=True))
            h.addWidget(self.check_now_btn, 0)
            return w

        def pick_dir(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, "选择输出目录", self.dir_edit.text())
            if chosen:
                self.dir_edit.setText(chosen)

        def pick_local_files(self) -> None:
            exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS | AUDIO_EXTENSIONS))
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "选择本地视频 / 音频文件（可多选）",
                "",
                f"媒体文件 ({exts});;视频文件 ({' '.join('*' + e for e in sorted(VIDEO_EXTENSIONS))});;"
                f"音频文件 ({' '.join('*' + e for e in sorted(AUDIO_EXTENSIONS))});;所有文件 (*)",
            )
            if not paths:
                return
            current = self.links_edit.toPlainText().splitlines()
            current = [line for line in current if line.strip()]
            existing = set(current)
            added = 0
            for p in paths:
                if p not in existing:
                    current.append(p)
                    existing.add(p)
                    added += 1
            self.links_edit.setPlainText("\n".join(current))
            self.hint_label.setText(f"已添加 {added} 个本地文件")

        def clear_links(self) -> None:
            self.links_edit.clear()
            self.hint_label.setText("已清空")

        def _current_lines(self) -> list[str]:
            return [line.strip() for line in self.links_edit.toPlainText().splitlines() if line.strip()]

        def _on_links_changed(self) -> None:
            """多行粘贴时自动显示下拉工具条并统计平台分布。"""
            lines = self._current_lines()
            if len(lines) < 2:
                self.toolbar.setVisible(False)
                self._sync_height()
                return
            self.toolbar.setVisible(True)
            counts: dict[str, int] = {}
            link_total = 0
            file_total = 0
            for line in lines:
                urls = extract_urls(line)
                if urls:
                    link_total += len(urls)
                    for u in urls:
                        label = PLATFORM_LABELS.get(classify_platform(u), "通用")
                        counts[label] = counts.get(label, 0) + 1
                else:
                    file_total += 1
            parts = [f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
            text = f"已识别 {link_total} 条链接"
            if file_total:
                text += f" + {file_total} 个本地文件"
            if parts:
                text += " · " + " ".join(parts)
            self.stats_label.setText(text)
            self._sync_height()

        def _on_bulk_action(self, index: int) -> None:
            action = self.bulk_box.itemData(index) if index > 0 else ""
            if not action:
                return
            lines = self._current_lines()
            if action == "extract":
                urls: list[str] = []
                for line in lines:
                    for u in extract_urls(line):
                        if u not in urls:
                            urls.append(u)
                others = [ln for ln in lines if not extract_urls(ln)]
                self.links_edit.setPlainText("\n".join(urls + others))
            elif action == "dedupe":
                seen_urls: set[str] = set()
                seen_lines: set[str] = set()
                kept: list[str] = []
                for line in lines:
                    urls = extract_urls(line)
                    if urls:
                        if any(u in seen_urls for u in urls):
                            continue
                        seen_urls.update(urls)
                        kept.append(line)
                    else:
                        if line in seen_lines:
                            continue
                        seen_lines.add(line)
                        kept.append(line)
                self.links_edit.setPlainText("\n".join(kept))
            elif action == "sort":
                from .parser import PLATFORM_LABELS as _labels

                order = list(_labels.keys())
                def key(line: str) -> tuple[int, str]:
                    urls = extract_urls(line)
                    plat = classify_platform(urls[0]) if urls else "local"
                    idx = order.index(plat) if plat in order else len(order)
                    return (idx, line)
                self.links_edit.setPlainText("\n".join(sorted(lines, key=key)))
            elif action == "sample":
                self.links_edit.setPlainText(
                    "https://v.douyin.com/xxxxxxxxxxx/\n"
                    "https://v.kuaishou.com/xxxxxxxxx\n"
                    "https://www.kugou.com/mixsong/xxxxxxxx.html\n"
                    "https://www.bilibili.com/video/BVxxxxxxxx"
                )
            elif action == "clear":
                self.links_edit.clear()
            self.bulk_box.setCurrentIndex(0)

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
                output_format=self.format_box.currentData() or "mp3",
                audio_source=self.source_box.currentData(),
                engine=self.engine_box.currentData(),
                delay=self.delay_spin.value() / 1.0,
                proxy=self.proxy_edit.text().strip() or None,
                route_mode=self.route_box.currentData() or "auto",
                trust_env=False,
                cookies_file=self.cookies_edit.text().strip() or None,
                cookies_from_browser=self.browser_box.currentData() or None,
            )
            self.worker_signals = WorkerSignals(self)
            self.worker = Worker(options, lines, self.worker_signals)
            self.worker_signals.log.connect(self.append_log)
            self.worker_signals.item_start.connect(self._on_item_start)
            self.worker_signals.item_done.connect(self._on_item_done)
            self.worker_signals.finished_all.connect(self._on_finished)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            # 只锁住「输出设置」页的内容，页签本身保持可点击，
            # 否则处理期间无法切到「详情日志」查看实时进度
            self.settings_page.setEnabled(False)
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

        def closeEvent(self, event) -> None:  # noqa: ANN001
            """关闭时先请求停止当前任务，避免后台线程被硬杀。"""
            if self.worker and self.worker.isRunning():
                self.worker.stop()
            super().closeEvent(event)

        def _on_item_done(self, result: object) -> None:
            status = getattr(result, "status", "")
            if status == "ok":
                self.progress.setValue(self.progress.value() + 1)

        def _on_finished(self, summary: object) -> None:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.settings_page.setEnabled(True)
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

        # ── 组件自检与升级 ─────────────────────────────────────
        def start_update_check(self, manual: bool = False) -> None:
            """启动后台自检（不阻塞界面）。

            `manual=True` 时无视「启动时检查」开关，由用户主动触发。
            """
            if self._check_started:
                if manual:
                    self.append_log("组件检查正在进行中，请稍候…")
                return
            if not manual and not updater.load_state().get("auto_check", True):
                return
            self._check_started = True
            UpdateChecker(self._update_signals).start()

        def _on_check_done(self, result: object) -> None:
            self._check_started = False
            if isinstance(result, Exception):
                # 自检失败不影响使用，只在日志里留痕
                self.append_log(f"组件更新检查失败（不影响使用）：{result}")
                return
            if not isinstance(result, list):
                return
            current = updater.current_ytdlp_version()
            ffmpeg_ver = updater.current_ffmpeg_version()
            pending = [
                status
                for status in result
                if getattr(status, "has_update", False)
                and not updater.is_ignored(status.key, status.latest)
            ]
            self.append_log(
                f"组件自检：yt-dlp {current or '未知'} / ffmpeg {ffmpeg_ver or '未知'}"
            )
            if not pending:
                self.append_log("组件均为最新版本")
                return
            self._pending_updates = pending
            parts = [status.summary() for status in pending]
            self.update_label.setText(
                "⚠ 检测到组件更新可用：" + "；".join(parts)
                + "。yt-dlp 过旧会导致部分站点解析失败。"
            )
            self.update_banner.setVisible(True)

        def _on_auto_check_toggled(self, checked: bool) -> None:
            state = updater.load_state()
            state["auto_check"] = bool(checked)
            updater.save_state(state)

        def ignore_updates(self) -> None:
            for status in self._pending_updates:
                updater.ignore_version(status.key, status.latest)
            self._pending_updates = []
            self.update_banner.setVisible(False)
            self.append_log("已忽略本次更新提示；可在覆盖层目录的 state.json 中清除记录后恢复")

        def open_upgrade_dialog(self) -> None:
            if not self._pending_updates:
                self.start_update_check(manual=True)
                return
            dialog = UpgradeDialog(self, self._pending_updates)
            dialog.exec()
            if getattr(dialog, "done_ok", False):
                self._pending_updates = []
                self.update_banner.setVisible(False)
                self.append_log("组件已升级，重启程序后生效")

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
