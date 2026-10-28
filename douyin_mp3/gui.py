from __future__ import annotations

import os
import sys
from pathlib import Path

from .batch import BatchProcessor
from .config import (
    AUDIO_EXTENSIONS,
    AUDIO_SOURCE_CHOICES,
    AUDIO_SOURCE_LABELS,
    COOKIE_BROWSER_CHOICES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_QUALITY,
    ENGINE_CHOICES,
    ENGINE_LABELS,
    OUTPUT_FORMATS,
    QUALITY_PRESETS,
    REPORT_MODES,
    REPORT_MODE_LABELS,
    VIDEO_EXTENSIONS,
    ConvertOptions,
)
from .dragdrop import (
    LINK_DROP_DISABLED_HINT,
    is_drop_supported,
    parse_drop_data,
    split_drop_payload,
)
from .local_media import DEFAULT_LIMIT, collect_media_paths
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


def disable_child_drops(window, keep=()) -> int:
    """关掉子控件的拖放接收，只保留白名单里的控件。

    ``QLineEdit`` / ``QPlainTextEdit`` / ``QTextEdit`` 默认 ``acceptDrops=True``。
    而 Qt 的 ``findDnDTarget()`` 会把拖放交给「从光标处向上第一个 acceptDrops 的
    控件」——于是把标签页拖到日志框、输出目录等输入框上时，事件被这些控件截胡，
    主窗口根本收不到，表现就是「拖进程序里没反应」。

    关掉它们的接收之后，整个窗口都由主窗口统一接管拖放。
    返回被改动的控件数量。
    """
    from PySide6.QtWidgets import QWidget  # 延迟导入：未装 PySide6 也能用命令行模式

    keep_ids = {id(w) for w in keep}
    changed = 0
    for widget in window.findChildren(QWidget):
        if id(widget) in keep_ids:
            continue
        if widget.acceptDrops():
            widget.setAcceptDrops(False)
            changed += 1
    return changed


