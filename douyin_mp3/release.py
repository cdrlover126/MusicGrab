"""程序自身的版本检查与新版下载。

与 ``updater.py``（组件自愈：yt-dlp / ffmpeg）不同，这里管的是**本程序自己**
的版本：

1. **检查**：拉取一份版本清单（``latest.json``），和当前版本比较
2. **下载**：把官方发布包下到本地，校验 SHA256
3. **交接**：解压到程序目录旁边，提示用户**手动覆盖**正在运行的程序

为什么不自动覆盖？——正在运行的 exe 无法安全重写自己（文件被占用），而且
"悄悄替换用户正在用的程序"风险太大。这里只做到"下好、校验好、告诉你放哪"。

版本清单是一个 JSON 文件，格式：

.. code-block:: json

    {
      "version": "1.8.1",
      "url": "https://example.com/MusicGrab-v1.8.1-win-x64.zip",
      "sha256": "64 位十六进制校验值",
      "notes": "修复了……",
      "published_at": "2026-10-30",
      "size": 106000000
    }
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from . import __version__
from .tls import requests_verify

#: 版本清单地址（留空 = 不检查程序自身版本）
#: 可以用环境变量 ``MUSICGRAB_UPDATE_MANIFEST`` 覆盖，方便测试或临时换源。
RELEASE_MANIFEST_URL = ""
ENV_MANIFEST = "MUSICGRAB_UPDATE_MANIFEST"

HTTP_TIMEOUT = 12
DOWNLOAD_TIMEOUT = 600

#: 下载进度回调：(已下载字节, 总字节)
ProgressCallback = Callable[[int, int], None]


class ReleaseError(RuntimeError):
    """版本检查 / 下载过程中的可读错误。"""


@dataclass(frozen=True)
class ReleaseInfo:
    """一次版本检查的结果。"""

    version: str
    url: str = ""
    sha256: str = ""
    notes: str = ""
    published_at: str = ""
    size: int = 0

    @property
    def summary(self) -> str:
        return self.version or "未知版本"


def manifest_url() -> str:
    """版本清单地址（环境变量优先）。"""
    return (os.environ.get(ENV_MANIFEST) or RELEASE_MANIFEST_URL or "").strip()


def normalize_version(text: str) -> str:
    """去掉 ``v`` 前缀与空白，只留数字点分形式。"""
    value = (text or "").strip()
    value = re.sub(r"^[vV]", "", value)
    match = re.match(r"(\d+(?:\.\d+)*)", value)
    return match.group(1) if match else ""


def version_tuple(text: str) -> tuple[int, ...]:
    """版本号转成数字元组，便于比较。"""
    normalized = normalize_version(text)
    if not normalized:
        return (0,)
    return tuple(int(part) for part in normalized.split("."))


def is_newer_release(latest: str, current: str | None = None) -> bool:
    """``latest`` 是否比当前程序版本新。"""
    latest_norm = normalize_version(latest)
    if not latest_norm:
        return False
    now = current if current is not None else __version__
    if not normalize_version(now):
        return True
    return version_tuple(latest_norm) > version_tuple(now)


def parse_manifest(text: str) -> ReleaseInfo:
    """解析版本清单（JSON；同时兼容 ``version=1.8.1`` 这种纯文本）。"""
    raw = (text or "").strip()
    if not raw:
        raise ReleaseError("版本清单为空")
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ReleaseError(f"版本清单不是合法 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise ReleaseError("版本清单格式不正确（应为 JSON 对象）")
        return ReleaseInfo(
            version=normalize_version(str(data.get("version", ""))),
            url=str(data.get("url", "") or "").strip(),
            sha256=str(data.get("sha256", "") or "").strip().lower(),
            notes=str(data.get("notes", "") or "").strip(),
            published_at=str(data.get("published_at", "") or "").strip(),
            size=int(data.get("size", 0) or 0),
        )
    # 纯文本兜底：version=1.8.1 / url=... / sha256=...
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        fields[key.strip().lower()] = value.strip()
    if "version" not in fields:
        raise ReleaseError("版本清单里没有 version 字段")
    return ReleaseInfo(
        version=normalize_version(fields.get("version", "")),
        url=fields.get("url", ""),
        sha256=fields.get("sha256", "").lower(),
        notes=fields.get("notes", ""),
        published_at=fields.get("published_at", ""),
    )


def fetch_release(url: str | None = None) -> ReleaseInfo:
    """拉取版本清单。"""
    target = (url or manifest_url()).strip()
    if not target:
        raise ReleaseError("未配置版本清单地址")
    try:
        response = requests.get(
            target,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": f"MusicGrab/{__version__}"},
            verify=requests_verify(),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ReleaseError(f"检查新版本失败：{exc}") from exc
    return parse_manifest(response.text)


def download_release(
    info: ReleaseInfo,
    dest_dir: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """下载发布包并校验 SHA256，返回本地文件路径。"""
    if not info.url:
        raise ReleaseError("版本清单里没有下载地址")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = info.url.rsplit("/", 1)[-1] or f"MusicGrab-{info.version}.zip"
    target = dest_dir / name
    digest = hashlib.sha256()
    done = 0
    try:
        with requests.get(
            info.url,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
            headers={"User-Agent": f"MusicGrab/{__version__}"},
            verify=requests_verify(),
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or info.size or 0)
            with target.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total)
    except requests.RequestException as exc:
        target.unlink(missing_ok=True)
        raise ReleaseError(f"下载失败：{exc}") from exc
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise ReleaseError(f"写入文件失败：{exc}") from exc

    actual = digest.hexdigest()
    if info.sha256 and actual.lower() != info.sha256.lower():
        target.unlink(missing_ok=True)
        raise ReleaseError("校验失败：下载文件的 SHA256 与官方公布值不一致")
    return target


def _safe_target(root: Path, name: str) -> Path:
    """解析压缩包内的目标路径，并阻止路径穿越（zip slip）。"""
    target = (root / name).resolve()
    base = root.resolve()
    if base != target and base not in target.parents:
        raise ReleaseError(f"压缩包内含非法路径：{name}")
    return target


def extract_release(zip_path: Path, target_dir: Path) -> Path:
    """把发布包解压到 ``target_dir``，返回解压后的目录。"""
    zip_path = Path(zip_path)
    target_dir = Path(target_dir)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise ReleaseError(f"压缩包内含非法路径：{name}")
                out = _safe_target(target_dir, name)
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, out.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile as exc:
        raise ReleaseError(f"解压失败：{exc}") from exc
    except OSError as exc:
        raise ReleaseError(f"解压失败：{exc}") from exc
    return target_dir


def program_dir() -> Path:
    """程序所在目录（源码运行时为项目根目录）。"""
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).resolve().parent
        except OSError:
            pass
    return Path(__file__).resolve().parents[1]


def staged_release_dir(version: str) -> Path:
    """新版程序解压到哪里（程序目录旁；不可写则退回用户目录）。"""
    name = f"MusicGrab-{normalize_version(version) or 'new'}"
    target = program_dir() / name
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".mg_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return target
    except OSError:
        fallback = Path.home() / "Music" / name
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
