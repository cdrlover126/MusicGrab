from __future__ import annotations

from douyin_mp3.proxy import (
    DOMESTIC_DOMAINS,
    OVERSEAS_DOMAINS,
    ROUTE_MODES,
    _host_matches,
    resolve_route,
)

PROXY = "http://127.0.0.1:7890"


def test_route_modes():
    assert ROUTE_MODES == ("auto", "direct", "proxy")


def test_host_matches():
    assert _host_matches("www.douyin.com", DOMESTIC_DOMAINS)
    assert _host_matches("v.douyin.com", DOMESTIC_DOMAINS)
    assert not _host_matches("notdouyin.com", DOMESTIC_DOMAINS)
    assert _host_matches("www.youtube.com", OVERSEAS_DOMAINS)
    assert _host_matches("youtu.be", OVERSEAS_DOMAINS)


def test_direct_mode_ignores_everything():
    r = resolve_route("https://www.youtube.com/watch?v=x", "direct", PROXY)
    assert r.use_proxy is False
    assert r.use_system is False
    assert r.error == ""


def test_proxy_mode_requires_proxy():
    r = resolve_route("https://www.douyin.com/video/1", "proxy", None)
    assert r.error
    assert "未填写代理地址" in r.error


def test_proxy_mode_uses_proxy_for_all():
    r = resolve_route("https://www.douyin.com/video/1", "proxy", PROXY)
    assert r.use_proxy is True
    assert r.use_system is False
    assert r.error == ""


def test_auto_mode_domestic_always_direct():
    for url in (
        "https://www.douyin.com/video/1",
        "https://v.kuaishou.com/abc",
        "https://www.kugou.com/mixsong/x.html",
        "https://www.bilibili.com/video/BV1",
        "https://music.163.com/song?id=1",
    ):
        r = resolve_route(url, "auto", PROXY)
        assert r.use_proxy is False, url
        assert r.use_system is False, url
        assert r.error == "", url


def test_auto_mode_overseas_uses_explicit_proxy():
    r = resolve_route("https://www.youtube.com/watch?v=x", "auto", PROXY)
    assert r.use_proxy is True
    assert r.error == ""


def test_auto_mode_unknown_host_is_direct():
    r = resolve_route("https://example.com/video", "auto", PROXY)
    assert r.use_proxy is False
    assert r.use_system is False
    assert r.error == ""


def test_overseas_and_domestic_sets_do_not_overlap():
    assert not (OVERSEAS_DOMAINS & DOMESTIC_DOMAINS)
