"""代理连通性检测与可读错误信息。

`requests` 默认会继承系统代理（Windows 注册表 / HTTP_PROXY 等环境变量），
一旦代理软件没启动，所有请求都会以「解析失败」「风控」等误导性文案失败。
本模块负责把这类问题提前识别出来，并给出可操作的提示。
"""
from __future__ import annotations

import socket
from urllib.parse import urlparse

import requests

from .config import PROXY_TIMEOUT

DEFAULT_PROXY_TIMEOUT = PROXY_TIMEOUT


class ProxyUnreachableError(RuntimeError):
    """代理无法连通（通常是代理软件未启动或端口填错）。"""


def normalize_proxy(proxy: str | None) -> str:
    """把用户填写的代理补全为带 scheme 的 URL。"""
    text = (proxy or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    return text


def proxy_host_port(proxy: str) -> tuple[str, int] | None:
    """解析代理的主机与端口，失败返回 None。"""
    text = normalize_proxy(proxy)
    if not text:
        return None
    parsed = urlparse(text)
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def check_proxy_reachable(proxy: str | None, timeout: float = DEFAULT_PROXY_TIMEOUT) -> None:
    """检测代理端口是否可连接，不可连则抛出 ProxyUnreachableError。"""
    text = normalize_proxy(proxy)
    if not text:
        return
    target = proxy_host_port(text)
    if not target:
        raise ProxyUnreachableError(f"代理地址无法解析: {text}")
    host, port = target
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        raise ProxyUnreachableError(
            f"代理无法连接（{host}:{port}）——请确认代理软件已启动、端口正确；"
            f"若不需要代理请清空「代理」设置。底层原因：{exc}"
        ) from exc


def is_proxy_error(exc: BaseException) -> bool:
    """判断异常是否由代理引起。"""
    if isinstance(exc, requests.exceptions.ProxyError):
        return True
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, requests.exceptions.ProxyError):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def describe_effective_proxy(explicit: str | None, trust_env: bool = True) -> str:
    """描述实际生效的代理：显式设置 / 继承系统 / 强制直连。"""
    text = normalize_proxy(explicit)
    if text:
        return f"使用指定代理 {text}"
    try:
        system = requests.utils.get_environ_proxies("https://www.douyin.com")
    except Exception:
        system = {}
    inherited = {
        k: v
        for k, v in system.items()
        if k in ("http", "https") and v
    }
    if inherited and trust_env:
        detail = ", ".join(f"{k}={v}" for k, v in inherited.items())
        return f"未指定代理，跟随系统/环境代理（{detail}）"
    if inherited:
        return "直连（已忽略系统/环境代理：" + ", ".join(f"{k}={v}" for k, v in inherited.items()) + "）"
    return "直连（未使用代理）"


def build_session(
    proxy: str | None = None,
    *,
    trust_env: bool = True,
) -> requests.Session:
    """创建统一配置的 requests 会话。

    - `proxy` 非空时显式覆盖 http/https 代理
    - `trust_env=False` 时忽略系统注册表与环境变量中的代理（强制直连）
    """
    session = requests.Session()
    session.trust_env = trust_env
    text = normalize_proxy(proxy)
    if text:
        session.proxies.update({"http": text, "https": text})
    return session


def proxy_error_message(exc: BaseException, proxy: str | None = None) -> str:
    """把 requests 的代理异常翻译成可操作的提示。"""
    text = normalize_proxy(proxy)
    detail = str(exc)
    if "Connection refused" in detail or "10061" in detail or "actively refused" in detail:
        target = text or "系统/环境中的代理"
        return (
            f"代理无法连接（{target}）——请确认代理软件已启动、端口与设置一致；"
            f"若不需要代理请清空「代理」设置并勾选「直连」"
        )
    if "407" in detail or "Proxy Authentication" in detail:
        return f"代理需要认证（{text}）——请检查代理用户名/密码"
    if text:
        return f"代理请求失败（{text}）：{detail[:160]}"
    return f"代理请求失败（跟随系统/环境代理）：{detail[:160]}"


TIMEOUT_HINT = (
    "若目标为境外站点，请填写代理地址（http://127.0.0.1:7890）；"
    "国内平台直连即可"
)

_TIMEOUT_MARKERS = (
    "timed out",
    "timeout",
    "read timeout",
    "connect timeout",
    "network is unreachable",
    "failed to establish a new connection",
    "temporary failure in name resolution",
    "getaddrinfo failed",
)


def is_timeout_error(exc: BaseException) -> bool:
    """判断异常是否为网络超时/不可达（而非平台返回的解析错误）。"""
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    detail = str(exc).lower()
    return any(marker in detail for marker in _TIMEOUT_MARKERS)


def timeout_error_message(exc: BaseException, proxy: str | None = None) -> str:
    """网络超时/不可达的可操作提示。"""
    return f"网络连接失败：{str(exc)[:140]}（{TIMEOUT_HINT}）"
