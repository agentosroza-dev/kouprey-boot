"""
Batch flash all ISOs from D:\\ISO to a real USB drive one by one.

Usage:
    python batch_flash_usb.py --disk 2

Each ISO is flashed to disk #N. After each flash the script pauses so you can
unplug, test the USB, then plug it back and press Enter for the next ISO.
"""

import os
import sys
import time
import subprocess
import re
import ctypes
import platform
import argparse

ISO_DIR = r'D:\ISO'
BAR_WIDTH = 40


def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _elevate():
    script = os.path.abspath(sys.argv[0])
    args = ' '.join(f'"{a}"' if ' ' in a else a for a in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(
        None, 'runas', sys.executable, f'"{script}" {args}',
        os.path.dirname(script), 1
    )


def log(msg: str):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}')


def progress_bar(pct: int, status: str = ''):
    pct = max(0, min(100, pct))
    filled = int(BAR_WIDTH * pct / 100)
    empty = BAR_WIDTH - filled
    pct_text = f'{pct}%'
    pct_len = len(pct_text)
    left_fill = (BAR_WIDTH - pct_len) // 2
    right_fill = BAR_WIDTH - left_fill - pct_len
    bar = '[' + '=' * left_fill + pct_text + '=' * right_fill + ']'
    line = f'\r{bar}  {status}'
    sys.stdout.write(line.ljust(120))
    sys.stdout.flush()


def get_iso_type(iso_path: str) -> str:
    """Return 'windows', 'winpe', or 'linux'."""
    found = set()
    try:
        with open(iso_path, 'rb') as f:
            f.seek(0x8001)
            if f.read(5) == b'CD001':
                f.seek(0)
                for _ in range(16):
                    chunk = f.read(8388608)
                    if not chunk:
                        break
                    for m in (b'install.wim', b'INSTALL.WIM',
                              b'install.esd', b'INSTALL.ESD',
                              b'boot.wim', b'BOOT.WIM'):
                        if m in chunk:
                            found.add('install' if b'install' in m.lower() else 'boot')
    except Exception:
        pass
    if 'install' in found:
        return 'windows'
    if 'boot' in found:
        return 'winpe'
    return 'linux'


