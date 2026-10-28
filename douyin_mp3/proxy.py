"""代理路由决策、连通性检测与可读错误信息。

`requests` 默认会继承系统代理（Windows 注册表 / HTTP_PROXY 等环境变量），
一旦代理软件没启动，所有请求都会以「解析失败」「风控」等误导性文案失败。
本模块负责：

1. 按目标站点决定走直连还是走代理（`resolve_route`）
2. 提前检测代理与目标主机的连通性
3. 把底层异常翻译成可操作的提示
"""
from __future__ import annotations

import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from .config import PROXY_TIMEOUT
from .tls import requests_verify

DEFAULT_PROXY_TIMEOUT = PROXY_TIMEOUT

# ── 路由模式 ────────────────────────────────────────────────
ROUTE_MODES = ("auto", "direct", "proxy")
ROUTE_MODE_LABELS = {
    "auto": "智能（按站点自动选择：国内直连 / 境外走代理）",
    "direct": "全部直连（忽略系统代理）",
    "proxy": "全部走代理（需先填写代理地址）",
}

# ── 境外站点域名：国内网络通常无法直连 ──────────────────────
OVERSEAS_DOMAINS = frozenset(
    {
        "youtube.com", "youtu.be", "youtubekids.com", "ytimg.com",
        "tiktok.com", "tiktokcdn.com", "tiktokv.com", "tiktokd.org",
        "twitter.com", "x.com", "t.co", "twimg.com",
        "instagram.com", "cdninstagram.com",
        "facebook.com", "fb.watch", "fbcdn.net",
        "reddit.com", "redd.it", "redditmedia.com",
        "niconico.jp", "nicovideo.jp", "nico.ms", "nicocdn.jp",
        "soundcloud.com", "sndcdn.com",
        "vimeo.com", "dailymotion.com", "dai.ly",
        "twitch.tv", "ttvnw.net", "jtvnw.net",
        "rumble.com", "odysee.com", "odysee.tv",
        "bandcamp.com", "mixcloud.com", "audiomack.com",
        "spotify.com", "scdn.co", "deezer.com", "tidal.com",
        "bilibili.tv",  # 港澳台/海外版
    }
)

# ── 国内平台域名：CDN 全球可达，默认直连 ────────────────────
DOMESTIC_DOMAINS = frozenset(
    {
        "douyin.com", "iesdouyin.com", "douyinstatic.com", "douyinpic.com",
        "kuaishou.com", "chenzhongtech.com", "gifshow.com", "kwai.com",
        "kugou.com", "kgimg.com", "kugou.net",
        "bilibili.com", "b23.tv", "bilivideo.com", "hdslb.com", "biliapi.net",
        "weibo.com", "weibocdn.com", "sinaimg.cn", "sina.com.cn",
        "music.163.com", "126.net", "netease.com",
        "y.qq.com", "qq.com", "gtimg.cn",
        "ixigua.com", "toutiao.com", "byteimg.com", "pstatp.com",
        "xiaohongshu.com", "xhslink.com", "xhscdn.com",
        "youku.com", "iqiyi.com", "v.qq.com", "mgtv.com", "funshine.cn",
        "acfun.cn", "acfun.tv", "zhihu.com", "douban.com",
        "cnblogs.com", "csdn.net", "gitee.com",
    }
)


def _host_matches(host: str, domains: frozenset[str]) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def host_reachable(host: str, port: int = 443, timeout: float = 3.0) -> bool:
    """快速探测目标主机 TCP 是否可达（用于境外站点的直连可行性判断）。"""
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass(frozen=True)
class Route:
    """一条任务的路由决策。

    - `use_proxy`  : 显式走「代理」框中填写的代理
    - `use_system` : 跟随系统/环境代理（仅在无显式代理时生效）
    """

    use_proxy: bool
    reason: str
    error: str = ""
    use_system: bool = False


def _system_proxy_exists() -> bool:
    try:
        env = requests.utils.get_environ_proxies("https://www.youtube.com")
    except Exception:
        return False
    return any(env.get(k) for k in ("http", "https"))


def resolve_route(url: str, mode: str = "auto", proxy: str | None = None) -> Route:
    """根据 URL、路由模式与代理配置，决定该任务走直连还是走代理。

    - `auto`（默认）：
        * 国内平台 → 直连（CDN 全球可达，对国内与境外用户都成立）
        * 境外站点 → 有显式代理走代理；否则先探测直连可达性；
          直连不通但系统有代理则跟随系统代理；两者都没有时给出「需要配置代理」的提示
    - `direct`：全部直连，忽略系统代理
    - `proxy`  ：全部走「代理」框中填写的代理
    """
    mode = (mode or "auto").strip().lower()
    text = normalize_proxy(proxy)
    has_proxy = bool(text)

    if mode == "direct":
        return Route(False, "强制直连（忽略系统代理）")
    if mode == "proxy":
        if not has_proxy:
            return Route(False, "", "已选择「全部走代理」但未填写代理地址，请在「代理」中填写")
        return Route(True, f"全部走代理 {text}")

    host = (urlparse(url).hostname or "").lower()
    if _host_matches(host, OVERSEAS_DOMAINS):
        if has_proxy:
            return Route(True, f"境外站点 {host}，使用代理 {text}")
        if host_reachable(host):
            return Route(False, f"境外站点 {host} 直连可达（当前网络无需代理）")
        if _system_proxy_exists():
            return Route(
                False,
                f"境外站点 {host} 直连不通，跟随系统代理",
                use_system=True,
            )
        return Route(
            False,
            "",
            f"境外站点 {host} 在当前网络下不可达，请在「代理」中填写代理地址后重试",
        )
    if _host_matches(host, DOMESTIC_DOMAINS):
        return Route(False, f"国内平台 {host}，直连")
    return Route(False, f"直连 {host or '未知域名'}")


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


def describe_effective_proxy(explicit: str | None, mode: str = "auto") -> str:
    """描述当前代理设置状态（结合路由模式）。"""
    text = normalize_proxy(explicit)
    if text:
        if mode == "proxy":
            return f"代理: {text}（全部请求走此代理）"
        return f"代理: {text}（智能模式下仅境外站点使用）"
    try:
        system = requests.utils.get_environ_proxies("https://www.douyin.com")
    except Exception:
        system = {}
    inherited = {
        k: v for k, v in system.items() if k in ("http", "https") and v
    }
    detail = ", ".join(f"{k}={v}" for k, v in inherited.items())
    if not inherited:
        return "代理: 未填写（国内平台直连，境外站点将提示需要代理）"
    if mode == "direct":
        return f"代理: 未填写（已忽略系统代理 {detail}，全部直连）"
    return f"代理: 未填写（检测到系统代理 {detail}，境外站点直连不通时会自动跟随）"


def build_session(
    proxy: str | None = None,
    *,
    trust_env: bool = True,
) -> requests.Session:
    """创建统一配置的 requests 会话。

    - `proxy` 非空时显式覆盖 http/https 代理
    - `trust_env=False` 时忽略系统注册表与环境变量中的代理（强制直连）
    - 证书包路径失效时（打包版的临时目录被清理）改用覆盖层里的副本
    """
    session = requests.Session()
    session.trust_env = trust_env
    session.verify = requests_verify()
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
