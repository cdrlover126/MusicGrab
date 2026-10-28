"""TLS 证书包兜底测试（打包版临时目录被清理时的自愈）。"""

from __future__ import annotations

from pathlib import Path

from douyin_mp3 import tls
from douyin_mp3.config import overlay_root


def test_overlay_root_is_under_localappdata():
    path = overlay_root()
    assert path.name == "MusicGrab"


def test_bundled_ca_path_exists_in_normal_environment():
    """正常情况下 certifi 的证书包是存在的。"""
    assert tls.ca_bundle_available() is True


def test_save_ca_bundle_creates_copy(tmp_path: Path):
    target = tls.save_ca_bundle(tmp_path)
    assert target is not None
    assert target.exists()
    assert target.stat().st_size > 1000


def test_save_ca_bundle_is_idempotent(tmp_path: Path):
    first = tls.save_ca_bundle(tmp_path)
    assert first is not None
    stamp = first.stat().st_mtime
    second = tls.save_ca_bundle(tmp_path)
    assert second == first
    assert second.stat().st_mtime == stamp


def test_requests_verify_uses_default_when_available(tmp_path: Path):
    assert tls.requests_verify(tmp_path) is True


def test_requests_verify_falls_back_to_saved_copy(tmp_path: Path, monkeypatch):
    """certifi 路径失效时（临时目录被清理），改用覆盖层里的副本。"""
    saved = tls.save_ca_bundle(tmp_path)
    assert saved is not None
    monkeypatch.setattr(tls, "bundled_ca_path", lambda: r"C:\nonexistent\cacert.pem")

    verify = tls.requests_verify(tmp_path)
    assert verify == str(saved)
    assert Path(str(verify)).exists()


def test_requests_verify_without_any_bundle(tmp_path: Path, monkeypatch):
    """既没有 certifi 也没有副本时，回退到 requests 默认行为。"""
    monkeypatch.setattr(tls, "bundled_ca_path", lambda: "")
    assert tls.requests_verify(tmp_path) is True


def test_saved_ca_path_missing_returns_none(tmp_path: Path):
    assert tls.saved_ca_path(tmp_path) is None


def test_updater_http_uses_fallback(monkeypatch):
    """升级相关的网络请求必须走 verify 兜底。"""
    import inspect

    from douyin_mp3 import updater

    src = inspect.getsource(updater)
    assert "verify=requests_verify(overlay_root())" in src