def clean_disk(disk_number: int) -> bool:
    log('Cleaning disk...')

    # Close Explorer windows and unmount volumes first
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'$dl = (Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue '
             f'| Where-Object {{ $_.DriveLetter }} | Select-Object -First 1).DriveLetter; '
             f'if ($dl) {{ '
             f'  $shell = New-Object -ComObject Shell.Application; '
             f'  $shell.Windows() | ForEach-Object {{ '
             f'    try {{ if ($_.Document.Folder.Self.Path -eq "$dl`:\\") {{ $_.Quit() }} }} catch {{}} }}; '
             f'  Remove-PartitionAccessPath -DiskNumber {disk_number} '
             f'    -PartitionNumber (Get-Partition -DiskNumber {disk_number} '
             f'      -ErrorAction SilentlyContinue | Where-Object {{ $_.DriveLetter }} '
             f'      | Select-Object -First 1 -ExpandProperty PartitionNumber) '
             f"    -AccessPath \"$dl`:\\\" -ErrorAction SilentlyContinue "
             f'}}'],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass
    time.sleep(2)

    # Try Clear-Disk first (works better on removable media)
    log('Attempting Clear-Disk via PowerShell...')
    try:
        cr = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'Clear-Disk -Number {disk_number} -RemoveData -RemoveOEM '
             f'-PassThru -ErrorAction SilentlyContinue'],
            capture_output=True, text=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if cr.returncode == 0:
            log('Clear-Disk succeeded')
            time.sleep(2)
            return True
        err = cr.stderr.strip() or cr.stdout.strip()[:200]
        log(f'Clear-Disk failed: {err}')
    except Exception as e:
        log(f'Clear-Disk error: {e}')

    for attempt in range(3):
        log(f'diskpart clean attempt {attempt + 1}/3')
        script = (
            f'select disk {disk_number}\n'
            f'attributes disk clear readonly\n'
            f'clean\n'
            f'exit\n'
        )
        r = subprocess.run(
            ['diskpart'], input=script, capture_output=True, text=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = r.stdout.strip()
        if 'Access is denied' in out or 'not supported on removable media' in out:
            log('diskpart clean unavailable, zeroing MBR directly...')
            if zero_mbr_fallback(disk_number):
                log('MBR zeroed successfully')
                time.sleep(2)
                return True
            log('ERROR: Cannot clean disk - close programs accessing this drive')
            return False
        if 'DiskPart has encountered an error' in out or r.returncode != 0:
            log(f'Attempt {attempt + 1} failed, retrying...')
            time.sleep(3)
            continue
        log('diskpart clean completed')
        time.sleep(2)
        return True
    log('diskpart clean failed after 3 attempts')

    # Last resort
    log('Attempting MBR zero as last resort...')
    if zero_mbr_fallback(disk_number):
        log('MBR zeroed successfully')
        time.sleep(2)
        return True
    return False


def zero_mbr_fallback(disk_number: int) -> bool:
    """Zero out the first 10MB to remove partition table on removable media."""
    device = rf'\\.\PhysicalDrive{disk_number}'
    try:
        ps = (
            f"$dev = @\"\n{device}\n\"@; "
            f"$stream = [System.IO.File]::Open($dev, "
            f"[System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, "
            f"[System.IO.FileShare]::ReadWrite); "
            f"try {{ "
            f"  $buf = New-Object byte[] 10485760; "
            f"  $stream.Write($buf, 0, $buf.Length); "
            f"}} finally {{ $stream.Close() }} "
            f"Write-Output 'DONE'"
        )
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception as e:
        log(f'MBR zero failed: {e}')
        return False


def hide_drive_ui(drive_letter: str):
    try:
        ps = (
            f"$vol = Get-Volume -DriveLetter {drive_letter} -ErrorAction SilentlyContinue; "
            f"$vol | Out-Null; "
            f"$s = New-Object -ComObject Shell.Application; "
            f"$s.Windows() | ForEach-Object {{ "
            f"try {{ if ($_.Document.Folder.Self.Path -eq '{drive_letter}:\\') {{ $_.Quit() }} }} "
            f"catch {{}} }}"
        )
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def raw_write_iso(iso_path: str, disk_number: int, progress=None):
    device = rf'\\.\PhysicalDrive{disk_number}'
    ps = (
        f"$path = @\"\n{iso_path}\n\"@; "
        f"$dev = @\"\n{device}\n\"@; "
        f"$size = (Get-Item $path).Length; "
        f"$stream = [System.IO.File]::Open($dev, "
        f"[System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, "
        f"[System.IO.FileShare]::ReadWrite); "
        f"try {{ "
        f"  $iso = [System.IO.File]::OpenRead($path); "
        f"  try {{ "
        f"    $buf = New-Object byte[] 1048576; "
        f"    $total = 0; "
        f"    while (($read = $iso.Read($buf, 0, $buf.Length)) -gt 0) {{ "
        f"      $stream.Write($buf, 0, $read); "
        f"      $total += $read; "
        f"      Write-Output (\"P:\" + [int]($total * 100 / $size)); "
        f"    }} "
        f"  }} finally {{ $iso.Close() }} "
        f"}} finally {{ $stream.Close() }} "
        f"Write-Output \"DONE\""
    )
    r = subprocess.run(
        ['powershell', '-NoProfile', '-Command', ps],
        capture_output=True, text=True, timeout=7200,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith('P:'):
            pct = int(line.split(':')[1])
            if progress:
                progress(pct)
    return r.returncode == 0


def flash_windows_iso(iso_path: str, disk_number: int, progress=None):
    time.sleep(1)
    script = (
        f'select disk {disk_number}\n'
        f'clean\n'
        f'create partition primary\n'
        f'select partition 1\n'
        f'active\n'
        f'format fs=fat32 label="WINUSB" quick\n'
        f'assign\n'
        f'exit\n'
    )
    if progress:
        progress(5)
    r = subprocess.run(
        ['diskpart'], input=script, capture_output=True, text=True, timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if 'DiskPart has encountered an error' in r.stdout or r.returncode != 0:
        return False
    if progress:
        progress(15)
    time.sleep(2)

    pr = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f'$p = Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue '
         f'| Where-Object {{ $_.DriveLetter -and $_.DriveLetter -ne [char]0 }} '
         f'| Select-Object -First 1; '
         f'if ($p) {{ Write-Output $p.DriveLetter }} else {{ Write-Output \'\' }}'],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    drive_letter = pr.stdout.strip()[:1]
    if not drive_letter or not drive_letter.isalpha():
        return False
    if progress:
        progress(20)

    iso_escaped = iso_path.replace("'", "''")
    mr = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f'$iso = Mount-DiskImage -ImagePath \'{iso_escaped}\' -PassThru; '
         f'if ($iso) {{ Write-Output \'OK:\' + $iso.ImagePath }} else {{ Write-Output \'FAIL\' }}'],
        capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if 'FAIL' in mr.stdout or mr.returncode != 0:
        return False
    if progress:
        progress(25)
    time.sleep(2)

    vr = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         '$vol = Get-Volume | Where-Object { $_.DriveType -eq \'CD-ROM\' -and $_.DriveLetter } '
         '| Sort-Object DriveLetter -Descending | Select-Object -First 1; '
         'if ($vol) { Write-Output $vol.DriveLetter } else { Write-Output \'N\' }'],
        capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    iso_letter = vr.stdout.strip()[:1]
    if not iso_letter or not iso_letter.isalpha() or iso_letter.upper() == 'N':
        return False

    if progress:
        progress(30)
    cr = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f'robocopy "{iso_letter}:\\" "{drive_letter}:\\" /E /R:1 /W:1 '
         f'/XF install.wim install.esd /NFL /NDL /NJH /NJS /nc /ns /np'],
        capture_output=True, text=True, timeout=3600,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if cr.returncode >= 8:
        return False
    if progress:
        progress(60)

    wim_path = f'{iso_letter}:\\sources\\install.wim'
    esd_path = f'{iso_letter}:\\sources\\install.esd'

    wc = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f'if (Test-Path "{wim_path}") {{ Write-Output "WIM" }} else {{ Write-Output "NO" }}'],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    has_wim = 'WIM' in wc.stdout

    ec = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f'if (Test-Path "{esd_path}") {{ Write-Output "ESD" }} else {{ Write-Output "NO" }}'],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    has_esd = 'ESD' in ec.stdout

    if has_wim:
        sc = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'(Get-Item "{wim_path}").Length'],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        wim_size = int(sc.stdout.strip()) if sc.stdout.strip().isdigit() else 0
        if wim_size > 4 * 1024 * 1024 * 1024:
            if progress:
                progress(70)
            sr = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'Dism /Split-Image /ImageFile:"{wim_path}" '
                 f'/SWMFile:"{drive_letter}:\\sources\\install.swm" /FileSize:3800'],
                capture_output=True, text=True, timeout=3600,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if sr.returncode != 0:
                return False
        else:
            if progress:
                progress(70)
            subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'Copy-Item "{wim_path}" "{drive_letter}:\\sources\\install.wim"'],
                capture_output=True, timeout=3600,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    elif has_esd:
        if progress:
            progress(70)
        subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'Copy-Item "{esd_path}" "{drive_letter}:\\sources\\install.esd"'],
            capture_output=True, timeout=3600,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    if progress:
        progress(90)

    subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f'Dismount-DiskImage -ImagePath \'{iso_escaped}\' -ErrorAction SilentlyContinue'],
        capture_output=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if progress:
        progress(100)
    return True


