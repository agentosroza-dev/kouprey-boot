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
Write-Host "[Step 1/5] Flashing Ventoy to Disk #${DiskNumber}..."
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
Write-Host "[Step 2/5] Deploying Vimix theme..."
python.exe "$PSScriptRoot\flash_headless.py" -deploy -disk $DiskNumber -theme Vimix
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Deploy Vimix step failed." -ForegroundColor Red
    exit 1
}
Write-Host "OK: Vimix theme deployed!" -ForegroundColor Green

# Step 3: Deploy Bigsur theme
Write-Host ""
Write-Host "[Step 3/5] Deploying Bigsur theme..."
python.exe "$PSScriptRoot\flash_headless.py" -deploy -disk $DiskNumber -theme Bigsur
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Deploy Bigsur step failed." -ForegroundColor Red
    exit 1
}
Write-Host "OK: Bigsur theme deployed!" -ForegroundColor Green

# Step 4: Deploy Window11 theme (final)
Write-Host ""
Write-Host "[Step 4/5] Deploying Window11 theme (final)..."
python.exe "$PSScriptRoot\flash_headless.py" -deploy -disk $DiskNumber -theme Window11
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Deploy Window11 step failed." -ForegroundColor Red
    exit 1
}
Write-Host "OK: Window11 theme deployed!" -ForegroundColor Green

# Step 5: Rename data partition to KOUPREYDATA
Write-Host ""
Write-Host "[Step 5/5] Renaming data partition to KOUPREYDATA..."
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
Write-Host "  Final theme: Window11"
Write-Host "  Drive label: KOUPREYDATA"
Write-Host ""
Write-Host "  Reboot and set BIOS to boot from USB."
Write-Host "============================================"
pause
