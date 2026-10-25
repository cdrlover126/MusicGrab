from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_locking_settings_page_keeps_tabs_clickable(app):
    """回归：处理期间只锁「输出设置」页内容，页签本身保持可点击。

    参见问题：处理中点击「详情日志」无效，必须等处理结束才能切换。
    """
    from PySide6.QtWidgets import QTabWidget, QWidget

    tabs = QTabWidget()
    settings_page = QWidget()
    log_page = QWidget()
    tabs.addTab(settings_page, "输出设置")
    tabs.addTab(log_page, "详情日志")

    settings_page.setEnabled(False)
    assert tabs.isEnabled() is True
    assert tabs.isTabEnabled(1) is True
    tabs.setCurrentIndex(1)
    assert tabs.currentIndex() == 1

    settings_page.setEnabled(True)
    assert tabs.isEnabled() is True


def test_gui_source_does_not_disable_whole_tab_widget():
    """回归：源码中不得出现 `self.tabs.setEnabled(False)`（会禁用页签点击）。"""
    import inspect

    import douyin_mp3.gui as gui_mod

    src = inspect.getsource(gui_mod)
    assert "self.tabs.setEnabled(False)" not in src
    assert "self.settings_page.setEnabled(False)" in src
