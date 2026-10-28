"""拖放数据解析：把浏览器链接、本地文件、文件夹统一整理成可导入条目。

浏览器与文件管理器提供的拖放格式并不统一：

===========  ==========================================================
来源          MIME 格式
===========  ==========================================================
Chrome/Edge   ``text/uri-list``（网址）+ ``text/plain``（标题 + 网址）
Firefox       ``text/x-moz-url``（第一行网址、第二行标题）
资源管理器     ``text/uri-list``（``file:///`` 本地路径）
===========  ==========================================================

Qt 的 ``QMimeData.urls()`` 在部分来源上会解析失败（结果为空列表），
于是「拖进来没反应」。因此这里不依赖它，而是把上述原始格式全部自行解析一遍，
并保留 ``urls()`` 作为兜底，保证任何一种来源都能被识别。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from .parser import extract_urls

#: 通用网址列表（Chrome / Edge / 资源管理器）
URL_LIST_MIME = "text/uri-list"
#: Firefox 标签页拖动
MOZ_URL_MIMES = ("text/x-moz-url", "application/x-moz-url")

_WINDOWS_DRIVE_RE = re.compile(r"^/[A-Za-z]:")


@dataclass
class DropPayload:
    """一次拖放解析出来的内容。"""

    links: list[str] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.links and not self.paths


def _safe_call(obj, name: str, default=None):
    """安全调用 ``obj.name()``（拖放对象来自 Qt，异常一律忽略）。"""
    try:
        value = getattr(obj, name)
    except Exception:  # noqa: BLE001
        return default
    try:
        return value() if callable(value) else value
    except Exception:  # noqa: BLE001
        return default


def _mime_text(mime) -> str:
    text = _safe_call(mime, "text", "") or ""
    return text if isinstance(text, str) else str(text)


def _mime_data(mime, fmt: str) -> bytes:
    """读取原始 MIME 数据（Qt 返回 QByteArray，这里统一成 bytes）。"""
    try:
        data = mime.data(fmt)
    except Exception:  # noqa: BLE001
        return b""
    if not data:
        return b""
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    try:
        return bytes(data.data())  # QByteArray
    except Exception:  # noqa: BLE001
        return b""


def _mime_has_format(mime, fmt: str) -> bool:
    try:
        return bool(mime.hasFormat(fmt))
    except Exception:  # noqa: BLE001
        return False


def file_url_to_path(raw: str) -> Path | None:
    """把 ``file:///C:/x/y.mp4`` 之类的网址转成本地路径。"""
    text = (raw or "").strip()
    if not text.lower().startswith("file:"):
        return None
    parsed = urlparse(text)
    path = unquote(parsed.path or "")
    netloc = parsed.netloc or ""
    if netloc and netloc.lower() != "localhost":
        path = f"//{netloc}{path}"
    if not path:
        return None
    if _WINDOWS_DRIVE_RE.match(path):
        path = path[1:]
    return Path(path)


def _uri_list_lines(mime) -> list[str]:
    """解析原始 ``text/uri-list``（Qt 的 urls() 失败时的兜底）。"""
    raw = _mime_data(mime, URL_LIST_MIME)
    if not raw:
        return []
    lines: list[str] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _moz_urls(mime) -> list[str]:
    """解析 Firefox 的 ``text/x-moz-url``（第一行网址，第二行标题）。"""
    for fmt in MOZ_URL_MIMES:
        raw = _mime_data(mime, fmt)
        if not raw:
            continue
        for line in raw.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.lower().startswith(("http://", "https://")):
                return [line]
    return []


def parse_drop_data(mime) -> DropPayload:
    """把拖放数据解析成链接与本地路径列表（自动去重）。"""
    payload = DropPayload()
    seen_links: set[str] = set()
    seen_paths: set[str] = set()

    def add_link(url: str) -> None:
        url = (url or "").strip().strip('"').strip("'").rstrip(",;")
        if not url.lower().startswith(("http://", "https://")):
            return
        if url in seen_links:
            return
        seen_links.add(url)
        payload.links.append(url)

    def add_path(path: Path) -> None:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen_paths:
            return
        seen_paths.add(key)
        payload.paths.append(Path(path))

    # 1) Qt 解析出的 URL 列表
    if _safe_call(mime, "hasUrls", False):
        for url in _safe_call(mime, "urls", []) or []:
            try:
                if url.isLocalFile():
                    add_path(Path(url.toLocalFile()))
                else:
                    add_link(url.toString())
            except Exception:  # noqa: BLE001
                continue

    # 2) 原始 text/uri-list（浏览器标签页最常见）
    for line in _uri_list_lines(mime):
        if line.lower().startswith("file:"):
            path = file_url_to_path(line)
            if path is not None:
                add_path(path)
        else:
            add_link(line)

    # 3) Firefox text/x-moz-url
    for url in _moz_urls(mime):
        add_link(url)

    # 4) 纯文本（标题 + 网址，或直接是本地路径）
    text = _mime_text(mime)
    if text:
        for url in extract_urls(text):
            add_link(url)
        for line in text.splitlines():
            candidate = line.strip().strip('"').strip("'")
            if not candidate or "://" in candidate:
                continue
            try:
                path = Path(candidate).expanduser()
                if path.exists():
                    add_path(path)
            except OSError:
                continue

    return payload


def is_drop_supported(mime) -> bool:
    """判断这次拖放是否应当被当作「导入链接 / 文件」处理。

    只要数据里带有网址列表、浏览器链接格式或文本网址就接受；
    纯文本（如从日志里拖一段字）则保持默认行为。
    """
    if _safe_call(mime, "hasUrls", False):
        return True
    for fmt in (URL_LIST_MIME, *MOZ_URL_MIMES):
        if _mime_has_format(mime, fmt):
            return True
    return bool(extract_urls(_mime_text(mime)))
