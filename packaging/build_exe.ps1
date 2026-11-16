# DouyinMP3 打包脚本（Windows）
# 用法: 在项目根目录执行  powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
#
# 产出两种形态（同一个入口，两个产物）：
#   1. 单文件版  dist\MusicGrab.exe              —— 普通用户，双击即用
#   2. 目录版    dist\onedir\MusicGrab\          —— 启动快、组件可放在 exe 旁边、整目录可拷贝
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$common = @(
  "--noconfirm", "--clean", "--windowed",
  "--name", "MusicGrab",
  "--icon", "assets\icon.ico",
  "--add-data", "assets\icon.png;assets",
  "--version-file", "packaging\version_info.txt",
  "--collect-all", "imageio_ffmpeg",
  "--collect-all", "yt_dlp",
  "--hidden-import", "musicgrab",
  "--hidden-import", "musicgrab.gui",
  "--hidden-import", "mutagen.id3",
  "musicgrab\app.py"
)

Write-Host "[1/5] 生成图标..."
python packaging\make_icons.py

Write-Host "[2/5] PyInstaller 打包（单文件版）..."
python -m PyInstaller @common --onefile --workpath build\onefile --distpath dist

Write-Host "[3/5] PyInstaller 打包（目录版）..."
python -m PyInstaller @common --onedir --workpath build\onedir --distpath dist\onedir

if (Test-Path "dist\MusicGrab.exe") {
  $size = (Get-Item "dist\MusicGrab.exe").Length / 1MB
  Write-Host ("[4/5] 单文件版生成成功: dist\MusicGrab.exe ({0:N1} MB)" -f $size)
} else {
  throw "打包失败，未生成 dist\MusicGrab.exe"
}

if (Test-Path "dist\onedir\MusicGrab\MusicGrab.exe") {
  $dirSize = (Get-ChildItem "dist\onedir\MusicGrab" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
  Write-Host ("      目录版生成成功: dist\onedir\MusicGrab\ ({0:N1} MB)" -f $dirSize)
} else {
  throw "打包失败，未生成 dist\onedir\MusicGrab\MusicGrab.exe"
}

Write-Host "[5/5] 可选：构建 MSIX 应用商店安装包..."
powershell -ExecutionPolicy Bypass -File packaging\msix\make_msix.ps1
