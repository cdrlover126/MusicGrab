from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urlparse,
    urlunparse,
)

import requests

from .config import MOBILE_UA, REQUEST_TIMEOUT
from .cookies import load_requests_cookies
from .proxy import build_session

URL_RE = re.compile(r"https?://[^\s<>\"'，。；！？]+", re.IGNORECASE)
SHORT_LINK_RE = re.compile(r"(?:https?://)?v\.douyin\.com/([A-Za-z0-9_\-]+)", re.IGNORECASE)
AWEME_ID_RE = re.compile(r"(?:video|note|slides)/(\d{10,})")
# 网页版浏览视频时地址栏常见形式：?modal_id= / ?aweme_id=
AWEME_ID_QUERY_RE = re.compile(r"[?&](?:modal_id|aweme_id|item_id)=(\d{10,})", re.IGNORECASE)
RENDER_DATA_RE = re.compile(
    r'<script[^>]+id="RENDER_DATA"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)
ROUTER_DATA_RE = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", re.DOTALL
)

DOUYIN_DOMAINS = ("douyin.com", "iesdouyin.com", "douyinstatic.com")
KUAISHOU_DOMAINS = ("kuaishou.com", "chenzhongtech.com", "gifshow.com")
KUGOU_DOMAINS = ("kugou.com", "kgimg.com", "kugou.net")
PLATFORM_LABELS = {
    "douyin": "抖音",
    "bilibili": "B站",
    "youtube": "YouTube",
    "kuaishou": "快手",
    "kugou": "酷狗",
    "generic": "通用",
}


def classify_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if any(host == d or host.endswith("." + d) for d in DOUYIN_DOMAINS):
        return "douyin"
    if any(host == d or host.endswith("." + d) for d in KUAISHOU_DOMAINS):
        return "kuaishou"
    if any(host == d or host.endswith("." + d) for d in KUGOU_DOMAINS):
        return "kugou"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    return "generic"


# ── B站链接规范化 ────────────────────────────────────────────
# 问题：yt-dlp 的 BiliBili 提取器只认 `bilibili.com/video/BV…` 的规范形式。
# 地址栏里常见的「语言前缀 / 跟踪参数 / 移动端域名 / b23.tv 短链」都会让
# yt-dlp 匹配不上，掉进 generic 万能提取器，把网页 HTML 本身当成一个
# "格式"，然后报 `The extracted extension ('html') is unusual…` 这个错。
BILI_HOST = "bilibili.com"

#: 跟踪参数（对取视频毫无用处，还会让 yt-dlp 认不出规范 URL）
BILI_TRACKING_PARAMS = frozenset({
    "trackid", "spm_id_from", "vd_source", "share_source", "share_medium",
    "share_plat", "share_tag", "share_session", "shareTimes", "share_times",
    "bbid", "tsl", "unique_k", "buvid", "launch_id", "web_flags",
    "fusion_ui", "xsec_from", "plat_id", "timestamp", "random", "c",
    "callback", "extra_parameter", "channels",
})


def resolve_bili_short_link(url: str) -> str | None:
    """把 b23.tv 短链解析到最终地址（解析失败返回 None，调用方保留原链接）。"""
    from .tls import requests_verify
    try:
        headers = {"User-Agent": MOBILE_UA}
        verify = requests_verify()
        resp = requests.head(
            url, timeout=10, allow_redirects=True, headers=headers, verify=verify
        )
        final = resp.url or ""
        if BILI_HOST in final:
            return final
        # 某些短链对 HEAD 返回 405，改用 GET（流式，不下载正文）
        with requests.get(
            url, timeout=10, allow_redirects=True, headers=headers,
            verify=verify, stream=True,
        ) as resp:
            final = resp.url or ""
            if BILI_HOST in final:
                return final
    except requests.RequestException:
        return None
    return None


def normalize_bilibili(url: str) -> str:
    """把 B站的各种链接形态归一到 yt-dlp 能认的规范形式。"""
    raw = (url or "").strip()
    if not raw.lower().startswith(("http://", "https://")):
        return raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    is_short = host == "b23.tv" or host.endswith(".b23.tv")
    is_bili = is_short or (
        host == BILI_HOST or host.endswith("." + BILI_HOST)
    )
    if not is_bili:
        return raw

    # 1) 短链 → 真实地址
    if is_short:
        resolved = resolve_bili_short_link(raw)
        if not resolved:
            return raw
        raw = resolved
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()

    # 移动端域名归一到 www，保证 yt-dlp 的 BiliBili 提取器能匹配
    if host in ("m.bilibili.com", "bilibili.com"):
        parsed = parsed._replace(netloc="www.bilibili.com")

    # 2) 视频页：提取 BV/av 号，只保留分 P 参数
    m = re.search(r"(?:^|/)(?P<vid>[bB][vV][0-9A-Za-z]{8,10})|av(?P<aid>[0-9]{6,})",
                  parsed.path)
    if m:
        bvid = m.group("vid") or f"av{m.group('aid')}"
        query = ""
        q = parse_qs(parsed.query)
        if "p" in q:
            query = "p=" + quote(str(q["p"][0]), safe="")
        return f"https://www.bilibili.com/video/{bvid}" + (f"?{query}" if query else "")

    # 3) 非视频页（番剧/音频/动态/合集等）：保留路径，仅去掉跟踪参数
    keep = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k not in BILI_TRACKING_PARAMS
    ]
    return urlunparse(parsed._replace(query=urlencode(keep)))


