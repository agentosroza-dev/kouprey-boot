@echo off
set mode1=MICROSOFT
set mode2=GRUB2
set tail=MODE
cd /d "%~dp0"
if exist temp64.efi (
move /y bootx64.efi sstr64.efi
move /y bootia32.efi sstr86.efi
move /y temp64.efi bootx64.efi
move /y temp86.efi bootia32.efi
move /y temp.efi grubx64.efi
)
cls
echo.
if exist "[%mode1%_%tail%]" (move /y "[%mode1%_%tail%]" "[%mode2%_%tail%]">nul) else (echo.>"[%mode2%_%tail%]")
echo %mode2% BOOT ENABLED!
echo.
pause
exit