def find_drive_letter(disk_number: int) -> str:
    try:
        ps = (
            f'$p = Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue '
            f'| Where-Object {{ $_.DriveLetter -and $_.DriveLetter -ne [char]0 }} '
            f'| Select-Object -First 1; '
            f'if ($p) {{ Write-Output $p.DriveLetter }}'
        )
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        letter = r.stdout.strip()[:1]
        if letter and letter.isalpha():
            return letter.upper()
    except Exception:
        pass
    return ''


def flash_one(iso_path: str, disk_number: int, index: int, total: int) -> bool:
    iso_name = os.path.basename(iso_path)
    iso_type = get_iso_type(iso_path)

    print()
    log(f'[{index}/{total}] {iso_name} ({iso_type})')
    print()

    ok = False
    if iso_type in ('windows', 'winpe'):
        ok = flash_windows_iso(
            iso_path, disk_number,
            lambda p: progress_bar(p, iso_name)
        )
    else:
        progress_bar(0, 'Cleaning disk...')
        if not clean_disk(disk_number):
            log('\nFAILED: Could not clean disk')
            return False
        ok = raw_write_iso(
            iso_path, disk_number,
            lambda p: progress_bar(p, iso_name)
        )

    if not ok:
        print()
        log(f'FAILED: {iso_name}')
        return False

    progress_bar(100, iso_name)
    print()

    if iso_type not in ('windows', 'winpe'):
        # Take disk offline after raw write to suppress Windows "Format disk" prompt
        log('Suppressing Windows format prompt...')
        try:
            subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue '
                 f'| Where-Object {{ $_.DriveLetter }} '
                 f'| ForEach-Object {{ '
                 f'  Remove-PartitionAccessPath -DiskNumber {disk_number} '
                 f'    -PartitionNumber $_.PartitionNumber '
                 f"    -AccessPath \"$($_.DriveLetter):\\\" -ErrorAction SilentlyContinue; "
                 f'}} ; '
                 f'Set-Disk -Number {disk_number} -IsOffline $true -ErrorAction SilentlyContinue'],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
    else:
        letter = find_drive_letter(disk_number)
        if letter:
            hide_drive_ui(letter)

    log(f'OK: {iso_name}')
    return True


