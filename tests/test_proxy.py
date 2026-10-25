from __future__ import annotations

import pytest
import requests

from douyin_mp3.config import ConvertOptions
from douyin_mp3.proxy import (
    ProxyUnreachableError,
    build_session,
    check_proxy_reachable,
    describe_effective_proxy,
    is_proxy_error,
    normalize_proxy,
    proxy_error_message,
    proxy_host_port,
)


def test_normalize_proxy_adds_scheme():
    assert normalize_proxy("127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert normalize_proxy("http://127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert normalize_proxy("  ") == ""
    assert normalize_proxy(None) == ""


def test_proxy_host_port():
    assert proxy_host_port("http://127.0.0.1:7890") == ("127.0.0.1", 7890)
    assert proxy_host_port("127.0.0.1:7890") == ("127.0.0.1", 7890)
    assert proxy_host_port("") is None


def test_check_proxy_reachable_ok_for_empty():
    check_proxy_reachable("")
    check_proxy_reachable(None)


def test_check_proxy_reachable_reports_refused():
    # 1 端口几乎必定无人监听
    with pytest.raises(ProxyUnreachableError) as exc:
        check_proxy_reachable("http://127.0.0.1:1", timeout=0.5)
    msg = str(exc.value)
    assert "代理无法连接" in msg
    assert "127.0.0.1:1" in msg


def test_is_proxy_error_detects_nested():
    err = requests.exceptions.ProxyError("Unable to connect to proxy")
    assert is_proxy_error(err)
    assert not is_proxy_error(requests.exceptions.ConnectionError("boom"))


def test_proxy_error_message_mentions_port_and_hint():
    err = requests.exceptions.ProxyError(
        "Max retries exceeded (Caused by ProxyError('Unable to connect to proxy', "
        "NewConnectionError('Failed to establish a new connection: [WinError 10061] "
        "由于目标计算机积极拒绝，无法连接。')))"
    )
    msg = proxy_error_message(err, "http://127.0.0.1:10090")
    assert "代理无法连接" in msg
    assert "10090" in msg
    assert "强制直连" in msg


def test_describe_effective_proxy_explicit():
    text = describe_effective_proxy("http://127.0.0.1:7890")
    assert "使用指定代理" in text
    assert "7890" in text


def test_build_session_trust_env_toggle():
    s = build_session(None, trust_env=False)
    assert s.trust_env is False
    s2 = build_session("http://127.0.0.1:7890")
    assert s2.proxies["http"] == "http://127.0.0.1:7890"
    assert s2.proxies["https"] == "http://127.0.0.1:7890"


def test_convert_options_trust_env_default():
    assert ConvertOptions().trust_env is True