class DouyinParseError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    aweme_id: str
    share_url: str
    title: str = ""
    author: str = ""
    music_title: str = ""
    music_author: str = ""
    video_url: str = ""
    music_url: str = ""
    cover_url: str = ""
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        return self.music_title or self.title or self.aweme_id

    @property
    def artist(self) -> str:
        return self.music_author or self.author or "未知歌手"


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.findall(text or ""):
        url = match.rstrip(").,;'\"[]{}")
        if url.startswith("http") and url not in urls:
            urls.append(url)
    if not urls:
        for match in SHORT_LINK_RE.findall(text or ""):
            candidate = f"https://v.douyin.com/{match}/"
            if candidate not in urls:
                urls.append(candidate)
    return urls


def extract_aweme_id(url: str) -> str | None:
    m = AWEME_ID_RE.search(url)
    if m:
        return m.group(1)
    m = AWEME_ID_QUERY_RE.search(url)
    if m:
        return m.group(1)
    m = SHORT_LINK_RE.search(url)
    if m and len(m.group(1)) >= 15 and m.group(1).isdigit():
        return m.group(1)
    return None


def _find_item_list(node: Any) -> list[dict] | None:
    if isinstance(node, dict):
        if isinstance(node.get("item_list"), list) and node["item_list"]:
            return node["item_list"]
        for value in node.values():
            found = _find_item_list(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_item_list(value)
            if found:
                return found
    return None


def _first_url(container: Any, *keys: str) -> str:
    if not isinstance(container, dict):
        return ""
    for key in keys:
        node = container.get(key)
        if isinstance(node, dict):
            url_list = node.get("url_list") or []
            for url in url_list:
                if isinstance(url, str) and url.startswith("http"):
                    return url
            uri = node.get("uri")
            if isinstance(uri, str) and uri.startswith("http"):
                return uri
        elif isinstance(node, str) and node.startswith("http"):
            return node
    return ""


def _parse_item(item: dict, aweme_id: str, share_url: str) -> VideoInfo:
    video = item.get("video") or {}
    music = item.get("music") or {}
    author = (item.get("author") or {}).get("nickname") or ""

    video_url = _first_url(video, "play_addr", "download_addr", "play_addr_h264")
    if video_url:
        video_url = video_url.replace("playwm", "play")

    music_url = _first_url(music, "play_url", "play_url_uri", "mid_url", "download_url")

    cover_url = _first_url(video, "cover", "origin_cover", "dynamic_cover")

    return VideoInfo(
        aweme_id=str(item.get("aweme_id") or aweme_id),
        share_url=share_url,
        title=(item.get("desc") or "").strip(),
        author=author,
        music_title=(music.get("title") or "").strip(),
        music_author=(music.get("author") or "").strip(),
        video_url=video_url,
        music_url=music_url,
        cover_url=cover_url,
        duration_ms=int(item.get("duration") or video.get("duration") or 0),
        extra={"raw_music": music.get("play_url") is not None},
    )


class DouyinClient:
    def __init__(
        self,
        proxy: str | None = None,
        timeout: int = REQUEST_TIMEOUT,
        *,
        cookies_file: str | None = None,
        cookies_from_browser: str | None = None,
        trust_env: bool = True,
    ):
        self.timeout = timeout
        self.session = build_session(proxy, trust_env=trust_env)
        self.session.headers.update({"User-Agent": MOBILE_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        load_requests_cookies(
            self.session,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
        )
        try:
            self.session.get("https://www.douyin.com/", timeout=self.timeout)
        except requests.RequestException:
            pass

    def resolve(self, url: str) -> tuple[str, str]:
        """返回 (aweme_id, canonical_share_url)。"""
        aweme_id = extract_aweme_id(url)
        if aweme_id:
            return aweme_id, f"https://www.iesdouyin.com/share/video/{aweme_id}/"
        resp = self.session.get(url, allow_redirects=True, timeout=self.timeout)
        final = resp.url
        aweme_id = extract_aweme_id(final)
        if not aweme_id:
            m = re.search(r"/(\d{15,})", final)
            if m:
                aweme_id = m.group(1)
        if not aweme_id:
            raise DouyinParseError(f"无法从链接解析视频ID: {url}")
        return aweme_id, f"https://www.iesdouyin.com/share/video/{aweme_id}/"

    def fetch_info(self, url: str) -> VideoInfo:
        aweme_id, share_url = self.resolve(url)
        headers = {
            "User-Agent": MOBILE_UA,
            "Referer": "https://www.douyin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        # 依次尝试分享页与网页版详情页，降低风控导致的失败率
        candidates = [share_url, f"https://www.douyin.com/video/{aweme_id}"]
        last_error = ""
        for candidate in candidates:
            try:
                resp = self.session.get(candidate, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException as exc:
                last_error = str(exc)
                continue

            payload: Any = None
            m = RENDER_DATA_RE.search(resp.text)
            if m:
                try:
                    payload = json.loads(unquote(m.group(1).strip()))
                except json.JSONDecodeError:
                    payload = None
            if payload is None:
                m = ROUTER_DATA_RE.search(resp.text)
                if m:
                    try:
                        payload = json.loads(m.group(1))
                    except json.JSONDecodeError:
                        payload = None

            item_list = _find_item_list(payload) if payload is not None else None
            if item_list:
                return _parse_item(item_list[0], aweme_id, share_url)
            last_error = f"页面结构未找到视频数据: {candidate}"

        raise DouyinParseError(
            f"{last_error or '解析失败'}（可能被风控或页面已改版，可稍后重试或提供 cookies）"
        )
