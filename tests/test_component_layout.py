"""组件目录布局与状态自描述测试。

回归的用户问题：单文件应用分发后，组件更新状态容易丢——

* ``state.json`` 被清理工具删掉 → 又开始提示「有更新」
* exe 拷到别的机器 → 外置组件没跟过去

方案：**状态自描述**（版本标记跟组件走）+ **多位置组件目录**（便携 + 机器级）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from douyin_mp3 import updater
from douyin_mp3.updater import FFMPEG, FFMPEG_VERSION_FILE, YTDLP


@pytest.fixture
def fake_exe_dir(tmp_path, monkeypatch):
    """假装程序跑在某个目录下的 exe 里（启用便携目录逻辑）。"""
    exe_dir = tmp_path / "Program"
    exe_dir.mkdir()
    monkeypatch.setattr(updater, "executable_dir", lambda: exe_dir)
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "AppData" / "MusicGrab")
    return exe_dir


def test_component_roots_contains_machine_level(fake_exe_dir):
    roots = updater.component_roots()
    assert fake_exe_dir / updater.PORTABLE_DIR_NAME not in roots
    assert roots[-1].name == "MusicGrab"


def test_portable_dir_wins_when_present(fake_exe_dir):
    portable = fake_exe_dir / updater.PORTABLE_DIR_NAME
    portable.mkdir()

    roots = updater.component_roots()
    assert roots[0] == portable
    assert roots[-1].name == "MusicGrab"


def test_install_root_prefers_portable_dir(fake_exe_dir):
    assert updater.install_root() == fake_exe_dir / updater.PORTABLE_DIR_NAME


def test_install_root_falls_back_when_exe_dir_readonly(fake_exe_dir, monkeypatch):
    """exe 所在目录不可写（如 Program Files）时，装到机器级目录。"""
    monkeypatch.setattr(updater, "_dir_writable", lambda path: False)
    root = updater.install_root()
    assert root.name == "MusicGrab"
    assert root.parent.name == "AppData"


def test_components_are_found_in_portable_dir(fake_exe_dir):
    portable = fake_exe_dir / updater.PORTABLE_DIR_NAME
    (portable / "yt_dlp").mkdir(parents=True)
    (portable / "yt_dlp" / "__init__.py").write_text("x = 1\n", encoding="utf-8")

    assert updater.ytdlp_overlay_dir() == portable / "yt_dlp"
    # 覆盖层里没有 version.py → 退回打包内置的版本，而不是空串
    version = updater.current_ytdlp_version()
    assert version
    assert version != "OVERLAY"


def test_ffmpeg_version_marker_is_self_describing(fake_exe_dir):
    """版本标记跟二进制放在一起：不依赖 state.json。"""
    portable = fake_exe_dir / updater.PORTABLE_DIR_NAME
    ffmpeg_dir = portable / "ffmpeg"
    ffmpeg_dir.mkdir(parents=True)
    (ffmpeg_dir / "ffmpeg-win-x86_64-v7.1.exe").write_bytes(b"x")
    updater.write_ffmpeg_version_marker("0.7.0", ffmpeg_dir)

    # state.json 是空的（被清理过），但版本仍然读得出来
    assert updater.ffmpeg_version_marker() == "0.7.0"
    assert updater.current_imageio_ffmpeg_version() == "0.7.0"


def test_version_marker_survives_state_loss(fake_exe_dir):
    """状态文件丢失后，版本判定依然正确（不会重复提示更新）。"""
    portable = fake_exe_dir / updater.PORTABLE_DIR_NAME
    ffmpeg_dir = portable / "ffmpeg"
    ffmpeg_dir.mkdir(parents=True)
    (ffmpeg_dir / "ffmpeg-win-x86_64-v7.1.exe").write_bytes(b"x")
    updater.write_ffmpeg_version_marker("0.7.0", ffmpeg_dir)

    # 模拟 state.json 丢失
    updater.save_state({"installed": {FFMPEG: "0.7.0"}})
    updater.state_path().unlink()

    assert updater.current_imageio_ffmpeg_version() == "0.7.0"


def test_reset_components_removes_external_installs(fake_exe_dir):
    portable = fake_exe_dir / updater.PORTABLE_DIR_NAME
    (portable / "yt_dlp").mkdir(parents=True)
    (portable / "yt_dlp" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (portable / "ffmpeg").mkdir(parents=True)
    (portable / "ffmpeg" / "ffmpeg-win-x86_64-v7.1.exe").write_bytes(b"x")
    machine = updater.overlay_root()
    (machine / "yt_dlp").mkdir(parents=True)
    (machine / "yt_dlp" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    updater.save_state({"installed": {FFMPEG: "0.7.0", YTDLP: "2026.10.26"}})

    removed = updater.reset_components()

    assert len(removed) == 3
    assert not (portable / "yt_dlp").exists()
    assert not (portable / "ffmpeg").exists()
    assert not (machine / "yt_dlp").exists()
    # 状态里的「已安装版本」也要清掉，否则会以为组件还是新的
    assert updater.load_state().get("installed") == {}


def test_reset_components_is_safe_when_nothing_installed(fake_exe_dir):
    assert updater.reset_components() == []
