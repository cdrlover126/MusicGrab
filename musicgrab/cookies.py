from __future__ import annotations

import http.cookiejar
from pathlib import Path

import requests


class CookieError(RuntimeError):
    pass


def normalize_browser(browser: str | None) -> str | None:
    value = (browser or "").strip().lower()
    return value or None


def load_requests_cookies(
    session: requests.Session,
    *,
    cookies_file: str | None = None,
    cookies_from_browser: str | None = None,
) -> int:
    """把 cookies 载入 requests 会话，返回注入的 cookie 条数。"""
    if cookies_file:
        path = Path(cookies_file).expanduser()
        if not path.exists():
            raise CookieError(f"cookies 文件不存在: {path}")
        jar = http.cookiejar.MozillaCookieJar(str(path))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except (OSError, http.cookiejar.LoadError) as exc:
            raise CookieError(f"读取 cookies 文件失败: {exc}") from exc
        count = 0
        for cookie in jar:
            session.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path or "/")
            count += 1
        return count

    browser = normalize_browser(cookies_from_browser)
    if browser:
        try:
            from yt_dlp.cookies import extract_cookies_from_browser
        except ImportError as exc:
            raise CookieError("读取浏览器 cookies 需要 yt-dlp，请执行: pip install yt-dlp") from exc
        try:
            jar = extract_cookies_from_browser(browser)
        except Exception as exc:
            detail = str(exc).splitlines()[0]
            hint = ""
            if "cookie database" in detail.lower():
                hint = "（请先完全退出 Edge/Chrome 等浏览器后重试，或改用 --cookies cookies.txt）"
            raise CookieError(f"从 {browser} 读取 cookies 失败: {detail}{hint}") from exc
        count = 0
        for cookie in jar:
            session.cookies.set(
                cookie.name,
                cookie.value,
                domain=(cookie.domain or "").lstrip(".") or None,
                path=cookie.path or "/",
            )
            count += 1
        return count

    return 0
