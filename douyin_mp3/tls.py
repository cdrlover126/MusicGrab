"""TLS 证书包的稳定副本与兜底。

PyInstaller 单文件版会把 CA 证书包解压到 ``%TEMP%\\_MEIxxxxxx\\certifi\\cacert.pem``。
这个临时目录可能被「清理临时文件」类工具删掉、或因进程被强制结束而残缺，
于是 requests 抛出：

    Could not find a suitable TLS CA certificate bundle, invalid path: ...

对策：启动时把证书包复制一份到覆盖层目录（``%LOCALAPPDATA%\\MusicGrab``），
请求时优先用 certifi 自带路径，失效则改用这份稳定副本。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import overlay_root

#: 覆盖层里保存的 CA 证书包文件名
CA_BUNDLE_NAME = "cacert.pem"


def bundled_ca_path() -> str:
    """certifi 自带的证书包路径（取不到时返回空串）。"""
    try:
        import certifi

        return certifi.where() or ""
    except Exception:  # noqa: BLE001
        return ""


def ca_bundle_available(path: str | os.PathLike[str] | None = None) -> bool:
    """指定的证书包路径是否真实存在。"""
    target = str(path) if path else bundled_ca_path()
    if not target:
        return False
    try:
        return os.path.isfile(target)
    except OSError:
        return False


def saved_ca_path(directory: Path | None = None) -> Path | None:
    """覆盖层里那份证书包副本的路径（不存在返回 None）。"""
    base = directory if directory is not None else overlay_root()
    target = Path(base) / CA_BUNDLE_NAME
    return target if ca_bundle_available(target) else None


def save_ca_bundle(directory: Path | None = None) -> Path | None:
    """把 certifi 的证书包复制到覆盖层，返回副本路径（失败返回 None）。"""
    source = bundled_ca_path()
    if not ca_bundle_available(source):
        return None
    base = directory if directory is not None else overlay_root()
    target = Path(base) / CA_BUNDLE_NAME
    try:
        base.mkdir(parents=True, exist_ok=True)
        if not ca_bundle_available(target):
            shutil.copyfile(source, target)
        return target
    except OSError:
        return None


def requests_verify(directory: Path | None = None) -> bool | str:
    """给 requests 的 ``verify`` 参数。

    - 证书包正常时返回 True（沿用 requests 默认行为）
    - certifi 路径失效时返回覆盖层里那份副本的路径
    - 都没有时仍返回 True，让 requests 抛出它自己的错误信息
    """
    if ca_bundle_available():
        return True
    fallback = saved_ca_path(directory)
    if fallback is not None:
        return str(fallback)
    return True
