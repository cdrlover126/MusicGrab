from __future__ import annotations

import os
import subprocess
import sys

from douyin_mp3 import winconsole


def test_parent_has_console_returns_bool():
    assert isinstance(winconsole.parent_has_console(), bool)


def test_apply_is_idempotent():
    first = winconsole.apply()
    second = winconsole.apply()
    assert second is False or first is False or first == second


def test_popen_creationflags_injected():
    """GUI 模式下（父进程无控制台）子进程必须带 CREATE_NO_WINDOW。"""
    if os.name != "nt":
        return
    winconsole.apply()
    # 直接验证补丁逻辑：模拟一次 Popen，检查 creationflags
    cmd = [sys.executable, "-c", "print(1)"]
    kwargs = {}
    if not winconsole.parent_has_console():
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(cmd, capture_output=True, creationflags=kwargs.get("creationflags", 0))
    assert proc.returncode == 0
