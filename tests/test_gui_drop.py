"""GUI 拖放相关回归测试。

核心回归点：``QLineEdit`` / ``QPlainTextEdit`` / ``QTextEdit`` 默认
``acceptDrops=True``，而 Qt 的 ``findDnDTarget()`` 会把拖放交给
「从光标处向上第一个 acceptDrops 的控件」——日志框、输出目录输入框会把拖放
截胡，主窗口收不到，表现为「拖浏览器标签页进程序没反应」。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_line_edit_and_plain_text_edit_accept_drops_by_default(app):
    """前提：这两个控件默认会抢走拖放事件（Qt 的既有行为）。"""
    assert QLineEdit().acceptDrops() is True
    assert QPlainTextEdit().acceptDrops() is True


def test_disable_child_drops_turns_off_children(app):
    from musicgrab.gui import disable_child_drops

    window = QWidget()
    layout = QVBoxLayout(window)
    keep = QPlainTextEdit()
    layout.addWidget(keep)
    layout.addWidget(QLineEdit())
    layout.addWidget(QPlainTextEdit())

    changed = disable_child_drops(window, keep=(keep,))

    assert changed >= 2
    assert keep.acceptDrops() is True
    for widget in window.findChildren(QWidget):
        if widget is keep:
            continue
        assert widget.acceptDrops() is False


def test_disable_child_drops_is_idempotent(app):
    from musicgrab.gui import disable_child_drops

    window = QWidget()
    layout = QVBoxLayout(window)
    layout.addWidget(QLineEdit())

    assert disable_child_drops(window) == 1
    assert disable_child_drops(window) == 0


def test_gui_source_calls_disable_child_drops():
    """回归：主窗口初始化时必须调用 disable_child_drops。"""
    import inspect

    import musicgrab.gui as gui_mod

    src = inspect.getsource(gui_mod)
    assert "disable_child_drops(self, keep=(self.links_edit,))" in src


def test_gui_source_has_no_app_level_drop_filter():
    """回归：不要再用应用层事件过滤器接拖放。

    Qt 的 ``QGuiApplication::forwardEvent()`` 直接调用控件的 ``event()``，
    **不会**经过应用层事件过滤器，所以那种写法对真实拖放无效。
    """
    import inspect

    import musicgrab.gui as gui_mod

    src = inspect.getsource(gui_mod)
    assert "installEventFilter" not in src
    assert "DropWatcher" not in src
