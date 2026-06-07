@echo off
set mode1=MICROSOFT
set mode2=GRUB2
set tail=MODE
cd /d "%~dp0"
if exist sstr64.efi (
move /y bootx64.efi temp64.efi
move /y bootia32.efi temp86.efi
move /y sstr64.efi bootx64.efi
move /y sstr86.efi bootia32.efi
move /y grubx64.efi temp.efi
)
cls
echo.
if exist "[%mode2%_%tail%]" (move /y "[%mode2%_%tail%]" "[%mode1%_%tail%]">nul) else (echo.>"[%mode1%_%tail%]")
echo %mode1% BOOT ENABLED!
echo.
pause
exit