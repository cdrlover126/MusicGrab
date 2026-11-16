"""组件版本判定回归测试。

回归的用户问题：打包分发后**每次启动都提示「有更新」，明明已经升级过了**。

根因：ffmpeg 组件升级时只把二进制装进覆盖层，并不替换 ``imageio-ffmpeg`` 包，
于是包版本永远停在「打包时内置」的那个（0.6.0），拿它跟 PyPI 最新版（0.7.0）比
永远是「有更新」。正确做法是以**升级时记录的版本**为准。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from musicgrab import updater
from musicgrab.updater import (
    FFMPEG,
    YTDLP,
    ComponentStatus,
    RemotePackage,
)


@pytest.fixture(autouse=True)
def isolated_overlay(tmp_path, monkeypatch):
    """把覆盖层指到临时目录，避免污染真实环境。"""
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "MusicGrab")
    yield tmp_path / "MusicGrab"


def _write_state(overlay: Path, installed: dict) -> None:
    updater.save_state({"installed": installed})


def test_installed_version_is_read_from_state(isolated_overlay):
    _write_state(isolated_overlay, {FFMPEG: "0.7.0", YTDLP: "2026.10.26"})
    assert updater.installed_component_version(FFMPEG) == "0.7.0"
    assert updater.installed_component_version(YTDLP) == "2026.10.26"
    assert updater.installed_component_version("nope") == ""


def test_ffmpeg_version_uses_recorded_version_when_overlay_present(
    isolated_overlay, monkeypatch
):
    """覆盖层有外置 ffmpeg 时，版本号取「升级时记录的」，不是打包内置的。"""
    ffmpeg_dir = isolated_overlay / "ffmpeg"
    ffmpeg_dir.mkdir(parents=True)
    (ffmpeg_dir / "ffmpeg-win-x86_64-v7.1.exe").write_bytes(b"x")
    _write_state(isolated_overlay, {FFMPEG: "0.7.0"})

    # 打包内置的包版本故意设成旧的
    monkeypatch.setattr(
        updater, "_read_module_version", lambda package_dir: "0.6.0"
    )

    assert updater.current_imageio_ffmpeg_version() == "0.7.0"


def test_ffmpeg_version_falls_back_to_bundled_without_record(
    isolated_overlay, monkeypatch
):
    """没有记录、也没有外置 ffmpeg 时，用打包内置的包版本（该提示更新）。"""
    monkeypatch.setattr(
        updater, "_read_module_version", lambda package_dir: "0.6.0"
    )
    assert updater.current_imageio_ffmpeg_version() == "0.6.0"


def test_ffmpeg_version_falls_back_when_overlay_removed(
    isolated_overlay, monkeypatch
):
    """外置 ffmpeg 被删掉后，不能再用记录的版本号（那会漏报更新）。"""
    _write_state(isolated_overlay, {FFMPEG: "0.7.0"})
    monkeypatch.setattr(
        updater, "_read_module_version", lambda package_dir: "0.6.0"
    )
    assert updater.current_imageio_ffmpeg_version() == "0.6.0"


def test_ytdlp_version_prefers_overlay(isolated_overlay):
    overlay = isolated_overlay / "yt_dlp"
    overlay.mkdir(parents=True)
    (overlay / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (overlay / "version.py").write_text("__version__ = '2026.10.26'\n", encoding="utf-8")

    assert updater.current_ytdlp_version() == "2026.10.26"


def test_ytdlp_version_falls_back_to_record_when_overlay_broken(
    isolated_overlay, monkeypatch
):
    """覆盖层里读不到版本号时，退回升级时记录的版本。"""
    overlay = isolated_overlay / "yt_dlp"
    overlay.mkdir(parents=True)
    (overlay / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    _write_state(isolated_overlay, {YTDLP: "2026.10.26"})

    monkeypatch.setattr(updater, "_read_module_version", lambda package_dir: "")
    assert updater.current_ytdlp_version() == "2026.10.26"


def test_check_ffmpeg_reports_no_update_after_upgrade(isolated_overlay, monkeypatch):
    """回归：已升级到最新版时不应再提示「有更新」。"""
    ffmpeg_dir = isolated_overlay / "ffmpeg"
    ffmpeg_dir.mkdir(parents=True)
    (ffmpeg_dir / "ffmpeg-win-x86_64-v7.1.exe").write_bytes(b"x")
    _write_state(isolated_overlay, {FFMPEG: "0.7.0"})

    monkeypatch.setattr(
        updater,
        "_read_module_version",
        lambda package_dir: "0.6.0",  # 打包内置的旧版本
    )
    monkeypatch.setattr(
        updater,
        "fetch_remote_package",
        lambda package: RemotePackage(
            package=package,
            version="0.7.0",
            url="https://example.invalid/x.whl",
            sha256="",
            size=0,
            source="test",
        ),
    )
    monkeypatch.setattr(updater, "current_ffmpeg_version", lambda: "7.1")

    status = updater.check_ffmpeg()
    assert status.current == "0.7.0"
    assert status.latest == "0.7.0"
    assert status.has_update is False


def test_check_ffmpeg_reports_update_when_bundled_is_old(isolated_overlay, monkeypatch):
    """没升级过时仍应正常提示更新。"""
    monkeypatch.setattr(
        updater,
        "_read_module_version",
        lambda package_dir: "0.6.0",
    )
    monkeypatch.setattr(
        updater,
        "fetch_remote_package",
        lambda package: RemotePackage(
            package=package,
            version="0.7.0",
            url="https://example.invalid/x.whl",
            sha256="",
            size=0,
            source="test",
        ),
    )
    monkeypatch.setattr(updater, "current_ffmpeg_version", lambda: "7.1")

    status = updater.check_ffmpeg()
    assert status.has_update is True
    assert status.current == "0.6.0"


def test_stale_ignore_is_pruned_when_up_to_date(isolated_overlay, monkeypatch):
    """组件已是最新时，之前「忽略此版本」的记录应当清掉。"""
    updater.save_state({"ignored": {FFMPEG: "0.7.0"}, "installed": {}})

    def fake_check(key):
        return ComponentStatus(key, key, "0.7.0", "0.7.0", False)

    monkeypatch.setattr(updater, "check_ytdlp", lambda: fake_check(YTDLP))
    monkeypatch.setattr(updater, "check_ffmpeg", lambda: fake_check(FFMPEG))

    updater.check_components()
    assert FFMPEG not in updater.load_state().get("ignored", {})


def test_ignore_record_kept_on_network_error(isolated_overlay, monkeypatch):
    """网络异常时不能清理忽略记录，否则恢复网络后又会弹提示。"""
    updater.save_state({"ignored": {FFMPEG: "0.7.0"}, "installed": {}})

    def fake_check(key):
        return ComponentStatus(key, key, "0.6.0", "", False, error="网络不通")

    monkeypatch.setattr(updater, "check_ytdlp", lambda: fake_check(YTDLP))
    monkeypatch.setattr(updater, "check_ffmpeg", lambda: fake_check(FFMPEG))

    updater.check_components()
    assert updater.load_state().get("ignored", {}).get(FFMPEG) == "0.7.0"
