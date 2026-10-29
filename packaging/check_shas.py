"""校验发布产物与文档中的 SHA256 是否一致（开发工具）。"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

root = pathlib.Path(".")
zip_path = root / "dist" / "release" / "MusicGrab-v1.8.0-win-x64.zip"
folder_zip = root / "dist" / "release" / "MusicGrab-v1.8.0-win-x64-folder.zip"
exe_path = root / "dist" / "MusicGrab.exe"
manifest_path = root / "dist" / "release" / "latest.json"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


zip_sha = sha256(zip_path)
exe_sha = sha256(exe_path)
print("zip ", zip_sha)
print("exe ", exe_sha)

ok = True
sums = (root / "dist" / "release" / "SHA256SUMS.txt").read_text(encoding="utf-8")
if zip_sha not in sums:
    print("!! SHA256SUMS.txt 与实际 zip 不一致")
    ok = False
else:
    print("SHA256SUMS.txt OK")

if folder_zip.exists():
    folder_sha = sha256(folder_zip)
    print("folder", folder_sha)
    if folder_sha not in sums:
        print("!! SHA256SUMS.txt 缺少目录版")
        ok = False
    notes_text = (root / "docs/releases/v1.8.0.md").read_text(encoding="utf-8")
    if folder_sha not in notes_text:
        print("!! 发布说明未记录目录版 SHA")
        ok = False
else:
    print("（未构建目录版，跳过检查）")

if manifest_path.exists():
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print("latest.json 版本:", manifest.get("version"))
    if manifest.get("version") != "1.8.0":
        print("!! 版本清单里的版本号不对")
        ok = False
else:
    print("!! 缺少 latest.json")
    ok = False

with zipfile.ZipFile(zip_path) as zf:
    notes = zf.read("发布说明.md").decode("utf-8")
    usage = zf.read("使用说明.txt").decode("utf-8")

if exe_sha in notes:
    print("包内发布说明的 exe SHA OK")
else:
    print("!! 包内发布说明的 exe SHA 不一致")
    ok = False

if "见发布包同级的 SHA256SUMS.txt" in notes:
    print("包内发布说明的 zip SHA 为自引用提示 OK")
else:
    print("!! 包内发布说明缺少 zip 自引用提示")
    ok = False

if "【转换报告】" in usage:
    print("包内使用说明含转换报告说明 OK")
else:
    print("!! 包内使用说明缺少转换报告说明")
    ok = False

for name in (
    "docs/releases/v1.8.0.md",
    "docs/blog/CSDN-技术博文.md",
    "docs/blog/CSDN-发布信息.md",
):
    text = (root / name).read_text(encoding="utf-8")
    has_zip = zip_sha in text
    has_exe = exe_sha in text
    print(f"{name}: zip={has_zip} exe={has_exe}")
    ok = ok and has_zip and has_exe

print("结论:", "全部通过" if ok else "存在问题")
raise SystemExit(0 if ok else 1)
