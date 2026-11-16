"""生成 / 更新程序自身的版本清单 latest.json（开发工具）。

用法:
    python packaging/make_manifest.py --url <发布包直链> [--sha256 <校验值>] [--notes "说明"]

产物: dist/release/latest.json

把这个文件放到任意静态托管（Gitea raw、对象存储、博客附件……），
再把它的地址填进 ``musicgrab/release.py`` 的 ``RELEASE_MANIFEST_URL``
（或运行时设置环境变量 ``MUSICGRAB_UPDATE_MANIFEST``），
程序启动后就能提示"有新版本"并提供一键下载。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
REL = ROOT / "dist" / "release"
VERSION = "1.8.0"


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="生成版本清单 latest.json")
    parser.add_argument("--url", default="", help="发布包直链（可留空，之后再填）")
    parser.add_argument("--sha256", default="", help="发布包 SHA256（留空则自动计算本地发布包）")
    parser.add_argument("--notes", default="", help="更新说明")
    parser.add_argument("--version", default=VERSION, help="版本号")
    parser.add_argument(
        "--zip", default="", help="本地发布包路径（用于自动算 SHA256 与大小）"
    )
    args = parser.parse_args()

    manifest_path = REL / "latest.json"
    data = {}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}

    zip_path = pathlib.Path(args.zip) if args.zip else REL / f"MusicGrab-v{args.version}-win-x64.zip"
    sha = args.sha256
    size = 0
    if zip_path.exists():
        if not sha:
            sha = sha256_of(zip_path)
        size = zip_path.stat().st_size

    data.update(
        {
            "version": args.version,
            "url": args.url or data.get("url", ""),
            "sha256": (sha or data.get("sha256", "")).lower(),
            "notes": args.notes or data.get("notes", ""),
            "published_at": data.get("published_at") or date.today().isoformat(),
            "size": size or data.get("size", 0),
        }
    )
    REL.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("已写入:", manifest_path)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
