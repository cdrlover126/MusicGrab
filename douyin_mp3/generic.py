from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .cookies import normalize_browser

ProgressCallback = Callable[[int, int], None]


class GenericParseError(RuntimeError):
    pass


@dataclass
class GenericMeta:
    title: str
    artist: str
    duration: float = 0.0
    webpage_url: str = ""
    extractor: str = ""
    album: str = ""


def _build_opts(
    dest_base: Path,
    proxy: str | None,
    progress: ProgressCallback | None,
    cookies_file: str | None = None,
    cookies_from_browser: str | None = None,
    trust_env: bool = True,
) -> dict:
    opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_base) + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 3,
        "ignoreerrors": False,
        "overwrites": True,
    }
    if proxy:
        opts["proxy"] = proxy
    elif not trust_env:
        # 忽略系统/环境变量中的代理，强制直连（yt-dlp 中空串表示不使用代理）
        opts["proxy"] = ""
    if cookies_file:
        opts["cookiefile"] = str(Path(cookies_file).expanduser())
    browser = normalize_browser(cookies_from_browser)
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    if progress:

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                done = int(d.get("downloaded_bytes") or 0)
                progress(done, total)
            elif d.get("status") == "finished":
                total = int(d.get("total_bytes") or 0) or 1
                progress(total, total)

        opts["progress_hooks"] = [hook]
    return opts


COOKIE_HINT = (
    "该站点需要登录信息，请用 --cookies-from-browser edge（或 chrome/firefox）"
    "或 --cookies cookies.txt 提供 cookies 后重试"
)


def _friendly_error(message: str) -> str:
    lowered = message.lower()
    if any(word in lowered for word in ("cookie", "login", "registered", "sign in", "log in")):
        return f"{message}（{COOKIE_HINT}）"
    return message


def download_generic_audio(
    url: str,
    dest: Path,
    *,
    proxy: str | None = None,
    progress: ProgressCallback | None = None,
    cookies_file: str | None = None,
    cookies_from_browser: str | None = None,
    trust_env: bool = True,
) -> GenericMeta:
    """用 yt-dlp 下载任意支持站点的最佳音轨到 dest，返回元数据。"""
    try:
        import yt_dlp
    except ImportError as exc:
        raise GenericParseError(
            "未安装 yt-dlp，无法处理抖音/快手/酷狗以外的链接。请执行: pip install yt-dlp"
        ) from exc

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest_base = dest.with_suffix("")
    opts = _build_opts(
        dest_base, proxy, progress, cookies_file, cookies_from_browser, trust_env=trust_env
    )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise GenericParseError(_friendly_error(str(exc).splitlines()[0])) from exc

    if not info:
        raise GenericParseError("站点未返回视频信息")

    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]

    candidates = sorted(dest_base.parent.glob(dest_base.name + ".*"))
    candidates = [c for c in candidates if c.suffix != ".part" and c.is_file()]
    if not candidates:
        raise GenericParseError("yt-dlp 下载后未找到输出文件")
    downloaded = max(candidates, key=lambda p: p.stat().st_size)
    if downloaded != dest:
        downloaded.replace(dest)

    artist = (
        str(info.get("artist") or "").strip()
        or ", ".join(str(a).strip() for a in (info.get("artists") or []) if a).strip()
        or str(info.get("album_artist") or "").strip()
        or ", ".join(str(a).strip() for a in (info.get("album_artists") or []) if a).strip()
        or str(info.get("creator") or "").strip()
        or ", ".join(str(a).strip() for a in (info.get("creators") or []) if a).strip()
        or str(info.get("uploader") or "").strip()
        or str(info.get("channel") or "").strip()
        or "未知歌手"
    )
    album = (
        str(info.get("album") or "").strip()
        or str(info.get("playlist_title") or "").strip()
        or ""
    )
    return GenericMeta(
        title=str(info.get("title") or "").strip() or "未命名",
        artist=artist,
        duration=float(info.get("duration") or 0.0),
        webpage_url=str(info.get("webpage_url") or url),
        extractor=str(info.get("extractor_key") or info.get("extractor") or ""),
        album=album,
    )