def main():
    if platform.system() == 'Windows' and not _is_admin():
        _elevate()
        return

    parser = argparse.ArgumentParser(description='Batch flash ISOs to USB')
    parser.add_argument('--disk', type=int, required=True,
                        help='Target disk number (e.g. 2 for \\\\.\\PhysicalDrive2)')
    args = parser.parse_args()
    disk = args.disk

    if not os.path.isdir(ISO_DIR):
        log(f'ERROR: ISO directory not found: {ISO_DIR}')
        sys.exit(1)

    isos = sorted([f for f in os.listdir(ISO_DIR) if f.lower().endswith('.iso')])
    if not isos:
        log('ERROR: No ISO files found in D:\\ISO')
        sys.exit(1)

    print()
    log(f'Found {len(isos)} ISO files')
    log(f'Target: \\\\.\\PhysicalDrive{disk}')
    log('WARNING: This will ERASE ALL DATA on this drive!')
    log('Press Ctrl+C to cancel.')
    print()

    time.sleep(2)

    success = 0
    for i, iso_name in enumerate(isos, 1):
        iso_path = os.path.join(ISO_DIR, iso_name)
        if flash_one(iso_path, disk, i, len(isos)):
            success += 1
        else:
            print()
            log(f'FAILED: {iso_name}')

        if i < len(isos):
            print()
            log(f'Disk #{disk} ready. Press Enter for next ISO ({isos[i]})...')
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                print()
                break

    print()
    log(f'Done: {success}/{len(isos)} succeeded')


if __name__ == '__main__':
    main()
