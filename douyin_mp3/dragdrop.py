"""拖放数据解析：把浏览器链接、本地文件、文件夹统一整理成可导入条目。

浏览器与文件管理器提供的拖放格式并不统一：

===========  ==========================================================
来源          MIME 格式
===========  ==========================================================
Chrome/Edge   ``text/uri-list``（网址）+ ``text/plain``（标题 + 网址）
Firefox       ``text/x-moz-url``（第一行网址、第二行标题）
资源管理器     ``text/uri-list``（``file:///`` 本地路径）
===========  ==========================================================

另外两个现实坑：

* Chromium 会把网址列表注册成 ``text/uri-list;charset=utf-8`` 这种**带参数**的格式名，
  与 Qt 精确匹配的 ``text/uri-list`` 不是一回事——``hasFormat()`` 会返回 False，
  ``urls()`` 也会是空列表。
* 有的来源只给纯文本（CF_UNICODETEXT），没有 urls / uri-list。

因此这里不依赖 Qt 的 ``QMimeData.urls()``，而是把 mime 里**所有**可读格式
都自行解码一遍再找网址，保证任何一种来源都能被识别。
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
#: 形如 "text/uri-list;charset=utf-8" 的格式，按基础名归类
URLISH_FORMAT_BASES = frozenset(
    {
        "text/uri-list",
        "text/x-moz-url",
        "application/x-moz-url",
        "text/x-url",
        "application/x-url",
        "text/x-uri-list",
    }
)
#: 这些格式里可能混着整页的链接（Chromium 拖链接时会带 text/html），
#: 一律不参与网址提取，否则一次拖放会导入一堆无关链接
SKIP_FORMAT_BASES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/rtf",
        "application/rtf",
        "text/richtext",
        "application/x-chrome-address-book",
    }
)

_WINDOWS_DRIVE_RE = re.compile(r"^/[A-Za-z]:")
#: 二进制负载里可能混入的控制字符（会让网址后面拖上 "\x00" 之类）
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: 是否允许把浏览器标签页 / 链接拖进输入框。
#:
#: v1.8.0 起暂时关闭：各浏览器对「拖标签页」给出的 MIME 数据差异太大，
#: 实际体验不稳定，先只保留文件 / 文件夹拖放（链接请复制后粘贴）。
#: 需要恢复时把这里改成 True 即可。
ALLOW_LINK_DROP = False

#: 链接拖放被关闭时给用户的提示
LINK_DROP_DISABLED_HINT = "暂不支持拖动浏览器标签页，请复制网址后粘贴"


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


def _mime_formats(mime) -> list[str]:
    """列出 mime 里所有可读的格式名。"""
    try:
        return [str(f) for f in (mime.formats() or [])]
    except Exception:  # noqa: BLE001
        return []


def _format_base(fmt: str) -> str:
    """去掉 "text/uri-list;charset=utf-8" 里的参数部分。"""
    return fmt.split(";", 1)[0].strip().lower()


def _is_urlish_format(fmt: str) -> bool:
    return _format_base(fmt) in URLISH_FORMAT_BASES


def _sanitize(text: str) -> str:
    """去掉控制字符，避免网址被 "\\x00" 之类的东西污染。"""
    return _CTRL_RE.sub("", text)


def _decode_payload(raw: bytes, fmt: str) -> str:
    """按格式名里的 charset 猜编码；实在猜不出就用 utf-8 兜底。"""
    lowered = fmt.lower()
    if "utf-16" in lowered:
        candidates = ("utf-16", "utf-16-le", "utf-8")
    elif "gb" in lowered:
        candidates = ("gb18030", "utf-8")
    else:
        candidates = ("utf-8", "gb18030", "utf-16-le")
    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _iter_format_payloads(mime) -> list[tuple[str, str]]:
    """把 mime 里所有格式的原始数据解码成文本（跳过 HTML / RTF 等噪声格式）。"""
    payloads: list[tuple[str, str]] = []
    for fmt in _mime_formats(mime):
        if _format_base(fmt) in SKIP_FORMAT_BASES:
            continue
        raw = _mime_data(mime, fmt)
        if not raw:
            continue
        text = _sanitize(_decode_payload(raw, fmt))
        if text:
            payloads.append((fmt, text))
    return payloads


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

    # 5) 兜底：扫描所有格式的原始数据
    #    Chromium 会把网址列表注册成 "text/uri-list;charset=utf-8"，
    #    Qt 的 hasFormat("text/uri-list") / urls() 都会漏掉它
    for fmt, chunk in _iter_format_payloads(mime):
        if _is_urlish_format(fmt):
            for line in chunk.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("file:"):
                    path = file_url_to_path(line)
                    if path is not None:
                        add_path(path)
                else:
                    add_link(line)
        for url in extract_urls(chunk):
            add_link(url)

    return payload


def is_drop_supported(mime) -> bool:
    """判断这次拖放是否应当被当作「导入链接 / 文件」处理。

    只要数据里带有网址列表、浏览器链接格式或文本网址就接受；
    纯文本（如从日志里拖一段字）则保持默认行为。
    """
    if _safe_call(mime, "hasUrls", False):
        return True
    for fmt in _mime_formats(mime):
        if _is_urlish_format(fmt):
            return True
    if extract_urls(_mime_text(mime)):
        return True
    for _fmt, payload in _iter_format_payloads(mime):
        if extract_urls(payload):
            return True
    return False


def split_drop_payload(
    payload: DropPayload, allow_links: bool = ALLOW_LINK_DROP
) -> tuple[list[str], list[Path], bool]:
    """把拖放内容拆成「要导入的链接」「要导入的本地文件」「是否忽略了链接」。

    链接拖放被关闭时（``allow_links=False``），链接会被丢弃并返回提示标记，
    让界面可以明确告诉用户「请复制网址后粘贴」，而不是毫无反应。
    """
    if allow_links:
        return list(payload.links), list(payload.paths), False
    return [], list(payload.paths), bool(payload.links)
