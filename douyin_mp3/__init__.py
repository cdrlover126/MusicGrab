"""乐取 (MusicGrab): 多平台音轨批量提取为车机可播放的 MP3。

双引擎解析（内置解析器 + yt-dlp 通用引擎）、智能代理路由、多格式转码，
并内置 yt-dlp / ffmpeg 的版本自检与在线升级能力。
"""

__version__ = "1.7.0"
APP_NAME = "乐取"
APP_NAME_EN = "MusicGrab"
APP_ID = "com.cdrlover.musicgrab"
APP_TITLE = f"{APP_NAME} {APP_NAME_EN}"

from . import winconsole

winconsole.apply()


def _apply_component_overlay() -> None:
    """让「组件升级」安装的外置 yt-dlp / ffmpeg 优先生效。

    必须在任何 ``import yt_dlp`` 之前完成——项目里 yt-dlp 是懒加载的，
    因此只要在进入业务逻辑前调用即可。失败时静默降级回内置组件。
    """
    try:
        from .updater import apply_overlay

        apply_overlay()
    except Exception:
        pass


_apply_component_overlay()
