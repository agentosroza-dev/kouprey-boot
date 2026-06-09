param(
    [int]$DiskNumber = 2
)

Write-Host "============================================"
Write-Host "  Kouprey Boot - Flash + Deploy Tool"
Write-Host "============================================"
Write-Host ""
Write-Host "This will ERASE ALL DATA on Disk #${DiskNumber}!"
Write-Host "Press Ctrl+C to cancel, or Enter to continue..."
Write-Host ""
pause

# Step 1: Flash
Write-Host ""
Write-Host "[Step 1/3] Flashing Ventoy to Disk #${DiskNumber}..."
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_ENABLE_HIGHDPI_SCALING = "0"
python.exe "$PSScriptRoot\flash_headless.py" -disk $DiskNumber
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Flash step failed. Check log." -ForegroundColor Red
    exit 1
}
Write-Host "OK: Flash complete!" -ForegroundColor Green

# Step 2: Deploy Vimix theme
Write-Host ""
Write-Host "[Step 2/3] Deploying Vimix theme..."
python.exe "$PSScriptRoot\flash_headless.py" -deploy -disk $DiskNumber -theme Vimix
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Deploy Vimix step failed." -ForegroundColor Red
    exit 1
}
Write-Host "OK: Vimix theme deployed!" -ForegroundColor Green

# Step 3: Rename data partition to KOUPREYDATA
Write-Host ""
Write-Host "[Step 3/3] Renaming data partition to KOUPREYDATA..."
python.exe "$PSScriptRoot\flash_headless.py" -rename -disk $DiskNumber
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: Rename step failed. You can rename the drive manually." -ForegroundColor Yellow
} else {
    Write-Host "OK: Drive renamed to KOUPREYDATA!" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================"
Write-Host "  ALL DONE!"
Write-Host "============================================"
Write-Host "  USB drive #${DiskNumber} is ready."
Write-Host "  Final theme: Vimix"
Write-Host "  Drive label: KOUPREYDATA"
Write-Host ""
Write-Host "  Reboot and set BIOS to boot from USB."
Write-Host "============================================"
pause
