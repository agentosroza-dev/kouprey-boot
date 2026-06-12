import os
import sys
import time
import subprocess
import re
import ctypes
import platform

ISO_DIR = r'D:\ISO'
OUTPUT_DIR = r'D:\VMware_Test'
BAR_WIDTH = 32


def log(msg: str):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}')


def progress_bar(pct: int, status: str = ''):
    filled = int(BAR_WIDTH * pct / 100)
    empty = BAR_WIDTH - filled
    bar = '[' + '=' * filled + '>' * (1 if filled < BAR_WIDTH else 0) + '-' * max(0, empty - 1) + ']'
    pct_text = f'{pct:>3}%'
    line = f'\r{bar} {pct_text}  {status}'
    sys.stdout.write(line.ljust(120))
    sys.stdout.flush()


def get_disk_numbers() -> set:
    r = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         '(Get-Disk | Select-Object -ExpandProperty Number) -join \",\"'],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    nums = r.stdout.strip()
    return {int(x) for x in nums.split(',') if x.strip().isdigit()}


def create_vhd(vhd_path: str, size_mb: int) -> bool:
    os.makedirs(os.path.dirname(vhd_path), exist_ok=True)
    script = (
        f'create vdisk file="{vhd_path}" maximum={size_mb} type=expandable\n'
        f'exit\n'
    )
    r = subprocess.run(
        ['diskpart'], input=script, capture_output=True, text=True, timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return r.returncode == 0 and 'DiskPart has encountered an error' not in r.stdout


def attach_vhd(vhd_path: str) -> int | None:
    before = get_disk_numbers()
    script = (
        f'select vdisk file="{vhd_path}"\n'
        f'attach vdisk\n'
        f'exit\n'
    )
    subprocess.run(
        ['diskpart'], input=script, capture_output=True, text=True, timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(2)
    after = get_disk_numbers()
    new = after - before
    return new.pop() if new else None


def detach_vhd(vhd_path: str):
    script = (
        f'select vdisk file="{vhd_path}"\n'
        f'detach vdisk\n'
        f'exit\n'
    )
    subprocess.run(
        ['diskpart'], input=script, capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def hide_drive_ui(disk_number: int):
    """Hide all drive letters on the given disk and suppress 'Format disk' prompt."""
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'$shell = New-Object -ComObject Shell.Application; '
             f'$shell.Windows() | ForEach-Object {{ try {{ '
             f'  $parts = Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue; '
             f'  foreach ($part in $parts) {{ '
             f'    if ($part.DriveLetter -and $_.Document.Folder.Self.Path -eq "$($part.DriveLetter):\\") {{ '
             f'      $_.Quit() }} }} '
             f'}} catch {{}} }}; '
             f'Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue '
             f'| Where-Object {{ $_.DriveLetter }} '
             f'| ForEach-Object {{ '
             f'  Remove-PartitionAccessPath -DiskNumber {disk_number} '
             f'    -PartitionNumber $_.PartitionNumber '
             f'    -AccessPath "$($_.DriveLetter):\\" -ErrorAction SilentlyContinue; '
             f'  Set-Partition -DiskNumber {disk_number} -PartitionNumber $_.PartitionNumber '
             f'    -IsHidden $true -ErrorAction SilentlyContinue '
             f'}}'],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def get_iso_type(iso_path: str) -> str:
    """Return 'windows', 'winpe', or 'linux' (informational only).
    All types use raw write for VMware VHDs.
    """
    found = set()
    try:
        import zipfile
        if zipfile.is_zipfile(iso_path):
            with zipfile.ZipFile(iso_path, 'r') as zf:
                for n in zf.namelist():
                    n = n.lower().replace('\\', '/')
                    if 'install.wim' in n or 'install.esd' in n:
                        found.add('install')
                    if 'boot.wim' in n:
                        found.add('boot')
    except Exception:
        pass
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


def raw_write_iso(iso_path: str, disk_number: int, progress=None):
    iso_size = os.path.getsize(iso_path)
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


def create_vmx(vhd_path: str, name: str, output_dir: str):
    vmx_path = os.path.join(output_dir, f'{name}.vmx')
    content = f'''#!/usr/bin/vmware
.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "21"
displayName = "{name}"
guestOS = "otherlinux-64"
numvcpus = "2"
memSize = "4096"
scsi0.present = "TRUE"
scsi0.virtualDev = "lsisas1068"
scsi0:0.present = "TRUE"
scsi0:0.fileName = "{os.path.basename(vhd_path)}"
scsi0:0.deviceType = "disk"
ide1:0.present = "TRUE"
ide1:0.deviceType = "cdrom-image"
ide1:0.fileName = ""
ide1:0.autodetect = "TRUE"
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "e1000"
mks.enable3d = "FALSE"
usb.present = "FALSE"
sound.present = "FALSE"
'''
    with open(vmx_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return vmx_path


def process_iso(iso_path: str, index: int, total: int) -> bool:
    iso_name = os.path.basename(iso_path)
    name = os.path.splitext(iso_name)[0]
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', name)
    out_dir = os.path.join(OUTPUT_DIR, safe_name)
    vhd_path = os.path.join(out_dir, 'disk.vhd')
    vmx_path = os.path.join(out_dir, f'{safe_name}.vmx')

    iso_size = os.path.getsize(iso_path)
    size_mb = int(iso_size / (1024 * 1024)) + 512
    iso_type = get_iso_type(iso_path)

    print()
    log(f'[{index}/{total}] {iso_name} ({iso_type}, {size_mb} MB)')
    print()

    progress_bar(0, 'Creating VHD...')
    if not create_vhd(vhd_path, size_mb):
        log(f'FAILED: Could not create VHD for {iso_name}')
        return False

    progress_bar(5, 'Attaching VHD...')
    disk_num = attach_vhd(vhd_path)
    if disk_num is None:
        log(f'FAILED: Could not attach VHD for {iso_name}')
        return False

    progress_bar(10, f'Writing to disk #{disk_num}...')
    ok = False
    try:
        ok = raw_write_iso(iso_path, disk_num,
                           lambda p: progress_bar(10 + int(p * 0.85), f'Writing raw... {iso_name}'))
        if ok:
            log('Suppressing Windows format prompt...')
            hide_drive_ui(disk_num)
    finally:
        progress_bar(95, 'Detaching VHD...')
        detach_vhd(vhd_path)

    if not ok:
        log(f'FAILED: Write failed for {iso_name}')
        return False

    progress_bar(97, 'Creating VMX...')
    create_vmx(vhd_path, safe_name, out_dir)
    progress_bar(100, 'Done')
    print()
    log(f'OK: {iso_name} -> {out_dir}')
    return True


def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _elevate():
    script = os.path.abspath(sys.argv[0])
    ctypes.windll.shell32.ShellExecuteW(
        None, 'runas', sys.executable, f'"{script}"',
        os.path.dirname(script), 1
    )


def main():
    if platform.system() == 'Windows' and not _is_admin():
        _elevate()
        return

    if not os.path.isdir(ISO_DIR):
        log(f'ERROR: ISO directory not found: {ISO_DIR}')
        sys.exit(1)

    isos = sorted([f for f in os.listdir(ISO_DIR) if f.lower().endswith('.iso')])
    if not isos:
        log(f'ERROR: No ISO files found in {ISO_DIR}')
        sys.exit(1)

    log(f'Found {len(isos)} ISO files in {ISO_DIR}')
    log(f'Output: {OUTPUT_DIR}')
    print()

    success = 0
    failed = 0
    for i, iso_name in enumerate(isos, 1):
        iso_path = os.path.join(ISO_DIR, iso_name)
        if process_iso(iso_path, i, len(isos)):
            success += 1
        else:
            failed += 1
        print()

    log(f'Done: {success} succeeded, {failed} failed')
    print(f'\nVMX files created in: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
