"""本地媒体文件发现：把拖入的文件 / 文件夹展开成可处理的媒体列表。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .config import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

#: 允许作为本地输入的扩展名
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

#: 单次拖放 / 选择最多展开的文件数，避免误拖整个磁盘导致界面卡死
DEFAULT_LIMIT = 2000

#: 扫描时跳过的目录（大小写不敏感）
_IGNORED_DIRS = {
    "$recycle.bin",
    "system volume information",
    "__macosx",
    ".git",
    ".svn",
    "node_modules",
}


def is_media_file(path: Path) -> bool:
    """判断路径是否为受支持的本地音视频文件。"""
    try:
        return path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
    except OSError:
        return False


def _walk_media(root: Path, limit: int) -> tuple[list[Path], bool]:
    """递归扫描文件夹；``limit`` 为本次最多返回的文件数。"""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".") and name.lower() not in _IGNORED_DIRS
        )
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = Path(dirpath) / name
            if path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            if len(found) >= limit:
                return found, True
            found.append(path)
    return found, False


def collect_media_paths(
    paths: Iterable[Path | str], *, limit: int = DEFAULT_LIMIT
) -> tuple[list[Path], bool]:
    """展开文件与文件夹，按首次出现顺序去重。

    返回 ``(媒体文件列表, 是否因数量上限被截断)``。文件夹会递归扫描，
    跳过隐藏目录、回收站、``__MACOSX``、``node_modules`` 等。
    """
    if limit <= 0:
        raise ValueError("limit 必须为正整数")

    files: list[Path] = []
    seen: set[str] = set()
    truncated = False

    def key_of(path: Path) -> str:
        return os.path.normcase(os.path.abspath(str(path)))

    def add(path: Path) -> None:
        nonlocal truncated
        key = key_of(path)
        if key in seen:
            return
        if len(files) >= limit:
            truncated = True
            return
        seen.add(key)
        files.append(path)

    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            remaining = limit - len(files)
            if remaining <= 0:
                truncated = True
                break
            found, cut = _walk_media(path, remaining)
            for item in found:
                add(item)
            truncated = truncated or cut
        elif is_media_file(path):
            add(path)

    return files, truncated
