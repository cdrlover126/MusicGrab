"""拖放数据解析测试。

用一个假的 MIME 对象覆盖浏览器的各种拖放格式，重点回归「拖标签页没反应」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from douyin_mp3.dragdrop import (
    URL_LIST_MIME,
    file_url_to_path,
    is_drop_supported,
    parse_drop_data,
)


class FakeUrl:
    """模拟 QUrl。"""

    def __init__(self, raw: str) -> None:
        self._raw = raw

    def isLocalFile(self) -> bool:  # noqa: N802 (Qt 命名)
        return self._raw.lower().startswith("file:")

    def toLocalFile(self) -> str:  # noqa: N802 (Qt 命名)
        return file_url_to_path(self._raw).as_posix() if file_url_to_path(self._raw) else ""

    def toString(self) -> str:  # noqa: N802 (Qt 命名)
        return self._raw

    def scheme(self) -> str:  # noqa: N802 (Qt 命名)
        return self._raw.split(":", 1)[0].lower()


class FakeMime:
    """模拟 QMimeData：可只提供某一种原始格式。"""

    def __init__(
        self,
        *,
        urls: list[str] | None = None,
        text: str = "",
        formats: dict[str, bytes] | None = None,
    ) -> None:
        self._urls = urls or []
        self._text = text
        self._formats = formats or {}

    def hasUrls(self) -> bool:  # noqa: N802 (Qt 命名)
        return bool(self._urls)

    def urls(self) -> list[FakeUrl]:  # noqa: N802 (Qt 命名)
        return [FakeUrl(u) for u in self._urls]

    def text(self) -> str:
        return self._text

    def hasFormat(self, fmt: str) -> bool:  # noqa: N802 (Qt 命名)
        return fmt in self._formats

    def data(self, fmt: str) -> bytes:
        return self._formats.get(fmt, b"")


def test_chrome_style_drag_with_urls_and_text() -> None:
    mime = FakeMime(
        urls=["https://www.bilibili.com/video/BV1xx411c7mD"],
        text="【标题】 https://www.bilibili.com/video/BV1xx411c7mD",
    )
    payload = parse_drop_data(mime)
    assert payload.links == ["https://www.bilibili.com/video/BV1xx411c7mD"]
    assert payload.paths == []


def test_uri_list_only_is_parsed() -> None:
    """回归：只有原始 text/uri-list（Qt 的 urls() 为空）时也要能识别。"""
    mime = FakeMime(
        formats={URL_LIST_MIME: b"https://v.douyin.com/abc123/\r\n"}
    )
    payload = parse_drop_data(mime)
    assert payload.links == ["https://v.douyin.com/abc123/"]


def test_uri_list_with_multiple_links() -> None:
    mime = FakeMime(
        formats={
            URL_LIST_MIME: (
                "# 注释行\r\nhttps://v.douyin.com/aaa/\r\nhttps://v.kuaishou.com/bbb\r\n"
            ).encode()
        }
    )
    payload = parse_drop_data(mime)
    assert payload.links == [
        "https://v.douyin.com/aaa/",
        "https://v.kuaishou.com/bbb",
    ]


def test_mozilla_url_format_is_parsed() -> None:
    """Firefox 拖标签页：text/x-moz-url 第一行是网址。"""
    mime = FakeMime(
        formats={
            "text/x-moz-url": "https://www.youtube.com/watch?v=abc\nYouTube\n".encode()
        }
    )
    payload = parse_drop_data(mime)
    assert payload.links == ["https://www.youtube.com/watch?v=abc"]


def test_plain_text_url_is_parsed() -> None:
    mime = FakeMime(text="看这个 https://music.163.com/song?id=347230 很好听")
    payload = parse_drop_data(mime)
    assert payload.links == ["https://music.163.com/song?id=347230"]


def test_local_file_url_becomes_path(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    mime = FakeMime(urls=[video.as_uri()])
    payload = parse_drop_data(mime)
    assert payload.paths
    assert payload.paths[0].name == "a.mp4"


def test_file_uri_list_becomes_path(tmp_path: Path) -> None:
    video = tmp_path / "b.mp4"
    video.write_bytes(b"x")
    mime = FakeMime(formats={URL_LIST_MIME: (video.as_uri() + "\r\n").encode()})
    payload = parse_drop_data(mime)
    assert [p.name for p in payload.paths] == ["b.mp4"]


def test_plain_local_path_in_text_is_parsed(tmp_path: Path) -> None:
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")
    mime = FakeMime(text=str(video))
    payload = parse_drop_data(mime)
    assert [p.name for p in payload.paths] == ["c.mp4"]


def test_duplicates_are_removed() -> None:
    mime = FakeMime(
        urls=["https://v.douyin.com/abc/"],
        text="https://v.douyin.com/abc/ https://v.douyin.com/abc/",
        formats={URL_LIST_MIME: b"https://v.douyin.com/abc/\r\n"},
    )
    payload = parse_drop_data(mime)
    assert payload.links == ["https://v.douyin.com/abc/"]


def test_unrelated_text_yields_nothing() -> None:
    mime = FakeMime(text="这是一段普通文字，没有网址")
    payload = parse_drop_data(mime)
    assert payload.empty is True


def test_is_drop_supported() -> None:
    assert is_drop_supported(FakeMime(urls=["https://a.com/x"])) is True
    assert is_drop_supported(FakeMime(formats={URL_LIST_MIME: b"https://a.com/x"})) is True
    assert (
        is_drop_supported(
            FakeMime(formats={"text/x-moz-url": b"https://a.com/x\ntitle"})
        )
        is True
    )
    assert is_drop_supported(FakeMime(text="https://a.com/x")) is True
    assert is_drop_supported(FakeMime(text="普通文字")) is False


def test_file_url_to_path_handles_windows_drive() -> None:
    path = file_url_to_path("file:///C:/Users/test/a.mp4")
    assert path is not None
    assert str(path).replace("\\", "/") == "C:/Users/test/a.mp4"


def test_file_url_to_path_handles_unc() -> None:
    path = file_url_to_path("file://server/share/a.mp4")
    assert path is not None
    assert "server" in str(path)
    assert "a.mp4" in str(path)


def test_file_url_to_path_rejects_http() -> None:
    assert file_url_to_path("https://example.com/a.mp4") is None


def test_empty_payload_property() -> None:
    mime = FakeMime(text="nothing here")
    payload = parse_drop_data(mime)
    assert payload.empty
    assert not payload.links
    assert not payload.paths


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
