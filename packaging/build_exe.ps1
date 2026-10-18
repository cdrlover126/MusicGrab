# DouyinMP3 打包脚本（Windows）
# 用法: 在项目根目录执行  powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "[1/4] 生成图标..."
python packaging\make_icons.py

Write-Host "[2/4] PyInstaller 打包..."
pyinstaller --noconfirm --clean `
  --onefile --windowed `
  --name DouyinMP3 `
  --icon assets\icon.ico `
  --version-file packaging\version_info.txt `
  --collect-binaries imageio_ffmpeg `
  --collect-all yt_dlp `
  --hidden-import douyin_mp3 `
  --hidden-import douyin_mp3.gui `
  --hidden-import mutagen.id3 `
  douyin_mp3\app.py

if (Test-Path "dist\DouyinMP3.exe") {
  $size = (Get-Item "dist\DouyinMP3.exe").Length / 1MB
  Write-Host ("[3/4] 生成成功: dist\DouyinMP3.exe ({0:N1} MB)" -f $size)
} else {
  throw "打包失败，未生成 dist\DouyinMP3.exe"
}

Write-Host "[4/4] 可选：构建 MSIX 应用商店安装包..."
powershell -ExecutionPolicy Bypass -File packaging\msix\make_msix.ps1