def run_gui() -> int:
    try:
        from PySide6.QtCore import Qt, QObject, QTimer, QUrl, Signal
        from PySide6.QtGui import QDesktopServices, QFont
        from PySide6.QtWidgets import (
            QAbstractItemView,
            QApplication,
            QCheckBox,
            QComboBox,
            QDialog,
            QFileDialog,
            QFrame,
            QGridLayout,
            QHBoxLayout,
            QHeaderView,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMenu,
            QMessageBox,
            QPlainTextEdit,
            QProgressBar,
            QPushButton,
            QScrollArea,
            QSizePolicy,
            QSpinBox,
            QTableWidget,
            QTableWidgetItem,
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

    class DropTextEdit(QPlainTextEdit):
        """支持把视频文件、文件夹、浏览器链接直接拖进输入框。"""

        def __init__(self, on_drop, parent=None) -> None:
            super().__init__(parent)
            self._on_drop = on_drop
            self.setAcceptDrops(True)

        def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
            if is_drop_supported(event.mimeData()):
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                super().dragEnterEvent(event)

        def dragMoveEvent(self, event) -> None:  # noqa: N802
            if is_drop_supported(event.mimeData()):
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                super().dragMoveEvent(event)

        def dropEvent(self, event) -> None:  # noqa: N802
            if is_drop_supported(event.mimeData()):
                event.setDropAction(Qt.CopyAction)
                event.accept()
                self._on_drop(event.mimeData())
            else:
                super().dropEvent(event)

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

        def __init__(
            self,
            options: ConvertOptions,
            lines: list[str],
            signals: WorkerSignals,
            indices: list[int] | None = None,
        ):
            self.processor = BatchProcessor(options)
            self.lines = lines
            self.indices = indices
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
                    self.processor.run(self.lines, indices=self.indices)
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
            self.setAcceptDrops(True)
            self.worker: Worker | None = None
            self.last_options: ConvertOptions | None = None
            self.result_rows: dict[int, int] = {}
            self.last_results: dict[int, object] = {}
            self._retrying = False

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

            self.links_edit = DropTextEdit(self.handle_drop)
            self.links_edit.setPlaceholderText(
                "粘贴分享链接或口令（每行一条），也可把视频文件 / 文件夹拖进来\n"
                "例：https://v.douyin.com/xxxxxxx/\n"
                "https://v.kuaishou.com/xxxxxx\n"
                "https://www.kugou.com/mixsong/xxxxxx.html\n"
                "https://www.bilibili.com/video/BVxxxx"
            )
            self.links_edit.setFixedHeight(150)
            body.addWidget(self.links_edit)

            # 链接区下方：常驻按钮行（添加文件 / 文件夹 / 清空）
            file_row = QHBoxLayout()
            file_row.setSpacing(10)
            add_file_btn = QPushButton("添加本地文件…")
            add_file_btn.setProperty("secondary", True)
            add_file_btn.setMinimumWidth(126)
            add_file_btn.clicked.connect(self.pick_local_files)
            add_dir_btn = QPushButton("添加文件夹…")
            add_dir_btn.setProperty("secondary", True)
            add_dir_btn.setMinimumWidth(112)
            add_dir_btn.clicked.connect(self.pick_local_folder)
            clear_btn = QPushButton("清空")
            clear_btn.setProperty("secondary", True)
            clear_btn.setMinimumWidth(72)
            clear_btn.clicked.connect(self.clear_links)
            file_row.addWidget(add_file_btn)
            file_row.addWidget(add_dir_btn)
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
            self._add_setting(10, "转换报告", self._make_report_row())
            self._refresh_quality_tip()
            self._refresh_format_tip()
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

            # ── 任务结果（支持单条右键重试 / 打开）─────────────────
            self.results_page = QWidget()
            results_layout = QVBoxLayout(self.results_page)
            results_layout.setContentsMargins(8, 8, 8, 8)
            results_layout.setSpacing(8)
            toolbar = QHBoxLayout()
            toolbar.setContentsMargins(0, 0, 0, 0)
            self.retry_failed_btn = QPushButton("重试全部失败项")
            self.retry_failed_btn.setProperty("secondary", True)
            self.retry_failed_btn.setEnabled(False)
            self.retry_failed_btn.clicked.connect(self.retry_all_failed)
            self.open_dir_btn = QPushButton("打开输出目录")
            self.open_dir_btn.setProperty("secondary", True)
            self.open_dir_btn.clicked.connect(
                lambda: self._open_path(Path(self.dir_edit.text()).expanduser())
            )
            self.results_summary = QLabel("暂无任务")
            self.results_summary.setStyleSheet("color: #6b7280;")
            toolbar.addWidget(self.retry_failed_btn)
            toolbar.addWidget(self.open_dir_btn)
            toolbar.addStretch(1)
            toolbar.addWidget(self.results_summary)
            results_layout.addLayout(toolbar)

            self.results_table = QTableWidget(0, 7)
            self.results_table.setHorizontalHeaderLabels(
                ["序号", "状态", "标题", "歌手", "时长", "大小", "输出文件"]
            )
            self.results_table.verticalHeader().setVisible(False)
            self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.results_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.results_table.customContextMenuRequested.connect(self._show_results_menu)
            self.results_table.cellDoubleClicked.connect(self._open_result_row)
            header = self.results_table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            header.setSectionResizeMode(6, QHeaderView.Stretch)
            results_layout.addWidget(self.results_table)
            self.tabs.addTab(self.results_page, "任务结果")

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

            # 除输入框外，关掉所有子控件的拖放接收：
            # QLineEdit / QPlainTextEdit 默认 acceptDrops=True，会把拖放截胡，
            # 导致「拖标签页进程序没反应」。关掉后由主窗口统一接管。
            disable_child_drops(self, keep=(self.links_edit,))

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
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            self.quality_box = QComboBox()
            self.quality_box.addItem("自定义（在右侧输入）", "")
            for preset in QUALITY_PRESETS.values():
                self.quality_box.addItem(preset.label, preset.key)
            self.quality_box.setCurrentIndex(self.quality_box.findData(DEFAULT_QUALITY))
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
            v.addLayout(h)
            self.quality_tip = QLabel()
            self.quality_tip.setStyleSheet("color: #6b7280;")
            self.quality_tip.setWordWrap(True)
            v.addWidget(self.quality_tip)
            return w

        def _on_preset_changed(self) -> None:
            """选择预设时清空自定义码率，并刷新说明。"""
            if self.quality_box.currentData():
                self.custom_quality.setValue(0)
            self._refresh_quality_tip()

        def _on_custom_quality_changed(self, value: int) -> None:
            """填写自定义码率时，下拉框切换到「自定义」项。"""
            if value > 0 and self.quality_box.currentIndex() != 0:
                self.quality_box.blockSignals(True)
                self.quality_box.setCurrentIndex(0)
                self.quality_box.blockSignals(False)
            self._refresh_quality_tip()

        def _refresh_quality_tip(self) -> None:
            spec = OUTPUT_FORMATS.get(self.format_box.currentData() or "mp3")
            if spec is not None and spec.is_copy:
                self.quality_tip.setText("BEST 模式直接复制源音轨，音质设置自动忽略。")
                self.quality_box.setEnabled(False)
                self.custom_quality.setEnabled(False)
                return
            self.quality_box.setEnabled(True)
            self.custom_quality.setEnabled(not (spec and spec.lossless))
            if spec is not None and spec.lossless:
                self.quality_tip.setText(f"{spec.label.split('（')[0]} 为无损格式，码率设置自动忽略。")
                return
            custom = self.custom_quality.value()
            if custom > 0:
                self.quality_tip.setText(f"自定义 {custom} kbps CBR；V0 仅 MP3 有效。")
                return
            key = self.quality_box.currentData()
            if not key:
                self.quality_tip.setText("在右侧填写 32~320 kbps 自定义固定码率。")
                return
            preset = QUALITY_PRESETS.get(key)
            self.quality_tip.setText(preset.note if preset is not None else "")

        def _make_format_row(self) -> QWidget:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            self.format_box = QComboBox()
            for key, spec in OUTPUT_FORMATS.items():
                suffix = "" if spec.is_copy else f"  ·  .{spec.ext}"
                self.format_box.addItem(f"{spec.label}{suffix}", key)
            self.format_box.setToolTip(
                "MP3 兼容性最好、车机首选；M4A 适合 Apple 生态；"
                "FLAC/WAV 无损；Opus 压缩率最高；BEST 不转码、速度最快"
            )
            self.format_box.currentIndexChanged.connect(self._refresh_quality_tip)
            v.addWidget(self.format_box)
            self.format_tip = QLabel()
            self.format_tip.setStyleSheet("color: #6b7280;")
            self.format_tip.setWordWrap(True)
            v.addWidget(self.format_tip)
            self.format_box.currentIndexChanged.connect(self._refresh_format_tip)
            return w

        def _refresh_format_tip(self) -> None:
            spec = OUTPUT_FORMATS.get(self.format_box.currentData() or "mp3")
            self.format_tip.setText(spec.note if spec is not None else "")

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

        def _make_report_row(self) -> QWidget:
            self.report_box = QComboBox()
            for key in REPORT_MODES:
                self.report_box.addItem(REPORT_MODE_LABELS[key], key)
            self.report_box.setCurrentIndex(self.report_box.findData("overwrite"))
            self.report_box.setToolTip(
                "转换报告 CSV 的保存方式。默认覆盖同名文件，输出目录里最多留一份，"
                "不会越用越多；需要保留历史可改为「每次新建」。"
            )
            return self.report_box

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
            self.reset_components_btn = QPushButton("恢复内置组件")
            self.reset_components_btn.setProperty("secondary", True)
            self.reset_components_btn.setFixedWidth(104)
            self.reset_components_btn.setToolTip(
                "删除已下载的外置 yt-dlp / ffmpeg，回到程序内置的版本。\n"
                "换了新版程序、或外置组件装坏时可以用。"
            )
            self.reset_components_btn.clicked.connect(self.reset_components)
            h.addWidget(self.reset_components_btn, 0)
            self.check_now_btn = QPushButton("立即检查")
            self.check_now_btn.setProperty("secondary", True)
            self.check_now_btn.setFixedWidth(88)
            self.check_now_btn.clicked.connect(lambda: self.start_update_check(manual=True))
            h.addWidget(self.check_now_btn, 0)
            return w

        def reset_components(self) -> None:
            """清除外置组件，恢复打包内置的版本。"""
            confirm = QMessageBox.question(
                self,
                APP_NAME,
                "确定要删除已下载的外置 yt-dlp / ffmpeg 吗？\n\n"
                "删除后程序会回到内置版本（功能不受影响），"
                "下次自检会重新提示升级。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            removed = updater.reset_components()
            self.append_log(
                "已清除外置组件：" + ("、".join(removed) if removed else "（没有可清除的）")
            )
            QMessageBox.information(
                self,
                APP_NAME,
                "已恢复为程序内置的 yt-dlp / ffmpeg。"
                + ("\n\n重启程序后完全生效。" if removed else ""),
            )

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
            if paths:
                self._append_entries([], [Path(p) for p in paths])

        def pick_local_folder(self) -> None:
            chosen = QFileDialog.getExistingDirectory(
                self, "选择包含视频 / 音频的文件夹（会递归扫描）", ""
            )
            if chosen:
                self._append_entries([], [Path(chosen)])

        def handle_drop(self, mime) -> None:
            """处理拖入的链接 / 文件 / 文件夹。

            浏览器标签页拖放暂时关闭（见 ``dragdrop.ALLOW_LINK_DROP``），
            遇到链接会提示用户复制网址后粘贴。
            """
            payload = parse_drop_data(mime)
            if payload.empty:
                self.hint_label.setText("未能识别到链接或文件（可先复制网址再粘贴）")
                return
            links, paths, ignored_links = split_drop_payload(payload)
            if ignored_links:
                if paths:
                    self._append_entries(links, paths)
                self.hint_label.setText(LINK_DROP_DISABLED_HINT)
                return
            self._append_entries(links, paths)

        def _append_entries(self, links: list[str], paths: list[Path]) -> None:
            """把链接与本地路径追加到输入框，按 URL / 绝对路径去重。"""
            current = self._current_lines()
            url_keys = {url for line in current for url in extract_urls(line)}
            path_keys: set[str] = set()
            for line in current:
                if extract_urls(line):
                    continue
                candidate = line.strip().strip('"').strip("'")
                if candidate:
                    path_keys.add(os.path.normcase(os.path.abspath(candidate)))

            added_links = 0
            for url in links:
                if url in url_keys:
                    continue
                current.append(url)
                url_keys.add(url)
                added_links += 1

            media, truncated = collect_media_paths(paths) if paths else ([], False)
            added_files = 0
            for path in media:
                key = os.path.normcase(os.path.abspath(str(path)))
                if key in path_keys:
                    continue
                current.append(str(path))
                path_keys.add(key)
                added_files += 1

            if not added_links and not added_files:
                if paths and not media:
                    self.hint_label.setText("未找到支持的音视频文件")
                else:
                    self.hint_label.setText("没有识别到新内容（可能已在列表中）")
                return

            self.links_edit.setPlainText("\n".join(current))
            parts: list[str] = []
            if added_links:
                parts.append(f"{added_links} 条链接")
            if added_files:
                parts.append(f"{added_files} 个本地文件")
            hint = "已添加 " + "、".join(parts)
            if truncated:
                hint += f"（文件夹内文件过多，仅取前 {DEFAULT_LIMIT} 个）"
            self.hint_label.setText(hint)

        def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
            if is_drop_supported(event.mimeData()):
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                super().dragEnterEvent(event)

        def dragMoveEvent(self, event) -> None:  # noqa: N802
            if is_drop_supported(event.mimeData()):
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                super().dragMoveEvent(event)

        def dropEvent(self, event) -> None:  # noqa: N802
            if is_drop_supported(event.mimeData()):
                event.setDropAction(Qt.CopyAction)
                event.accept()
                self.handle_drop(event.mimeData())
            else:
                super().dropEvent(event)

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
                quality = self.quality_box.currentData() or DEFAULT_QUALITY
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
                report_mode=self.report_box.currentData() or "overwrite",
            )
            self.last_options = options
            self._reset_results()
            self._launch(options, lines, None, retry=False)

        def _launch(
            self,
            options: ConvertOptions,
            lines: list[str],
            indices: list[int] | None,
            *,
            retry: bool,
        ) -> None:
            """启动后台转换（首次运行与失败重试共用）。"""
            self._retrying = retry
            self.worker_signals = WorkerSignals(self)
            self.worker = Worker(options, lines, self.worker_signals, indices)
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
            self.hint_label.setText(
                f"正在重试 {len(lines)} 条…" if retry else f"正在转换 {len(lines)} 条…"
            )
            self.retry_failed_btn.setEnabled(False)
            self.worker.start()

        def _on_item_start(self, index: int, total: int, _url: str) -> None:
            self.progress.setRange(0, total)
            self.progress.setFormat(f"第 {index} 条 · %p%")

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
            completed = min(self.progress.value() + 1, self.progress.maximum())
            self.progress.setValue(completed)
            self._upsert_result(result)

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
            self.worker = None
            self._refresh_results_summary()
            if self._retrying:
                QMessageBox.information(
                    self, APP_NAME, f"重试完成\n成功：{ok}\n失败：{fail}"
                )
            else:
                QMessageBox.information(self, APP_NAME, f"转换完成\n成功：{ok}\n失败：{fail}")
            self._retrying = False

        # ── 任务结果表 ─────────────────────────────────────────
        def _reset_results(self) -> None:
            self.results_table.setRowCount(0)
            self.result_rows.clear()
            self.last_results.clear()
            self.retry_failed_btn.setEnabled(False)
            self.results_summary.setText("暂无任务")

        def _upsert_result(self, result: object) -> None:
            index = int(getattr(result, "index", 0))
            self.last_results[index] = result
            row = self.result_rows.get(index)
            if row is None:
                row = self.results_table.rowCount()
                self.results_table.insertRow(row)
                self.result_rows[index] = row
            status = getattr(result, "status", "")
            status_text = {"ok": "成功", "failed": "失败", "skipped": "跳过"}.get(
                status, status or "未知"
            )
            duration = float(getattr(result, "duration", 0) or 0)
            size = int(getattr(result, "size", 0) or 0)
            output = str(getattr(result, "output_path", "") or "")
            message = str(getattr(result, "message", "") or "")
            cells = [
                str(index),
                status_text,
                str(getattr(result, "title", "") or ""),
                str(getattr(result, "artist", "") or ""),
                f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "",
                f"{size / 1024 / 1024:.1f} MB" if size else "",
                output or message,
            ]
            from PySide6.QtGui import QColor

            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 6:
                    item.setToolTip(output or message)
                if status == "failed":
                    item.setToolTip(message)
                    item.setForeground(QColor("#b91c1c"))
                elif status == "skipped":
                    item.setForeground(QColor("#6b7280"))
                self.results_table.setItem(row, col, item)
            self._refresh_results_summary()

        def _refresh_results_summary(self) -> None:
            results = list(self.last_results.values())
            failed = [r for r in results if getattr(r, "status", "") == "failed"]
            ok = len([r for r in results if getattr(r, "status", "") == "ok"])
            self.retry_failed_btn.setEnabled(bool(failed) and not self._busy())
            if not results:
                self.results_summary.setText("暂无任务")
            else:
                self.results_summary.setText(
                    f"共 {len(results)} 条 · 成功 {ok} · 失败 {len(failed)}"
                )

        def _busy(self) -> bool:
            return bool(self.worker and self.worker.isRunning())

        def _open_path(self, path: Path) -> None:
            if not path.exists():
                QMessageBox.warning(self, APP_NAME, f"路径不存在：{path}")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

        def _result_at_row(self, row: int) -> object | None:
            for index, row_index in self.result_rows.items():
                if row_index == row:
                    return self.last_results.get(index)
            return None

        def _open_result_row(self, row: int, _col: int) -> None:
            result = self._result_at_row(row)
            output = str(getattr(result, "output_path", "") or "") if result else ""
            if output and Path(output).exists():
                self._open_path(Path(output))

        def _show_results_menu(self, pos) -> None:  # noqa: ANN001
            item = self.results_table.itemAt(pos)
            menu = QMenu(self)
            result = self._result_at_row(item.row()) if item is not None else None
            if result is not None:
                output = str(getattr(result, "output_path", "") or "")
                if output and Path(output).exists():
                    menu.addAction("打开文件", lambda: self._open_path(Path(output)))
                    menu.addAction(
                        "打开所在文件夹", lambda: self._open_path(Path(output).parent)
                    )
                source = str(getattr(result, "source", "") or "")
                if source:
                    menu.addAction(
                        "复制来源地址",
                        lambda: QApplication.clipboard().setText(source),
                    )
                if getattr(result, "status", "") == "failed":
                    menu.addAction("重试此任务", lambda: self._start_retry([result]))
                menu.addSeparator()
            failed = [
                r for r in self.last_results.values() if getattr(r, "status", "") == "failed"
            ]
            retry_all = menu.addAction(f"重试全部失败项（{len(failed)}）")
            retry_all.setEnabled(bool(failed) and not self._busy())
            retry_all.triggered.connect(self.retry_all_failed)
            menu.exec(self.results_table.viewport().mapToGlobal(pos))

        def retry_all_failed(self) -> None:
            failed = [
                r for r in self.last_results.values() if getattr(r, "status", "") == "failed"
            ]
            self._start_retry(failed)

        def _start_retry(self, results: list) -> None:
            if not results or self._busy():
                return
            if self.last_options is None:
                QMessageBox.warning(self, APP_NAME, "请先执行一次转换，再重试失败项。")
                return
            lines = [str(getattr(r, "source", "")) for r in results]
            indices = [int(getattr(r, "index", 0)) for r in results]
            pairs = [(line, idx) for line, idx in zip(lines, indices) if line]
            if not pairs:
                return
            lines = [line for line, _ in pairs]
            indices = [idx for _, idx in pairs]
            self.tabs.setCurrentWidget(self.log_page)
            self.append_log(f"开始重试 {len(lines)} 条失败任务…")
            self._launch(self.last_options, lines, indices, retry=True)

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
