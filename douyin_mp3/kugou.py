from __future__ import annotations

import hashlib
import html as html_module
import re
from dataclasses import dataclass
from typing import Any

import requests

from .config import REQUEST_TIMEOUT
from .cookies import load_requests_cookies
from .proxy import build_session


KUGOU_DOMAINS = ("kugou.com",)

KUGOU_HASH_RE = re.compile(r"hash=([A-Fa-f0-9]{32})", re.IGNORECASE)
KUGOU_MID_RE = re.compile(r"/(?:song|share|play)/#hash=([A-Fa-f0-9]{32})", re.IGNORECASE)
SCRIPT_HASH_RE = re.compile(r'"hash"\s*:\s*"([A-Fa-f0-9]{32})"', re.IGNORECASE)

# 形如 https://www.kugou.com/song/#g5jy4e47 （# 后为 encode_album_audio_id）
KUGOU_SONG_ECID_RE = re.compile(
    r"kugou\.com/(?:song|play|share)/?(?:[?#].*?)?#([A-Za-z0-9]{6,})", re.IGNORECASE
)
KUGOU_MIXSONG_ECID_RE = re.compile(
    r"kugou\.com/mixsong/([A-Za-z0-9]{6,})\.html", re.IGNORECASE
)

SMARTY_DATA_RE = re.compile(r"dataFromSmarty\s*=\s*(\[.*?\])\s*[,;]", re.DOTALL)

