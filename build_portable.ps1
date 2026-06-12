param(
    [string]$Name = "KoupreyBootFlash",
    [switch]$Console
)

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = Join-Path $ProjectDir "dist"

$WindowedFlag = if (-not $Console) { "--windowed" } else { "" }

$IconPath = Join-Path $ProjectDir "assets\icons\Kouprey Logo Variations.ico"
$PyInstallerArgs = @(
    "--onefile"
    $WindowedFlag
    "--name", $Name
    "--distpath", $DistDir
    "--add-data", "themes;themes"
    "--add-data", "assets;assets"
    "--add-data", "lucide\lucide.zip;lucide"
    "--add-data", "lucide\__init__.py;lucide"
    "--hidden-import", "PyQt6.QtSvg"
    "--icon", $IconPath
    "--clean"
    "--noconfirm"
    "main.py"
)

Write-Host "=== Building portable EXE: $Name ===" -ForegroundColor Cyan
Write-Host "PyInstaller arguments:" -ForegroundColor Gray
$PyInstallerArgs -join " " | Write-Host
Write-Host ""

$env:PYTHONOPTIMIZE = "1"

python -m PyInstaller @PyInstallerArgs

if ($LASTEXITCODE -eq 0) {
    $exePath = Join-Path $DistDir "${Name}.exe"
    Write-Host ""
    Write-Host "=== BUILD SUCCESS ===" -ForegroundColor Green
    Write-Host "Portable EXE: $exePath" -ForegroundColor Green
    $size = (Get-Item $exePath).Length / 1MB
    Write-Host "Size: $([math]::Round($size, 1)) MB" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "=== BUILD FAILED ===" -ForegroundColor Red
    exit 1
}
