"""组件自检与在线升级（yt-dlp / ffmpeg）。

背景：PyInstaller 打包后，yt-dlp 与 ffmpeg 都被「冻结」进 exe，上游更新不会
自动生效。yt-dlp 几乎每周发版，原因就是目标站点一改版它就得跟着修；用户手里
的旧程序因此会**静默失效**——表现是「昨天还能下的链接今天下不到了」，而用户
完全不知道原因，更不可能自己升级一个绿色单文件 exe。

本模块提供一套「运行时自愈」方案：

1. **启动自检**：比对内置组件版本与 PyPI 上的最新稳定版
2. **提示升级**：把「有新版本」主动告诉用户（呈现形式由 GUI 决定）
3. **在线升级**：从 PyPI / 国内镜像下载官方 wheel，解压出新版组件
4. **覆盖生效**：yt-dlp 走自定义 import finder 优先加载外置副本；
   ffmpeg 走路径优先级 + ``IMAGEIO_FFMPEG_EXE`` 环境变量

覆盖层目录（Windows 默认 ``%LOCALAPPDATA%\\MusicGrab\\``）::

    yt_dlp/     外置 yt-dlp 包（import 时优先于内置）
    ffmpeg/     外置 ffmpeg 可执行文件
    state.json  升级记录、已忽略版本、偏好设置

设计约束：

* 全部逻辑不依赖 PySide6，可独立单测（见 ``tests/test_updater.py``）
* 任何一步失败都必须**退回内置组件**，绝不能让程序因为升级机制而打不开
* 只访问 PyPI 与国内镜像，不上传任何本地信息
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import requests

from . import __version__
from .config import overlay_root as _config_overlay_root
from .tls import requests_verify, save_ca_bundle

ProgressCallback = Callable[[int, int], None]

# ── 网络参数 ────────────────────────────────────────────────
PYPI_JSON_TEMPLATE = "https://pypi.org/pypi/{pkg}/json"

#: 国内镜像的 PEP 503 简单索引（pypi.org 在国内冷启动可能 30s+，镜像通常 0.3s）
MIRROR_SIMPLE_TEMPLATES = (
    "https://pypi.tuna.tsinghua.edu.cn/simple/{pkg}/",
    "https://mirrors.aliyun.com/pypi/simple/{pkg}/",
    "https://mirrors.cloud.tencent.com/pypi/simple/{pkg}/",
    "https://repo.huaweicloud.com/repository/pypi/simple/{pkg}/",
)

USER_AGENT = f"MusicGrab/{__version__} (+https://pypi.org/project/yt-dlp/)"
HTTP_TIMEOUT = 12
DOWNLOAD_TIMEOUT = 180

# ── 组件标识 ────────────────────────────────────────────────
YTDLP = "yt-dlp"
FFMPEG = "ffmpeg"

COMPONENT_LABELS = {YTDLP: "yt-dlp（通用解析引擎）", FFMPEG: "ffmpeg（转码内核）"}

#: 只接受纯数字版本号（排除 .dev / .rc / b1 之类的预发布版本）
_STABLE_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")
_VERSION_ASSIGN_RE = re.compile(r"""__version__\s*=\s*['"]([^'"]+)['"]""")
_FFMPEG_VERSION_RE = re.compile(r"ffmpeg version ([0-9][0-9.]*)")


class UpdateError(RuntimeError):
    """升级流程中的可读错误。"""


# ── 覆盖层路径 ──────────────────────────────────────────────
#: 覆盖层根目录（保留这个名字，测试里会 monkeypatch）
overlay_root = _config_overlay_root


def ytdlp_overlay_dir() -> Path:
    """外置 yt-dlp 包目录。"""
    return overlay_root() / "yt_dlp"


def ffmpeg_overlay_dir() -> Path:
    """外置 ffmpeg 目录。"""
    return overlay_root() / "ffmpeg"


def state_path() -> Path:
    """状态文件路径。"""
    return overlay_root() / "state.json"


def _ensure_root() -> Path:
    root = overlay_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


# ── 状态持久化 ──────────────────────────────────────────────
def load_state() -> dict:
    """读取状态文件（不存在或损坏时返回默认结构）。"""
    default = {"auto_check": True, "ignored": {}, "installed": {}}
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    if not isinstance(data, dict):
        return default
    for key, value in default.items():
        data.setdefault(key, value)
    return data


def save_state(state: dict) -> None:
    """写入状态文件（失败不影响主流程）。"""
    try:
        _ensure_root()
        state_path().write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ── 版本比较 ────────────────────────────────────────────────
def version_tuple(text: str) -> tuple[int, ...]:
    """把版本号转成可比较的元组。

    ``2026.10.26`` -> ``(2026, 10, 26)``

    注意：yt-dlp 的版本号是「年.月.日」，字符串比较会出错——
    ``"2026.10.26" < "2026.08.19"`` 为真（因为 ``'1' < '0'`` 为假，
    实则 ``'1' > '0'``），所以必须按数字元组比较。
    """
    parts = re.findall(r"\d+", text or "")
    return tuple(int(p) for p in parts) or (0,)


def is_stable_version(text: str) -> bool:
    """是否是稳定版（排除 .dev0 / rc1 之类的预发布版本）。"""
    return bool(_STABLE_VERSION_RE.match((text or "").strip()))


def is_newer(latest: str, current: str) -> bool:
    """`latest` 是否比 `current` 新。"""
    if not latest:
        return False
    if not current:
        return True
    return version_tuple(latest) > version_tuple(current)


# ── 本地组件探测 ────────────────────────────────────────────
def _locate_package_dir(name: str) -> Path | None:
    """定位某个包的源码目录（不执行模块代码）。

    顺序：覆盖层 → PyInstaller 冻结目录 → 常规 site-packages。

    注意冻结目录这一支**不能要求存在 ``__init__.py``**：打包时若只用了
    ``--collect-binaries``，磁盘上只有 ``binaries/`` 子目录，Python 源码在 PYZ 里，
    此时仍需返回该目录（版本号文本不在盘上时会走 import 兜底）。
    """
    overlay = overlay_root() / name
    if (overlay / "__init__.py").exists():
        return overlay
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / name
        if frozen.is_dir():
            return frozen
    try:
        import importlib.util

        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    for location in (spec.submodule_search_locations or []) if spec else []:
        path = Path(location)
        if path.is_dir():
            return path
    return None


def _read_module_version(package_dir: Path | None) -> str:
    """从包里读 ``__version__``（纯文本解析，无副作用）。

    版本号可能放在不同位置，必须逐个尝试：

    * ``version.py``      —— yt-dlp（``__init__.py`` 里是 re-export）
    * ``_definitions.py`` —— imageio-ffmpeg（同样只 re-export）
    * ``__init__.py``     —— 兜底
    """
    if not package_dir:
        return ""
    for name in ("version.py", "_definitions.py", "__init__.py"):
        try:
            text = (package_dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _VERSION_ASSIGN_RE.search(text)
        if match:
            return match.group(1)
    return ""


def current_ytdlp_version() -> str:
    """当前实际生效的 yt-dlp 版本（含外置覆盖层）。"""
    return _read_module_version(_locate_package_dir("yt_dlp"))


def current_imageio_ffmpeg_version() -> str:
    """内置 imageio-ffmpeg 包版本（ffmpeg 二进制由它提供）。

    文本读取拿不到时（例如源码只在 PYZ 里），退回 import 读属性。
    """
    version = _read_module_version(_locate_package_dir("imageio_ffmpeg"))
    if version:
        return version
    try:
        import imageio_ffmpeg

        return str(getattr(imageio_ffmpeg, "__version__", "") or "")
    except Exception:
        return ""


def overlay_ffmpeg_exe() -> Path | None:
    """外置 ffmpeg 可执行文件（存在才返回）。"""
    directory = ffmpeg_overlay_dir()
    if not directory.is_dir():
        return None
    for candidate in sorted(directory.glob("ffmpeg*.exe")):
        if candidate.is_file():
            return candidate
    return None


def current_ffmpeg_exe() -> str | None:
    """当前会实际被调用的 ffmpeg 路径（外置优先，其次系统，再次内置）。"""
    overlay = overlay_ffmpeg_exe()
    if overlay:
        return str(overlay)
    try:
        from .converter import find_ffmpeg

        return find_ffmpeg()
    except Exception:
        found = shutil.which("ffmpeg")
        return found


def current_ffmpeg_version() -> str:
    """当前 ffmpeg 的版本号（如 ``7.1``）。"""
    exe = current_ffmpeg_exe()
    if not exe:
        return ""
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    match = _FFMPEG_VERSION_RE.search((proc.stdout or "") + (proc.stderr or ""))
    return match.group(1) if match else ""


# ── 远端版本查询 ────────────────────────────────────────────
@dataclass(frozen=True)
class RemotePackage:
    """远端包信息。"""

    package: str
    version: str
    url: str
    sha256: str
    size: int
    source: str


def _http_get(url: str, timeout: int = HTTP_TIMEOUT) -> requests.Response:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        verify=requests_verify(overlay_root()),
    )
    response.raise_for_status()
    return response


def _wheel_tag() -> str:
    """当前平台的 wheel 标签。"""
    if sys.platform == "win32":
        return "py3-none-win_amd64" if sys.maxsize > 2**32 else "py3-none-win32"
    if sys.platform == "darwin":
        return "py3-none-macosx_11_0_arm64" if sys.platform == "darwin" else ""
    machine = os.uname().machine if hasattr(os, "uname") else "x86_64"
    return "py3-none-manylinux2014_x86_64" if machine in ("x86_64", "AMD64") else ""


def _pick_wheel(urls: list[dict], package: str, version: str) -> dict | None:
    """从 PyPI JSON 的 ``urls`` 中挑出目标 wheel。

    注意：PyPI 上的**发行名**是 ``yt-dlp``，但**文件名**用的是下划线
    ``yt_dlp-2026.10.26-py3-none-any.whl``，匹配时必须做归一化。
    """
    tag = _wheel_tag()
    prefix = f"{package.replace('-', '_')}-{version}-"
    candidates = [
        item
        for item in urls
        if item.get("packagetype") == "bdist_wheel"
        and str(item.get("filename", "")).startswith(prefix)
    ]
    if not candidates:
        return None
    for want in (tag, "py3-none-any"):
        for item in candidates:
            if item.get("filename", "").endswith(f"-{want}.whl"):
                return item
    return candidates[0]


def _fetch_from_pypi_json(package: str) -> RemotePackage | None:
    """官方 JSON 接口：版本号与下载地址一次拿全。"""
    try:
        data = _http_get(PYPI_JSON_TEMPLATE.format(pkg=package)).json()
    except (requests.RequestException, ValueError):
        return None
    version = str(data.get("info", {}).get("version", ""))
    if not is_stable_version(version):
        return None
    item = _pick_wheel(list(data.get("urls") or []), package, version)
    if not item:
        return None
    return RemotePackage(
        package=package,
        version=version,
        url=str(item.get("url", "")),
        sha256=str((item.get("digests") or {}).get("sha256", "")),
        size=int(item.get("size") or 0),
        source="pypi.org",
    )


_LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>')


def _parse_simple_index(html: str, package: str, base_url: str) -> RemotePackage | None:
    """解析 PEP 503 简单索引，挑出最新的稳定版 wheel。

    两个坑：

    1. 索引里包含 dev/rc 预发布版本，必须按「纯数字版本号」过滤
    2. 索引**不是按版本号排序**的——``2026.10.26`` 排在 ``2026.8.19`` 前面，
       所以必须按数字元组取最大值，不能取最后一个
    """
    pattern = re.compile(
        rf"^{re.escape(package.replace('-', '_'))}-(\d+(?:\.\d+)*)-(.+)\.whl$"
    )
    best: tuple[tuple[int, ...], str, str, str] | None = None
    for href, filename in _LINK_RE.findall(html):
        match = pattern.match(filename.strip())
        if not match:
            continue
        version = match.group(1)
        if not is_stable_version(version):
            continue
        url = urljoin(base_url, href)
        sha = ""
        if "#sha256=" in url:
            url, sha = url.split("#sha256=", 1)
        key = version_tuple(version)
        if best is None or key > best[0]:
            best = (key, version, url, sha)
    if best is None:
        return None
    host = base_url.split("/")[2]
    return RemotePackage(
        package=package,
        version=best[1],
        url=best[2],
        sha256=best[3],
        size=0,
        source=host,
    )


def _fetch_from_mirror(package: str, base_url: str) -> RemotePackage | None:
    """国内镜像的 PEP 503 简单索引。"""
    try:
        html = _http_get(base_url).text
    except requests.RequestException:
        return None
    return _parse_simple_index(html, package, base_url)


def fetch_remote_package(package: str) -> RemotePackage:
    """查询远端最新稳定版：官方 JSON 优先，失败自动切国内镜像。"""
    remote = _fetch_from_pypi_json(package)
    if remote:
        return remote
    errors: list[str] = []
    for template in MIRROR_SIMPLE_TEMPLATES:
        base = template.format(pkg=package)
        try:
            remote = _fetch_from_mirror(package, base)
        except requests.RequestException as exc:
            errors.append(f"{base.split('/')[2]}: {exc}")
            continue
        if remote:
            return remote
        errors.append(f"{base.split('/')[2]}: 无可用 wheel")
    raise UpdateError(
        "无法获取组件版本信息（已尝试 pypi.org 与国内镜像）：" + "；".join(errors[:4])
    )


# ── 自检结果 ────────────────────────────────────────────────
@dataclass(frozen=True)
class ComponentStatus:
    """单个组件的自检结果。"""

    key: str
    label: str
    current: str
    latest: str
    has_update: bool
    source: str = ""
    error: str = ""
    detail: str = ""

    def summary(self) -> str:
        """一句话描述（用于横幅与对话框）。"""
        name = self.label.split("（")[0]
        if self.key == FFMPEG:
            return f"{name} 组件 {self.current or '未知'} → {self.latest}"
        return f"{name} {self.current or '未知'} → {self.latest}"


def check_ytdlp() -> ComponentStatus:
    """检查 yt-dlp 是否有新版本。"""
    current = current_ytdlp_version()
    try:
        remote = fetch_remote_package("yt-dlp")
    except UpdateError as exc:
        return ComponentStatus(YTDLP, COMPONENT_LABELS[YTDLP], current, "", False, error=str(exc))
    return ComponentStatus(
        YTDLP,
        COMPONENT_LABELS[YTDLP],
        current,
        remote.version,
        is_newer(remote.version, current),
        source=remote.source,
    )


def check_ffmpeg() -> ComponentStatus:
    """检查 ffmpeg 是否有新版本。

    ffmpeg 本身不在 PyPI 上，本程序内置的二进制来自 ``imageio-ffmpeg``，
    因此以该包的最新版作为「ffmpeg 可更新」的判据：新版 imageio-ffmpeg
    通常会附带更新的 ffmpeg 构建。真正升级时才会把新二进制装下来，
    因此这里的版本号是**组件版本**而非 ffmpeg 自身版本。
    """
    current_pkg = current_imageio_ffmpeg_version()
    ffmpeg_ver = current_ffmpeg_version()
    detail = f"内置 ffmpeg {ffmpeg_ver}" if ffmpeg_ver else ""
    try:
        remote = fetch_remote_package("imageio-ffmpeg")
    except UpdateError as exc:
        return ComponentStatus(
            FFMPEG, COMPONENT_LABELS[FFMPEG], current_pkg, "", False, error=str(exc), detail=detail
        )
    return ComponentStatus(
        FFMPEG,
        COMPONENT_LABELS[FFMPEG],
        current_pkg,
        remote.version,
        is_newer(remote.version, current_pkg),
        source=remote.source,
        detail=detail,
    )


def check_components() -> list[ComponentStatus]:
    """检查全部可升级组件。"""
    return [check_ytdlp(), check_ffmpeg()]


# ── 下载与安装 ──────────────────────────────────────────────
def download_file(
    url: str,
    dest: Path,
    *,
    expected_sha256: str = "",
    on_progress: ProgressCallback | None = None,
) -> Path:
    """流式下载文件并校验 sha256。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    done = 0
    try:
        with requests.get(
            url,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            verify=requests_verify(overlay_root()),
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            with tmp.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"下载失败：{exc}") from exc
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"写入文件失败：{exc}") from exc

    actual = digest.hexdigest()
    if expected_sha256 and actual.lower() != expected_sha256.lower():
        tmp.unlink(missing_ok=True)
        raise UpdateError("校验失败：下载文件的 SHA256 与官方公布值不一致")
    tmp.replace(dest)
    return dest