AUDIO_MY_RE = re.compile(r'<audio[^>]+id=["\']myAudio["\'][^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
AUDIO_SRC_RE = re.compile(r'<audio[^>]+class=["\'][^"\']*music[^"\']*["\'][^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
AUDIO_ANY_RE = re.compile(r'<audio[^>]+src=["\']([^"\']+\.mp3[^"\']*)["\']', re.IGNORECASE)
DATA_HASH_RE = re.compile(r'data-hash=["\']([A-Fa-f0-9]{32})["\']', re.IGNORECASE)
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)
OG_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
SONG_NAME_RE = re.compile(r'"songname"\s*:\s*"([^"]+)"', re.IGNORECASE)
SINGER_NAME_RE = re.compile(r'"singername"\s*:\s*"([^"]+)"', re.IGNORECASE)
ALBUM_NAME_RE = re.compile(r'"album_name"\s*:\s*"([^"]+)"|"albumname"\s*:\s*"([^"]+)"', re.IGNORECASE)
DURATION_RE = re.compile(r'"duration"\s*:\s*(\d+)', re.IGNORECASE)


class KugouParseError(RuntimeError):
    pass


@dataclass
class KugouInfo:
    hash: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    play_url: str = ""
    share_url: str = ""
    extra: dict[str, Any] | None = None


def _clean(s: Any) -> str:
    if s is None:
        return ""
    text = str(s).strip()
    text = html_module.unescape(text)
    return text


def _resolve_ecid_url(url: str) -> str:
    """将形如 /song/#<ecid> 的链接归一化为可服务端渲染出 hash 的 mixsong 页面。

    酷狗新版歌曲页 https://www.kugou.com/song/#<ecid> 的 <audio> 由 JS 动态填充，
    但同一 ecid 也可通过 https://www.kugou.com/mixsong/<ecid>.html 访问，后者页面中
    带有 data-hash / dataFromSmarty，可直接提取 hash。
    """
    m = KUGOU_SONG_ECID_RE.search(url)
    if m:
        return f"https://www.kugou.com/mixsong/{m.group(1)}.html"
    return url


def _extract_hash(url: str, html: str) -> str:
    m = KUGOU_HASH_RE.search(url)
    if m:
        return m.group(1).lower()
    m = KUGOU_MID_RE.search(url)
    if m:
        return m.group(1).lower()
    m = DATA_HASH_RE.search(html)
    if m:
        return m.group(1).lower()
    m = SCRIPT_HASH_RE.search(html)
    if m:
        return m.group(1).lower()
    raise KugouParseError(f"无法从酷狗链接提取歌曲hash: {url}")


def _extract_smarty(html: str) -> dict[str, Any]:
    """提取页面中的 dataFromSmarty 元数据（JSON 数组首项）。"""
    m = SMARTY_DATA_RE.search(html)
    if not m:
        return {}
    raw = m.group(1)
    try:
        import json

        data = json.loads(raw)
    except Exception:
        return {}
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


def _extract_title_artist(html: str) -> tuple[str, str]:
    title = ""
    artist = ""

    smarty = _extract_smarty(html)
    if smarty:
        title = _clean(smarty.get("song_name") or smarty.get("audio_name"))
        artist = _clean(smarty.get("author_name"))
        if not title:
            audio_name = _clean(smarty.get("audio_name"))
            if audio_name:
                if " - " in audio_name:
                    left, right = audio_name.split(" - ", 1)
                    artist = artist or left.strip()
                    title = right.strip()
                else:
                    title = audio_name
        if title and artist:
            return title, artist

    m = SONG_NAME_RE.search(html)
    if m:
        title = title or _clean(m.group(1))
    m = SINGER_NAME_RE.search(html)
    if m:
        artist = artist or _clean(m.group(1))

    if not title:
        m = OG_TITLE_RE.search(html)
        if m:
            t = _clean(m.group(1))
            if "-" in t:
                parts = [p.strip() for p in t.split("-", 1)]
                if len(parts) == 2 and not artist:
                    artist = parts[0]
                    title = parts[1]
                else:
                    title = t
            else:
                title = t
    if not title:
        m = TITLE_RE.search(html)
        if m:
            t = _clean(m.group(1))
            t = re.sub(r"_酷狗音乐.*$", "", t).strip()
            if "-" in t and not artist:
                parts = [p.strip() for p in t.split("-", 1)]
                artist = parts[0]
                title = parts[1]
            else:
                title = t

    return title, artist


class KugouClient:
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
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.kugou.com/",
            }
        )
        load_requests_cookies(
            self.session,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
        )

    def fetch_info(self, url: str) -> KugouInfo:
        fetch_url = _resolve_ecid_url(url)
        resp = self.session.get(fetch_url, allow_redirects=True, timeout=self.timeout)
        resp.raise_for_status()
        html = resp.text
        final_url = resp.url

        play_url = ""
        m = AUDIO_MY_RE.search(html)
        if m:
            play_url = html_module.unescape(m.group(1).strip())
        if not play_url:
            m = AUDIO_SRC_RE.search(html)
            if m:
                play_url = html_module.unescape(m.group(1).strip())
        if not play_url:
            m = AUDIO_ANY_RE.search(html)
            if m:
                play_url = html_module.unescape(m.group(1).strip())

        smarty = _extract_smarty(html)

        song_hash = _clean(smarty.get("hash")).lower() if smarty else ""
        try:
            song_hash = song_hash or _extract_hash(final_url, html)
        except KugouParseError:
            m = DATA_HASH_RE.search(html)
            if m:
                song_hash = m.group(1).lower()
            if not song_hash:
                hashes = re.findall(r'[A-Fa-f0-9]{32}', html)
                if hashes:
                    song_hash = hashes[0].lower()

        # try mobile API to get direct mp3
        if not play_url and song_hash:
            try:
                m_session = requests.Session()
                m_session.headers.update(
                    {
                        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
                        "Referer": "https://m.kugou.com/",
                    }
                )
                for cookie in self.session.cookies:
                    m_session.cookies.set(cookie.name, cookie.value, domain=cookie.domain)
                mr = m_session.get(f"https://m.kugou.com/app/i/getSongInfo.php?cmd=playInfo&hash={song_hash}", timeout=self.timeout)
                if mr.ok:
                    try:
                        mj = mr.json()
                        for key in ("url", "play_url", "mp3Url", "fileUrl"):
                            val = mj.get(key)
                            if isinstance(val, str) and val.startswith("http") and ".mp3" in val:
                                play_url = val
                                break
                        if not play_url:
                            pay_type = mj.get("pay_type")
                            privilege = mj.get("privilege")
                            if str(pay_type) not in ("", "0", "None") or (isinstance(privilege, int) and privilege >= 10):
                                raise KugouParseError(
                                    "该酷狗歌曲为VIP/付费歌曲，未登录无法获取播放地址（可使用 --cookies 或 --cookies-from-browser 提供已登录酷狗的 cookies 重试）"
                                )
                    except KugouParseError:
                        raise
                    except Exception:
                        pass
            except KugouParseError:
                raise
            except Exception:
                pass

        title, artist = _extract_title_artist(html)
        album = ""

        m = ALBUM_NAME_RE.search(html)
        if m:
            album = _clean(m.group(1) or m.group(2))

        duration_ms = 0
        if smarty:
            try:
                duration_ms = int(smarty.get("timelength") or 0)
            except (TypeError, ValueError):
                duration_ms = 0
        if not duration_ms:
            m = DURATION_RE.search(html)
            if m:
                try:
                    duration_ms = int(m.group(1)) * 1000
                except ValueError:
                    duration_ms = 0

        if play_url and play_url.startswith("http"):
            return KugouInfo(
                hash=song_hash or play_url.split("/")[-1].split(".")[0],
                title=title or "酷狗音乐",
                artist=artist or "未知歌手",
                album=album or "酷狗音乐",
                duration_ms=duration_ms,
                play_url=play_url,
                share_url=final_url,
                extra={"source": "audio_tag"},
            )

        if not song_hash:
            raise KugouParseError(f"无法从酷狗链接提取歌曲hash: {url}")

        api_url = "https://wwwapi.kugou.com/yy/index.php"
        for mid_seed in (song_hash + "1234567890abcdef", song_hash):
            params = {
                "r": "play/getdata",
                "hash": song_hash,
                "album_id": "",
                "dfid": "",
                "mid": hashlib.md5(mid_seed.encode()).hexdigest(),
                "platid": "4",
            }
            try:
                api_resp = self.session.get(api_url, params=params, timeout=self.timeout)
                data = api_resp.json()
            except Exception:
                continue

            if isinstance(data, dict):
                data = data.get("data") or data

            play_url = ""
            if isinstance(data, dict):
                play_url = (
                    data.get("play_url")
                    or data.get("play_url_backup")
                    or data.get("url")
                    or data.get("audio_url")
                    or ""
                )
                if not title:
                    title = _clean(data.get("audio_name") or data.get("song_name") or data.get("name"))
                if not artist:
                    artist = _clean(data.get("author_name") or data.get("singer_name"))
                if not album:
                    album = _clean(data.get("album_name"))
                if not duration_ms:
                    try:
                        duration_ms = int(data.get("timelength") or data.get("duration") or 0)
                        if duration_ms < 10000:
                            duration_ms = duration_ms * 1000
                    except Exception:
                        pass

            if play_url and play_url.startswith("http"):
                break

        if not play_url or not play_url.startswith("http"):
            raise KugouParseError("酷狗未返回可播放音频地址（可能需要登录或接口已变动）")

        return KugouInfo(
            hash=song_hash,
            title=title or song_hash,
            artist=artist or "未知歌手",
            album=album or "酷狗音乐",
            duration_ms=duration_ms,
            play_url=play_url,
            share_url=final_url,
            extra={"source": "api"},
        )
