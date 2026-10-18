# 构建 MSIX 安装包（面向 Microsoft Store / 企业分发）
# 需要 Windows 10/11 SDK (MakeAppx.exe)。脚本会自动探测 SDK 路径。
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$stage = Join-Path $root "build\msix_stage"
$pkg = Join-Path $root "dist\DouyinMP3_1.0.0.0_x64.msix"

if (-not (Test-Path (Join-Path $root "dist\DouyinMP3.exe"))) {
  throw "请先运行 packaging\build_exe.ps1 生成 dist\DouyinMP3.exe"
}

# 查找 MakeAppx
$makeappx = Get-ChildItem "$env:ProgramFiles (x86)\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue |
  Sort-Object FullName -Descending | Select-Object -First 1
if (-not $makeappx) {
  $makeappx = Get-ChildItem "$env:ProgramFiles\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
}
if (-not $makeappx) {
  Write-Warning "未找到 MakeAppx.exe，请安装 Windows 10/11 SDK 后重试。exe 已可直接分发。"
  exit 1
}

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path "$stage\assets" -Force | Out-Null

Copy-Item (Join-Path $root "dist\DouyinMP3.exe") $stage
Copy-Item (Join-Path $PSScriptRoot "AppxManifest.xml") $stage
Copy-Item (Join-Path $PSScriptRoot "*.png") "$stage\assets"
# SplashScreen 单独复制
Copy-Item (Join-Path $PSScriptRoot "Square150x150Logo.png") "$stage\assets\SplashScreen.png" -Force

& $makeappx.FullName pack /d $stage /p $pkg /o
if ($LASTEXITCODE -eq 0) {
  Write-Host "MSIX 生成成功: $pkg"
  Write-Host "提交 Store 前请用 '测试签名证书' 签名，或在 Partner Center 提交时由商店签名。"
} else {
  throw "MakeAppx 打包失败"
}
