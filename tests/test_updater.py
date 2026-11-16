"""组件自检与升级模块的单元测试。"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

from musicgrab import updater


# ── 版本比较 ────────────────────────────────────────────────
def test_version_tuple_parses_date_like_versions():
    assert updater.version_tuple("2026.10.26") == (2026, 10, 26)
    assert updater.version_tuple("2026.8.19") == (2026, 8, 19)
    assert updater.version_tuple("0.6.0") == (0, 6, 0)
    assert updater.version_tuple("") == (0,)


def test_is_newer_uses_numeric_comparison():
    """字符串比较会在这里出错：'2026.10.26' < '2026.08.19' 是 False，
    但 '2026.10.26' > '2026.08.19' 才是正确结论（按数字元组比较）。"""
    assert updater.is_newer("2026.10.26", "2026.08.19") is True
    assert updater.is_newer("2026.08.19", "2026.10.26") is False
    assert updater.is_newer("2026.10.26", "2026.10.26") is False
    assert updater.is_newer("0.6.0", "0.6.0") is False
    assert updater.is_newer("0.7.0", "0.6.0") is True


def test_is_newer_handles_empty_current():
    assert updater.is_newer("2026.10.26", "") is True
    assert updater.is_newer("", "2026.10.26") is False


def test_is_stable_version_rejects_prereleases():
    assert updater.is_stable_version("2026.10.26") is True
    assert updater.is_stable_version("0.6.0") is True
    assert updater.is_stable_version("2026.9.27.232945.dev0") is False
    assert updater.is_stable_version("2026.10.26rc1") is False
    assert updater.is_stable_version("") is False


# ── 简单索引解析 ────────────────────────────────────────────
SAMPLE_INDEX = """
<a href="../../packages/aa/yt_dlp-2026.8.19-py3-none-any.whl#sha256=aaa">yt_dlp-2026.8.19-py3-none-any.whl</a>
<a href="../../packages/bb/yt_dlp-2026.10.26-py3-none-any.whl#sha256=bbb">yt_dlp-2026.10.26-py3-none-any.whl</a>
<a href="../../packages/cc/yt_dlp-2026.9.27.232945.dev0-py3-none-any.whl">yt_dlp-2026.9.27.232945.dev0-py3-none-any.whl</a>
"""


def test_parse_simple_index_picks_newest_stable():
    remote = updater._parse_simple_index(
        SAMPLE_INDEX, "yt-dlp", "https://example.com/simple/yt-dlp/"
    )
    assert remote is not None
    # 索引不是按版本排序的，且含 dev 版本，必须按数字元组取最大稳定版
    assert remote.version == "2026.10.26"
    assert remote.url == "https://example.com/packages/bb/yt_dlp-2026.10.26-py3-none-any.whl"
    assert remote.sha256 == "bbb"
    assert remote.source == "example.com"


def test_parse_simple_index_returns_none_without_stable():
    html = '<a href="x">yt_dlp-2026.9.1.dev0-py3-none-any.whl</a>'
    assert updater._parse_simple_index(html, "yt-dlp", "https://example.com/simple/yt-dlp/") is None


def test_parse_simple_index_ignores_other_packages():
    html = '<a href="x">other_pkg-9.9.9-py3-none-any.whl</a>'
    assert updater._parse_simple_index(html, "yt-dlp", "https://example.com/simple/yt-dlp/") is None


# ── 状态持久化 ──────────────────────────────────────────────
@pytest.fixture()
def overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "MusicGrab")
    return tmp_path / "MusicGrab"


def test_state_roundtrip(overlay):
    assert updater.load_state()["auto_check"] is True
    updater.save_state({"auto_check": False, "ignored": {}, "installed": {}})
    assert updater.load_state()["auto_check"] is False


def test_load_state_tolerates_corrupt_file(overlay):
    overlay.mkdir(parents=True, exist_ok=True)
    updater.state_path().write_text("{ not json", encoding="utf-8")
    state = updater.load_state()
    assert state["auto_check"] is True
    assert state["ignored"] == {}


def test_ignore_version_suppresses_prompt(overlay):
    assert updater.is_ignored("yt-dlp", "2026.10.26") is False
    updater.ignore_version("yt-dlp", "2026.10.26")
    assert updater.is_ignored("yt-dlp", "2026.10.26") is True
    assert updater.is_ignored("yt-dlp", "2026.8.19") is False


# ── 压缩包安全 ──────────────────────────────────────────────
def test_safe_target_blocks_path_traversal(tmp_path):
    root = tmp_path / "dest"
    root.mkdir()
    with pytest.raises(updater.UpdateError):
        updater._safe_target(root, "../../evil.py")


def test_safe_target_allows_nested_paths(tmp_path):
    root = tmp_path / "dest"
    root.mkdir()
    target = updater._safe_target(root, "yt_dlp/version.py")
    assert target.name == "version.py"


def test_extract_members_writes_only_matching_prefix(tmp_path):
    wheel = tmp_path / "demo.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("yt_dlp/__init__.py", "x = 1\n")
        zf.writestr("yt_dlp/version.py", "__version__ = '1.2.3'\n")
        zf.writestr("other/__init__.py", "y = 2\n")
    dest = tmp_path / "out"
    written = updater.extract_members(wheel, "yt_dlp/", dest)
    assert len(written) == 2
    # 前缀被剥掉：解压结果本身就是包目录，可直接整体替换覆盖层
    assert (dest / "version.py").exists()
    assert (dest / "__init__.py").exists()
    assert not (dest / "yt_dlp").exists()
    assert not (dest / "other").exists()


def test_extract_members_rejects_traversal(tmp_path):
    wheel = tmp_path / "evil.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("yt_dlp/../../escape.py", "bad\n")
    dest = tmp_path / "out"
    with pytest.raises(updater.UpdateError):
        updater.extract_members(wheel, "yt_dlp/", dest)


# ── 覆盖层生效 ──────────────────────────────────────────────
def test_external_finder_prefers_overlay_directory(tmp_path):
    root = tmp_path / "MusicGrab"
    overlay = root / "yt_dlp"
    overlay.mkdir(parents=True)
    (overlay / "__init__.py").write_text("__version__ = 'OVERLAY'\n", encoding="utf-8")
    (overlay / "version.py").write_text("__version__ = 'OVERLAY'\n", encoding="utf-8")

    finder = updater._ExternalPackageFinder([str(root)], "yt_dlp")
    spec = finder.find_spec("yt_dlp")
    assert spec is not None
    assert Path(spec.origin).resolve() == (overlay / "__init__.py").resolve()

    sub = finder.find_spec("yt_dlp.version", path=[str(overlay)])
    assert sub is not None
    assert Path(sub.origin).resolve() == (overlay / "version.py").resolve()


def test_external_finder_supports_multiple_roots(tmp_path):
    """便携目录优先于机器级目录（两个根都能找到时取靠前的）。"""
    portable = tmp_path / "portable"
    machine = tmp_path / "machine"
    for root in (portable, machine):
        (root / "yt_dlp").mkdir(parents=True)
        (root / "yt_dlp" / "__init__.py").write_text("x = 1\n", encoding="utf-8")

    finder = updater._ExternalPackageFinder([str(portable), str(machine)], "yt_dlp")
    spec = finder.find_spec("yt_dlp")
    assert spec is not None
    assert Path(spec.origin).resolve() == (portable / "yt_dlp" / "__init__.py").resolve()


def test_external_finder_ignores_other_packages(tmp_path):
    finder = updater._ExternalPackageFinder([str(tmp_path)], "yt_dlp")
    assert finder.find_spec("requests") is None
    assert finder.find_spec("mutagen.id3") is None


def test_apply_overlay_installs_finder_and_ignores_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "MusicGrab")
    before = list(sys.meta_path)
    result = updater.apply_overlay()
    assert result == {"ytdlp": False, "ffmpeg": False}
    # 覆盖层为空时不应再装新的 finder。
    # 注意：导入 musicgrab 时会按真实覆盖层装过一个，这里只比较「新增」部分。
    added = [f for f in sys.meta_path if not any(f is old for old in before)]
    assert not any(isinstance(f, updater._ExternalPackageFinder) for f in added)


def test_install_ytdlp_finder_skips_when_already_imported(tmp_path, monkeypatch):
    overlay = tmp_path / "yt_dlp"
    overlay.mkdir()
    (overlay / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "MusicGrab")
    monkeypatch.setitem(sys.modules, "yt_dlp", object())
    try:
        assert updater._install_ytdlp_finder() is False
    finally:
        sys.modules.pop("yt_dlp", None)


def test_current_ytdlp_version_reads_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "MusicGrab")
    overlay = tmp_path / "MusicGrab" / "yt_dlp"
    overlay.mkdir(parents=True)
    (overlay / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (overlay / "version.py").write_text("__version__ = '2099.1.1'\n", encoding="utf-8")
    assert updater.current_ytdlp_version() == "2099.1.1"


def test_locate_package_dir_accepts_frozen_dir_without_init(tmp_path, monkeypatch):
    """冻结布局：磁盘上只有包目录（源码在 PYZ 里），不能因此判定为「找不到」。"""
    root = tmp_path / "MusicGrab"
    (root / "imageio_ffmpeg" / "binaries").mkdir(parents=True)
    monkeypatch.setattr(updater, "overlay_root", lambda: root)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "MEI"), raising=False)
    located = updater._locate_package_dir("imageio_ffmpeg")
    assert located is not None
    assert located.name == "imageio_ffmpeg"


def test_current_imageio_ffmpeg_version_reads_definitions(tmp_path, monkeypatch):
    """imageio-ffmpeg 的版本号在 _definitions.py 里（__init__.py 只做 re-export）。"""
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "MusicGrab")
    pkg = tmp_path / "MusicGrab" / "imageio_ffmpeg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from ._definitions import __version__\n", encoding="utf-8")
    (pkg / "_definitions.py").write_text('__version__ = "0.6.0"\n', encoding="utf-8")
    assert updater.current_imageio_ffmpeg_version() == "0.6.0"


def test_overlay_ffmpeg_exe_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "MusicGrab")
    assert updater.overlay_ffmpeg_exe() is None


def test_apply_ffmpeg_overlay_sets_env(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "overlay_root", lambda: tmp_path / "MusicGrab")
    directory = tmp_path / "MusicGrab" / "ffmpeg"
    directory.mkdir(parents=True)
    fake = directory / "ffmpeg-win-x86_64-v9.9.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", "")
    assert updater.apply_ffmpeg_overlay() is True
    import os

    assert os.environ["IMAGEIO_FFMPEG_EXE"] == str(fake)


# ── ffmpeg 选择优先级 ───────────────────────────────────────
def test_find_ffmpeg_prefers_overlay(tmp_path, monkeypatch):
    from musicgrab import converter

    overlay = tmp_path / "MusicGrab"
    directory = overlay / "ffmpeg"
    directory.mkdir(parents=True)
    fake = directory / "ffmpeg-win-x86_64-v9.9.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setattr(updater, "overlay_root", lambda: overlay)
    monkeypatch.setattr(converter.shutil, "which", lambda _name: None)
    assert converter.find_ffmpeg() == str(fake)


def test_find_ffmpeg_respects_manual_path(tmp_path, monkeypatch):
    from musicgrab import converter

    overlay = tmp_path / "MusicGrab"
    directory = overlay / "ffmpeg"
    directory.mkdir(parents=True)
    (directory / "ffmpeg-win-x86_64-v9.9.exe").write_bytes(b"MZ")
    monkeypatch.setattr(updater, "overlay_root", lambda: overlay)
    manual = tmp_path / "my-ffmpeg.exe"
    manual.write_bytes(b"MZ")
    monkeypatch.setattr(converter.shutil, "which", lambda _name: None)
    assert converter.find_ffmpeg(str(manual)) == str(manual)


# ── 组件状态 ────────────────────────────────────────────────
def test_component_status_fields():
    status = updater.ComponentStatus(
        key=updater.YTDLP,
        label=updater.COMPONENT_LABELS[updater.YTDLP],
        current="2026.08.19",
        latest="2026.10.26",
        has_update=True,
        source="pypi.org",
    )
    assert status.has_update is True
    assert updater.plan_for(status) == ("yt-dlp", "ytdlp")


def test_component_status_summary_text():
    status = updater.ComponentStatus(
        key=updater.YTDLP,
        label=updater.COMPONENT_LABELS[updater.YTDLP],
        current="2026.08.19",
        latest="2026.10.26",
        has_update=True,
    )
    assert status.summary() == "yt-dlp 2026.08.19 → 2026.10.26"

    ffmpeg = updater.ComponentStatus(
        key=updater.FFMPEG,
        label=updater.COMPONENT_LABELS[updater.FFMPEG],
        current="0.6.0",
        latest="0.7.0",
        has_update=True,
    )
    assert ffmpeg.summary() == "ffmpeg 组件 0.6.0 → 0.7.0"


# ── CLI 子命令 ──────────────────────────────────────────────
def test_cli_check_update_runs_offline(monkeypatch, capsys):
    """`check-update` 在网络失败时也应正常输出，不抛异常。"""
    from musicgrab import cli

    def boom(_pkg):
        raise updater.UpdateError("网络不可达")

    monkeypatch.setattr(updater, "fetch_remote_package", boom)
    monkeypatch.setattr(updater, "current_ytdlp_version", lambda: "2026.08.19")
    monkeypatch.setattr(updater, "current_ffmpeg_version", lambda: "7.1")
    assert cli.main(["check-update"]) == 0
    out = capsys.readouterr().out
    assert "yt-dlp" in out
    assert "网络不可达" in out


def test_cli_check_update_json_output(monkeypatch, capsys):
    import json

    from musicgrab import cli

    fake = updater.RemotePackage(
        package="yt-dlp", version="2026.10.26", url="u", sha256="s", size=1, source="pypi.org"
    )
    monkeypatch.setattr(updater, "fetch_remote_package", lambda _pkg: fake)
    monkeypatch.setattr(updater, "current_ytdlp_version", lambda: "2026.08.19")
    monkeypatch.setattr(updater, "current_ffmpeg_version", lambda: "7.1")
    assert cli.main(["check-update", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list) and data
    assert data[0]["latest"] == "2026.10.26"


def test_plan_for_ffmpeg():
    status = updater.ComponentStatus(
        key=updater.FFMPEG,
        label=updater.COMPONENT_LABELS[updater.FFMPEG],
        current="7.1",
        latest="0.6.0",
        has_update=True,
    )
    assert updater.plan_for(status) == ("imageio-ffmpeg", "ffmpeg")
