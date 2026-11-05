# scripts/make-covers.ps1
# 一键重做博客封面：生成(Qwen-Image) + 压缩
#
# 用法（在仓库根目录 D:\notes\blog-hexo 下）：
#   .\scripts\make-covers.ps1                          # 全部封面
#   .\scripts\make-covers.ps1 -Only cover-hono         # 只做指定几张（逗号分隔）
#   .\scripts\make-covers.ps1 -Key "sk-xxxx"           # 直接传 key，不用设环境变量
#
# 前提：Node.js、Python + Pillow（pip install Pillow）

param(
    [string]$Key = "",
    [string]$Only = "",
    [switch]$SkipResize
)

$ErrorActionPreference = "Stop"

# 1. 设置 key
if ($Key -ne "") {
    $env:SF_KEY = $Key
}
if (-not $env:SF_KEY) {
    Write-Host "错误：没提供 SiliconFlow key。" -ForegroundColor Red
    Write-Host "两种方式任选一种："
    Write-Host "  1) .\scripts\make-covers.ps1 -Key `"sk-xxxx`""
    Write-Host "  2) `$env:SF_KEY = `"sk-xxxx`"  然后  .\scripts\make-covers.ps1"
    exit 1
}

# 2. 生成
Write-Host "`n=== 生成封面（Qwen-Image）===" -ForegroundColor Cyan
$nodeArgs = @("scripts/generate-covers.js")
if ($Only -ne "") { $nodeArgs += @("--only", $Only) }
& node @nodeArgs
if ($LASTEXITCODE -ne 0) { Write-Host "生成失败" -ForegroundColor Red; exit 1 }

# 3. 压缩
if (-not $SkipResize) {
    Write-Host "`n=== 压缩封面到 900 宽 ===" -ForegroundColor Cyan
    $pyArgs = @("scripts/resize-covers.py")
    if ($Only -ne "") { $pyArgs += @("--only", $Only) }
    & python @pyArgs
    if ($LASTEXITCODE -ne 0) { Write-Host "压缩失败（是不是没装 Pillow？pip install Pillow）" -ForegroundColor Red; exit 1 }
}

# 4. 提示
Write-Host "`n=== 完成 ===" -ForegroundColor Green
Write-Host "接下来："
Write-Host "  npx hexo clean; npx hexo generate     # 本地验证"
Write-Host "  git add source/img; git commit -m `"update covers`"; git push"
