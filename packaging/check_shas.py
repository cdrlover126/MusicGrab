"""校验发布产物与文档中的 SHA256 是否一致（开发工具）。"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

root = pathlib.Path(".")
zip_path = root / "dist" / "release" / "MusicGrab-v1.8.0-win-x64.zip"
exe_path = root / "dist" / "MusicGrab.exe"


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
