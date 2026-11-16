"""程序自身版本检查 / 下载的单元测试。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from musicgrab import release


def test_normalize_version_strips_prefix():
    assert release.normalize_version("v1.8.1") == "1.8.1"
    assert release.normalize_version(" 1.9.0 ") == "1.9.0"
    assert release.normalize_version("v1.8.0-beta") == "1.8.0"
    assert release.normalize_version("abc") == ""


def test_version_tuple_and_compare():
    assert release.version_tuple("1.8.0") == (1, 8, 0)
    assert release.is_newer_release("1.8.1", "1.8.0") is True
    assert release.is_newer_release("1.8.0", "1.8.0") is False
    assert release.is_newer_release("1.7.9", "1.8.0") is False
    assert release.is_newer_release("v1.10.0", "1.9.0") is True
    assert release.is_newer_release("", "1.8.0") is False


def test_parse_manifest_json():
    info = release.parse_manifest(
        json.dumps(
            {
                "version": "v1.9.0",
                "url": "https://example.com/x.zip",
                "sha256": "ABCDEF",
                "notes": "修了一些问题",
                "size": 123,
            }
        )
    )
    assert info.version == "1.9.0"
    assert info.url == "https://example.com/x.zip"
    assert info.sha256 == "abcdef"
    assert info.notes == "修了一些问题"
    assert info.size == 123


def test_parse_manifest_plain_text():
    info = release.parse_manifest(
        "version=1.9.0\nurl=https://example.com/x.zip\nsha256=00ff\n"
    )
    assert info.version == "1.9.0"
    assert info.url == "https://example.com/x.zip"


def test_parse_manifest_rejects_garbage():
    with pytest.raises(release.ReleaseError):
        release.parse_manifest("")
    with pytest.raises(release.ReleaseError):
        release.parse_manifest("{not json")
    with pytest.raises(release.ReleaseError):
        release.parse_manifest("hello world")


def test_manifest_url_from_env(monkeypatch):
    monkeypatch.setenv(release.ENV_MANIFEST, "http://example.com/latest.json")
    assert release.manifest_url() == "http://example.com/latest.json"
    monkeypatch.delenv(release.ENV_MANIFEST, raising=False)
    monkeypatch.setattr(release, "RELEASE_MANIFEST_URL", "")
    assert release.manifest_url() == ""


def test_fetch_release_without_url(monkeypatch):
    monkeypatch.delenv(release.ENV_MANIFEST, raising=False)
    monkeypatch.setattr(release, "RELEASE_MANIFEST_URL", "")
    with pytest.raises(release.ReleaseError):
        release.fetch_release()


def test_local_manifest_file_is_read_without_network(tmp_path, monkeypatch):
    """清单放在本地文件里也能用（内网共享目录 / U 盘，完全离线）。"""
    manifest = tmp_path / "latest.json"
    manifest.write_text(
        json.dumps({"version": "1.9.0", "url": str(tmp_path / "pkg.zip")}),
        encoding="utf-8",
    )
    # 不配置任何网络地址，直接用本地路径
    info = release.fetch_release(str(manifest))
    assert info.version == "1.9.0"
    assert info.url == str(tmp_path / "pkg.zip")


def test_local_manifest_file_url_form(tmp_path):
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({"version": "1.9.0"}), encoding="utf-8")
    info = release.fetch_release(manifest.as_uri())
    assert info.version == "1.9.0"


def test_local_path_detection(tmp_path):
    real = tmp_path / "a.txt"
    real.write_text("x", encoding="utf-8")
    assert release.local_path_of(str(real)) == real
    assert release.local_path_of(real.as_uri()) == real
    assert release.local_path_of("https://example.com/x.json") is None
    assert release.local_path_of(str(tmp_path / "nope.json")) is None


def test_download_release_from_local_file(tmp_path):
    """清单里指向本地发布包时，直接复制并校验。"""
    import hashlib

    payload = b"local release payload"
    source = tmp_path / "MusicGrab-1.9.0.zip"
    source.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    dest = tmp_path / "downloads"
    info = release.ReleaseInfo(
        version="1.9.0", url=str(source), sha256=digest
    )
    path = release.download_release(info, dest)
    assert path.read_bytes() == payload

    # 校验不过时必须删掉
    info_bad = release.ReleaseInfo(
        version="1.9.0", url=str(source), sha256="00" * 32
    )
    with pytest.raises(release.ReleaseError):
        release.download_release(info_bad, dest)


def test_release_page_url_defaults_to_empty(monkeypatch):
    monkeypatch.setattr(release, "RELEASE_PAGE_URL", "")
    assert release.release_page_url() == ""


def test_extract_release(tmp_path: Path):
    archive = tmp_path / "pkg.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("MusicGrab/MusicGrab.exe", "binary")
        zf.writestr("MusicGrab/使用说明.txt", "hello")

    target = tmp_path / "out"
    release.extract_release(archive, target)

    assert (target / "MusicGrab" / "MusicGrab.exe").read_text() == "binary"
    assert (target / "MusicGrab" / "使用说明.txt").read_text() == "hello"


def test_extract_release_blocks_path_traversal(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")

    with pytest.raises(release.ReleaseError):
        release.extract_release(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_staged_release_dir_uses_program_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "program_dir", lambda: tmp_path)
    target = release.staged_release_dir("1.9.0")
    assert target == tmp_path / "MusicGrab-1.9.0"
    assert target.is_dir()


def test_staged_release_dir_falls_back_when_readonly(tmp_path, monkeypatch):
    """程序目录不可写时，退回到用户目录。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(release, "program_dir", lambda: blocker / "sub")
    target = release.staged_release_dir("1.9.0")
    assert "MusicGrab-1.9.0" in str(target)
    assert target.is_dir()


def test_download_release_verifies_sha256(tmp_path, monkeypatch, monkeypatch_ctx=None):
    """SHA256 不匹配时必须删掉文件并报错。"""
    payload = b"hello world"

    class FakeResponse:
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield payload

    import requests

    monkeypatch.setattr(
        requests, "get", lambda *a, **k: FakeResponse()
    )

    info = release.ReleaseInfo(version="1.9.0", url="http://x/y.zip", sha256="00" * 32)
    with pytest.raises(release.ReleaseError):
        release.download_release(info, tmp_path)
    assert not list(tmp_path.glob("*.zip"))


def test_download_release_accepts_matching_sha256(tmp_path, monkeypatch):
    import hashlib

    payload = b"hello world"
    digest = hashlib.sha256(payload).hexdigest()

    class FakeResponse:
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield payload

    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())

    info = release.ReleaseInfo(
        version="1.9.0", url="http://x/y.zip", sha256=digest
    )
    path = release.download_release(info, tmp_path)
    assert path.exists()
    assert path.read_bytes() == payload


def test_download_release_without_url(tmp_path):
    with pytest.raises(release.ReleaseError):
        release.download_release(
            release.ReleaseInfo(version="1.9.0"), tmp_path
        )
