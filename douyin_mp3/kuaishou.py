from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests

from .config import MOBILE_UA, REQUEST_TIMEOUT
from .cookies import load_requests_cookies
from .proxy import build_session

KUAISHOU_DOMAINS = (
    "kuaishou.com",
    "chenzhongtech.com",
    "gifshow.com",
    "kwimgs.com",
)

PHOTO_ID_RE = re.compile(r"/(?:fw/photo|short-video|photo)/([A-Za-z0-9_-]{6,})")
SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL)


class KuaishouParseError(RuntimeError):
    pass


@dataclass
class KuaishouInfo:
    photo_id: str
    share_url: str
    title: str = ""
    author: str = ""
    duration_ms: int = 0
    video_urls: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        return self.title or self.photo_id

    @property
    def artist(self) -> str:
        return self.author or "未知歌手"


def _dedupe(urls: list[str]) -> list[str]:
    seen: list[str] = []
    for url in urls:
        if url and url.startswith("http") and url not in seen:
            seen.append(url)
    return seen


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\\u002F", "/").replace("\\/", "/")
    text = html_module.unescape(text)
    return " ".join(text.split())


def _collect_urls(node: Any, urls: list[str]) -> None:
    if isinstance(node, dict):
        for key in ("url", "playUrl", "srcNoMark", "photoUrl", "urlNoMark"):
            value = node.get(key)
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)
        for key in ("backupUrl", "urls", "urlList"):
            value = node.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.startswith("http"):
                        urls.append(item)
                    elif isinstance(item, dict):
                        _collect_urls(item, urls)
        for value in node.values():
            if isinstance(value, (dict, list)):
                _collect_urls(value, urls)
    elif isinstance(node, list):
        for item in node:
            _collect_urls(item, urls)


def _find_entity(node: Any) -> dict | None:
    if isinstance(node, dict):
        if node.get("photoType") or "adaptationSet" in node or "mainMvUrls" in node:
            return node
        for value in node.values():
            found = _find_entity(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_entity(item)
            if found:
                return found
    return None


def _quality_of(representation: dict) -> float:
    for key in ("avgBitrate", "maxBitrate", "bitrate"):
        value = representation.get(key)
        if isinstance(value, (int, float)) and value:
            return float(value)
    return 0.0


def _ranked_video_urls(entity: dict) -> list[str]:
    ranked: list[tuple[float, list[str]]] = []
    for adaptation in entity.get("adaptationSet") or []:
        if not isinstance(adaptation, dict):
            continue
        for representation in adaptation.get("representation") or []:
            if not isinstance(representation, dict):
                continue
            candidates: list[str] = []
            url = representation.get("url")
            if isinstance(url, str) and url.startswith("http"):
                candidates.append(url)
            for backup in representation.get("backupUrl") or []:
                if isinstance(backup, str) and backup.startswith("http"):
                    candidates.append(backup)
            if candidates:
                ranked.append((_quality_of(representation), candidates))
    ranked.sort(key=lambda item: item[0], reverse=True)

    urls: list[str] = []
    for _, candidates in ranked:
        urls.extend(candidates)

    for entry in entity.get("mainMvUrls") or []:
        if isinstance(entry, dict) and isinstance(entry.get("url"), str):
            urls.append(entry["url"])
        elif isinstance(entry, str):
            urls.append(entry)

    _collect_urls(entity.get("manifest") or {}, urls)
    for key in ("photoUrl", "srcNoMark", "playUrl"):
        value = entity.get(key)
        if isinstance(value, str):
            urls.append(value)
    return _dedupe([u.replace("\\u002F", "/") for u in urls])


def parse_kuaishou_html(html: str, photo_id: str, share_url: str) -> KuaishouInfo:
    payload: Any = None
    for block in SCRIPT_RE.findall(html or ""):
        if '"adaptationSet"' not in block and '"photoType"' not in block and '"mainMvUrls"' not in block:
            continue
        start = block.find("{")
        if start < 0:
            continue
        blob = block[start:].strip().rstrip(";")
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            break

    entity = _find_entity(payload) if payload is not None else None
    if not entity:
        raise KuaishouParseError(
            f"快手页面未找到视频数据（可能被风控或需要 cookies）: {share_url}"
        )

    urls = _ranked_video_urls(entity)
    if not urls:
        raise KuaishouParseError(f"快手视频未取到可播放地址: {share_url}")

    duration = entity.get("duration")
    return KuaishouInfo(
        photo_id=str(entity.get("photoId") or photo_id),
        share_url=share_url,
        title=_clean_text(entity.get("caption")),
        author=_clean_text(entity.get("userName")),
        duration_ms=int(duration) if isinstance(duration, (int, float)) else 0,
        video_urls=urls,
    )


def is_kuaishou_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in KUAISHOU_DOMAINS)


class KuaishouClient:
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
        self.session.headers.update(
            {"User-Agent": MOBILE_UA, "Accept-Language": "zh-CN,zh;q=0.9"}
        )
        load_requests_cookies(
            self.session,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
        )

    def resolve(self, url: str) -> tuple[str, str]:
        """返回 (photo_id, 最终页面URL)。"""
        resp = self.session.get(url, allow_redirects=True, timeout=self.timeout)
        resp.raise_for_status()
        final = resp.url
        match = PHOTO_ID_RE.search(final) or PHOTO_ID_RE.search(url)
        if not match:
            raise KuaishouParseError(f"无法从快手链接解析视频ID: {url}")
        return match.group(1), final

    def fetch_info(self, url: str) -> KuaishouInfo:
        photo_id, final_url = self.resolve(url)
        resp = self.session.get(final_url, timeout=self.timeout)
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        return parse_kuaishou_html(resp.text, photo_id, url)
