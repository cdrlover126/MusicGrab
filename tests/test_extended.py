from __future__ import annotations

import json

import pytest

from douyin_mp3.config import ConvertOptions
from douyin_mp3.cookies import CookieError, normalize_browser
from douyin_mp3.generic import _build_opts, _friendly_error
from douyin_mp3.kuaishou import (
    KuaishouParseError,
    parse_kuaishou_html,
)
from douyin_mp3.kugou import (
    _extract_smarty,
    _extract_title_artist,
    _resolve_ecid_url,
)

SAMPLE_ENTITY = {
    "photoId": "5233464383087894118",
    "photoType": "VIDEO",
    "caption": "测试标题 #音乐",
    "userName": "老徐动物世界",
    "duration": 118001,
    "adaptationSet": [
        {
            "duration": 118001,
            "representation": [
                {
                    "url": "https://v1.kwaicdn.com/low_720.mp4?tag=1",
                    "backupUrl": ["https://v2.kwaicdn.com/low_720_bak.mp4"],
                    "avgBitrate": 900,
                    "qualityLabel": "标清",
                },
                {
                    "url": "https://v1.kwaicdn.com/high_1280.mp4",
                    "backupUrl": ["https://v2.kwaicdn.com/high_1280_bak.mp4"],
                    "avgBitrate": 3300,
                    "qualityLabel": "高清",
                },
            ],
        }
    ],
    "mainMvUrls": [{"cdn": "tymov2.a.kwimgs.com", "url": "https://tymov2.a.kwimgs.com/main.mp4"}],
}


def _html_with(entity: dict) -> str:
    blob = json.dumps({"ssr": {"fw": {"photo": entity}}}, ensure_ascii=False)
    return f"<html><head><script>window.INIT_STATE = {blob}</script></head><body></body></html>"


def test_parse_kuaishou_html_extracts_metadata():
    info = parse_kuaishou_html(
        _html_with(SAMPLE_ENTITY), "3xzgkp4n5dkfvfy", "https://v.kuaishou.com/8OS21F"
    )
    assert info.title == "测试标题 #音乐"
    assert info.artist == "老徐动物世界"
    assert info.duration_ms == 118001
    assert info.display_title == "测试标题 #音乐"


def test_parse_kuaishou_html_prefers_highest_bitrate():
    info = parse_kuaishou_html(
        _html_with(SAMPLE_ENTITY), "3xzgkp4n5dkfvfy", "https://v.kuaishou.com/8OS21F"
    )
    assert info.video_urls[0].startswith("https://v1.kwaicdn.com/high_1280.mp4")
    assert "https://v2.kwaicdn.com/high_1280_bak.mp4" in info.video_urls
    assert "https://tymov2.a.kwimgs.com/main.mp4" in info.video_urls
    assert len(info.video_urls) == len(set(info.video_urls))


def test_parse_kuaishou_html_raises_without_data():
    with pytest.raises(KuaishouParseError):
        parse_kuaishou_html("<html><body>no data</script></body></html>", "x", "https://v.kuaishou.com/x")


def test_friendly_error_adds_cookie_hint():
    message = "ERROR: [Ixigua] 123: Cookies (not necessarily logged in) are needed"
    text = _friendly_error(message)
    assert "cookies-from-browser" in text
    assert text.startswith("ERROR")


def test_friendly_error_plain_message_unchanged():
    assert _friendly_error("Unsupported URL: https://x") == "Unsupported URL: https://x"


def test_build_opts_includes_cookies_and_proxy(tmp_path):
    opts = _build_opts(tmp_path / "a", "http://127.0.0.1:7890", None, "c.txt", "Edge")
    assert opts["proxy"] == "http://127.0.0.1:7890"
    assert opts["cookiefile"].endswith("c.txt")
    assert opts["cookiesfrombrowser"] == ("edge",)
    assert opts["format"] == "bestaudio/best"


def test_build_opts_without_cookies(tmp_path):
    opts = _build_opts(tmp_path / "a", None, None)
    assert "cookiefile" not in opts
    assert "cookiesfrombrowser" not in opts
    assert "proxy" not in opts


def test_normalize_browser():
    assert normalize_browser(" Edge ") == "edge"
    assert normalize_browser("") is None
    assert normalize_browser(None) is None


def test_load_requests_cookies_missing_file(tmp_path):
    import requests

    from douyin_mp3.cookies import load_requests_cookies

    with pytest.raises(CookieError):
        load_requests_cookies(requests.Session(), cookies_file=str(tmp_path / "nope.txt"))


def test_engine_option_defaults():
    options = ConvertOptions()
    assert options.engine == "auto"
    assert options.use_builtin_parser is True
    assert ConvertOptions(engine="generic").use_builtin_parser is False
    assert ConvertOptions(engine="douyin").use_builtin_parser is True


def test_kugou_resolve_ecid_url():
    assert (
        _resolve_ecid_url("https://www.kugou.com/song/#g5jy4e47")
        == "https://www.kugou.com/mixsong/g5jy4e47.html"
    )
    assert (
        _resolve_ecid_url("https://www.kugou.com/mixsong/g5jy4e47.html")
        == "https://www.kugou.com/mixsong/g5jy4e47.html"
    )
    assert (
        _resolve_ecid_url("https://www.kugou.com/song/#hash=FF3432CE123121722CFF5CCA609AD434")
        == "https://www.kugou.com/song/#hash=FF3432CE123121722CFF5CCA609AD434"
    )


def test_kugou_extract_smarty_and_title():
    html = (
        "<script>var dataFromSmarty = "
        '[{"hash":"BAA666B7B11E635EC8118C20E2C7FE7B","timelength":233000,'
        '"audio_name":"\\u5f20\\u6770 - \\u524d\\u8def\\u6709\\u5149",'
        '"author_name":"\\u5f20\\u6770","song_name":"\\u524d\\u8def\\u6709\\u5149"}],'
        "//x</script>"
    )
    smarty = _extract_smarty(html)
    assert smarty["hash"] == "BAA666B7B11E635EC8118C20E2C7FE7B"
    assert smarty["timelength"] == 233000
    title, artist = _extract_title_artist(html)
    assert title == "前路有光"
    assert artist == "张杰"