def _safe_target(root: Path, name: str) -> Path:
    """解析压缩包内的目标路径，并阻止路径穿越（zip slip）。"""
    target = (root / name).resolve()
    base = root.resolve()
    if base != target and base not in target.parents:
        raise UpdateError(f"压缩包内含非法路径：{name}")
    return target


def extract_members(
    wheel: Path,
    prefix: str,
    dest: Path,
    *,
    predicate: Callable[[str], bool] | None = None,
) -> list[Path]:
    """从 wheel 中按前缀提取文件到 ``dest``，返回写出的文件列表。

    前缀会被**剥掉**：``yt_dlp/version.py`` 会被写成 ``dest/version.py``，
    这样解压结果本身就是包目录，可以直接整体替换覆盖层。
    """
    written: list[Path] = []
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not name.startswith(prefix):
                continue
            if predicate and not predicate(name):
                continue
            relative = name[len(prefix) :]
            if not relative:
                continue
            target = _safe_target(dest, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(target)
    return written


def _replace_dir(new_dir: Path, target: Path) -> None:
    """用 ``new_dir`` 原子替换 ``target``（失败自动回滚）。"""
    backup = target.with_name(target.name + ".bak")
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        target.replace(backup)
    try:
        new_dir.replace(target)
    except OSError:
        if backup.exists():
            backup.replace(target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def install_ytdlp(wheel: Path) -> Path:
    """把 wheel 里的 ``yt_dlp`` 包安装到覆盖层。返回安装目录。"""
    root = _ensure_root()
    staging = root / "yt_dlp.new"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    try:
        extract_members(wheel, "yt_dlp/", staging)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"解压 yt-dlp 失败：{exc}") from exc
    if not (staging / "__init__.py").exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("下载的安装包中没有 yt_dlp 包，已放弃安装")
    target = ytdlp_overlay_dir()
    _replace_dir(staging, target)
    return target


def install_ffmpeg(wheel: Path) -> Path:
    """把 wheel 里的 ffmpeg 可执行文件安装到覆盖层。返回可执行文件路径。"""
    root = _ensure_root()
    staging = root / "ffmpeg.new"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    try:
        extract_members(
            wheel,
            "imageio_ffmpeg/binaries/",
            staging,
            predicate=lambda n: n.lower().endswith(".exe"),
        )
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"解压 ffmpeg 失败：{exc}") from exc
    exes = list(staging.glob("*.exe"))
    if not exes:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("下载的安装包中没有 ffmpeg 可执行文件，已放弃安装")
    exe = exes[0]
    # 校验二进制确实可运行，避免装上损坏的文件
    try:
        proc = subprocess.run(
            [str(exe), "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"新 ffmpeg 无法运行：{exc}") from exc
    if not _FFMPEG_VERSION_RE.search((proc.stdout or "") + (proc.stderr or "")):
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("新 ffmpeg 未返回版本信息，已放弃安装")

    target_dir = ffmpeg_overlay_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    for old in target_dir.glob("ffmpeg*.exe"):
        old.unlink(missing_ok=True)
    final = target_dir / exe.name
    exe.replace(final)
    shutil.rmtree(staging, ignore_errors=True)
    return final


# ── 覆盖生效 ────────────────────────────────────────────────
class _ExternalPackageFinder:
    """让外置包目录优先于 PyInstaller 冻结模块被导入。

    PyInstaller 的 ``FrozenImporter`` 挂在 ``sys.meta_path`` 上，优先级高于
    ``sys.path``，所以单纯 ``sys.path.insert(0, ...)`` 并不保险；这里显式
    插一个 finder，把 ``yt_dlp`` 及其子模块的解析导向外置目录。
    """

    def __init__(self, root: str, package: str) -> None:
        self.root = root
        self.package = package

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
        if fullname != self.package and not fullname.startswith(self.package + "."):
            return None
        from importlib.machinery import PathFinder

        search = path if path is not None else [self.root]
        spec = PathFinder.find_spec(fullname, search)
        if spec is None or not spec.origin:
            return None
        try:
            origin = Path(spec.origin).resolve()
        except OSError:
            return None
        root = Path(self.root).resolve()
        if root != origin and root not in origin.parents:
            return None
        return spec


def _install_ytdlp_finder() -> bool:
    """安装外置 yt-dlp 的 import finder。"""
    overlay = ytdlp_overlay_dir()
    if not (overlay / "__init__.py").exists():
        return False
    if "yt_dlp" in sys.modules:
        # 已经导入过（可能是内置版本），本次会话无法再切换
        return False
    # 搜索根目录必须是「包含 yt_dlp/ 的那一层」，否则会去找 yt_dlp/yt_dlp/
    root = str(overlay_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    if not any(isinstance(f, _ExternalPackageFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _ExternalPackageFinder(root, "yt_dlp"))
    return True


def apply_ffmpeg_overlay() -> bool:
    """让外置 ffmpeg 生效：设置环境变量 + 供 find_ffmpeg 优先选择。"""
    exe = overlay_ffmpeg_exe()
    if not exe:
        return False
    os.environ["IMAGEIO_FFMPEG_EXE"] = str(exe)
    return True


def apply_overlay() -> dict:
    """在程序启动早期调用：让覆盖层里的组件优先生效。

    必须在任何 ``import yt_dlp`` 之前执行（项目里 yt-dlp 是懒加载的，
    因此只要在进入业务逻辑前调用即可）。

    同时会把 CA 证书包复制一份到覆盖层：打包版解压出来的证书包在
    ``%TEMP%\\_MEIxxxxxx`` 里，被清理工具删掉就会导致所有 HTTPS 请求失败。
    """
    result = {"ytdlp": False, "ffmpeg": False}
    try:
        result["ytdlp"] = _install_ytdlp_finder()
    except Exception:
        result["ytdlp"] = False
    try:
        result["ffmpeg"] = apply_ffmpeg_overlay()
    except Exception:
        result["ffmpeg"] = False
    try:
        save_ca_bundle(overlay_root())
    except Exception:
        pass
    return result


# ── 升级编排 ────────────────────────────────────────────────
def plan_for(status: ComponentStatus) -> tuple[str, str] | None:
    """把自检结果映射到 (PyPI 包名, 安装方式)。"""
    if status.key == YTDLP:
        return "yt-dlp", "ytdlp"
    if status.key == FFMPEG:
        return "imageio-ffmpeg", "ffmpeg"
    return None


def upgrade_component(
    status: ComponentStatus,
    *,
    on_progress: ProgressCallback | None = None,
) -> str:
    """下载并安装单个组件的更新，返回可读的结果描述。"""
    mapping = plan_for(status)
    if mapping is None:
        raise UpdateError(f"未知组件：{status.key}")
    package, kind = mapping
    remote = fetch_remote_package(package)
    if not is_newer(remote.version, status.current):
        raise UpdateError(f"{status.label.split('（')[0]} 已是最新版本 {remote.version}")

    suffix = ".whl"
    wheel = overlay_root() / f"{package}-{remote.version}{suffix}"
    download_file(remote.url, wheel, expected_sha256=remote.sha256, on_progress=on_progress)

    if kind == "ytdlp":
        install_ytdlp(wheel)
        result = f"yt-dlp 已更新到 {remote.version}"
    else:
        exe = install_ffmpeg(wheel)
        apply_ffmpeg_overlay()
        result = f"ffmpeg 已更新到 {current_ffmpeg_version() or remote.version}（{exe.name}）"

    wheel.unlink(missing_ok=True)
    state = load_state()
    state.setdefault("installed", {})[status.key] = remote.version
    state.setdefault("ignored", {}).pop(status.key, None)
    save_state(state)
    return result


def ignore_version(key: str, version: str) -> None:
    """记录「忽略此版本」，下次自检不再提示。"""
    state = load_state()
    state.setdefault("ignored", {})[key] = version
    save_state(state)


def is_ignored(key: str, version: str) -> bool:
    """该版本是否已被用户忽略。"""
    return str(load_state().get("ignored", {}).get(key, "")) == str(version)
