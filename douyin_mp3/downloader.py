from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import requests

from .config import DOWNLOAD_TIMEOUT, MOBILE_UA, PC_UA

ProgressCallback = Callable[[int, int], None]


class DownloadError(RuntimeError):
    pass


def download_file(
    url: str,
    dest: Path,
    *,
    session: requests.Session | None = None,
    progress: ProgressCallback | None = None,
    timeout: int = DOWNLOAD_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> Path:
    sess = session or requests.Session()
    hdrs = {"User-Agent": PC_UA, "Referer": "https://www.douyin.com/"}
    if headers:
        hdrs.update(headers)
    try:
        with sess.get(url, headers=hdrs, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            tmp.replace(dest)
            return dest
    except requests.RequestException as exc:
        raise DownloadError(f"下载失败: {exc}") from exc


def download_with_retry(
    url: str,
    dest: Path,
    *,
    attempts: int = 3,
    session: requests.Session | None = None,
    progress: ProgressCallback | None = None,
    fallback_urls: list[str] | None = None,
) -> Path:
    urls = [url] + list(fallback_urls or [])
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        for candidate in urls:
            try:
                return download_file(candidate, dest, session=session, progress=progress)
            except (DownloadError, OSError) as exc:
                last_error = exc
                if dest.exists():
                    dest.unlink(missing_ok=True)
                time.sleep(min(2 * attempt, 6))
    raise DownloadError(f"重试 {attempts} 次后仍失败: {last_error}")
