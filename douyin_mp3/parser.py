from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from .config import MOBILE_UA, PC_UA, REQUEST_TIMEOUT

URL_RE = re.compile(r"https?://[^\s<>\"'，。；！？]+", re.IGNORECASE)
SHORT_LINK_RE = re.compile(r"(?:https?://)?v\.douyin\.com/([A-Za-z0-9_\-]+)", re.IGNORECASE)
AWEME_ID_RE = re.compile(r"(?:video|note|slides)/(\d{10,})")
RENDER_DATA_RE = re.compile(
    r'<script[^>]+id="RENDER_DATA"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)
ROUTER_DATA_RE = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", re.DOTALL
)

DOUYIN_DOMAINS = ("douyin.com", "iesdouyin.com", "douyinstatic.com")
PLATFORM_LABELS = {
    "douyin": "抖音",
    "bilibili": "B站",
    "youtube": "YouTube",
    "kuaishou": "快手",
    "generic": "通用",
}


def classify_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if any(host == d or host.endswith("." + d) for d in DOUYIN_DOMAINS):
        return "douyin"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "kuaishou.com" in host or "v.kuaishou.com" in host:
        return "kuaishou"
    return "generic"


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

    return VideoInfo(
        aweme_id=str(item.get("aweme_id") or aweme_id),
        share_url=share_url,
        title=(item.get("desc") or "").strip(),
        author=author,
        music_title=(music.get("title") or "").strip(),
        music_author=(music.get("author") or "").strip(),
        video_url=video_url,
        music_url=music_url,
        duration_ms=int(item.get("duration") or video.get("duration") or 0),
        extra={"raw_music": music.get("play_url") is not None},
    )


class DouyinClient:
    def __init__(self, proxy: str | None = None, timeout: int = REQUEST_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": MOBILE_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
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
        resp = self.session.get(share_url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        html = resp.text

        payload: Any = None
        m = RENDER_DATA_RE.search(html)
        if m:
            try:
                payload = json.loads(unquote(m.group(1).strip()))
            except json.JSONDecodeError:
                payload = None
        if payload is None:
            m = ROUTER_DATA_RE.search(html)
            if m:
                try:
                    payload = json.loads(m.group(1))
                except json.JSONDecodeError:
                    payload = None

        item_list = _find_item_list(payload) if payload is not None else None
        if not item_list:
            raise DouyinParseError(
                f"页面结构未找到视频数据（可能被风控或页面已改版）: {share_url}"
            )
        return _parse_item(item_list[0], aweme_id, share_url)
