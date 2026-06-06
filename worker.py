import os
import sys
import subprocess
import shutil
import platform
import tempfile
import datetime
import lzma
import time

from PyQt6.QtCore import QThread, pyqtSignal


def _create_log_file(prefix: str) -> str:
    log_dir = os.path.join(tempfile.gettempdir(), 'kouprey-boot')
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(log_dir, f'{prefix}_{ts}.log')


_base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
GRUB_SRC = os.path.join(_base, 'assets', 'grub')
BOOT_SRC = os.path.join(_base, 'assets', 'boot')


def _run_diskpart(commands: list[str], disk: int, timeout: int = 30) -> tuple[str, int]:
    try:
        script_lines = [f'select disk {disk}'] + commands
        script_text = '\r\n'.join(script_lines) + '\r\nexit\r\n'
        spath = os.path.join(tempfile.gettempdir(), f'dpart_{disk}.txt')
        with open(spath, 'w', encoding='ascii') as f:
            f.write(script_text)
        result = subprocess.run(
            ['diskpart', '/s', spath],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        os.remove(spath)
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return 'diskpart timed out', -1
    except Exception as e:
        return f'diskpart error: {e}', -1


def _run_powershell(script: str, timeout: int = 30) -> tuple[str, int]:
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = result.stdout.strip()
        if result.returncode != 0 and result.stderr.strip():
            combined = out + '\n' + result.stderr.strip() if out else result.stderr.strip()
            return combined, result.returncode
        return out, result.returncode
    except subprocess.TimeoutExpired:
        return 'Command timed out', -1
    except Exception as e:
        return f'Process error: {e}', -1


def _open_disk(disk_number: int):
    import ctypes
    handle = ctypes.windll.kernel32.CreateFileW(
        f'\\\\.\\PhysicalDrive{disk_number}',
        0xC0000000,
        0x00000003,
        None, 3,
        0x80, None,
    )
    if handle == -1 or handle is None:
        raise RuntimeError(f'Cannot open PhysicalDrive{disk_number}')
    return handle


def _close_disk(handle):
    import ctypes
    ctypes.windll.kernel32.CloseHandle(handle)


def _seek_disk(handle, byte_offset: int):
    import ctypes
    ctypes.windll.kernel32.SetFilePointerEx(handle, ctypes.c_longlong(byte_offset), None, 0)


def _read_raw_disk(disk_number: int, size: int, byte_offset: int = 0) -> bytes:
    import ctypes
    handle = _open_disk(disk_number)
    try:
        _seek_disk(handle, byte_offset)
        buf = ctypes.create_string_buffer(size)
        read = ctypes.c_ulong(0)
        ctypes.windll.kernel32.ReadFile(handle, buf, size, ctypes.byref(read), None)
        return buf.raw[:read.value]
    finally:
        _close_disk(handle)


def _write_raw_disk(disk_number: int, data: bytes, byte_offset: int = 0):
    import ctypes
    handle = _open_disk(disk_number)
    try:
        _seek_disk(handle, byte_offset)
        written = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None)
        if not ok:
            raise RuntimeError(f'WriteFile failed on PhysicalDrive{disk_number} at offset {byte_offset}')
    finally:
        _close_disk(handle)


def _suppress_format_dialogs():
    """Disable Windows automount & AutoPlay to suppress format/AutoPlay dialogs during flash."""
    _run_diskpart(['automount disable'], 0, timeout=10)
    _run_powershell('Stop-Service ShellHWDetection -Force -ErrorAction SilentlyContinue', timeout=5)
    time.sleep(0.3)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Policies\Explorer',
            0, winreg.KEY_SET_VALUE | winreg.KEY_READ,
        )
        winreg.SetValueEx(key, 'NoDriveTypeAutoRun', 0, winreg.REG_DWORD, 0xFF)
        winreg.CloseKey(key)
    except Exception:
        pass


def _restore_format_dialogs():
    """Re-enable Windows automount and restore AutoPlay after flash."""
    _run_diskpart(['automount enable'], 0, timeout=10)
    _run_powershell('Start-Service ShellHWDetection -ErrorAction SilentlyContinue', timeout=10)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Policies\Explorer',
            0, winreg.KEY_SET_VALUE | winreg.KEY_READ,
        )
        try:
            winreg.DeleteValue(key, 'NoDriveTypeAutoRun')
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
    except Exception:
        pass


class KoupreyFlashWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int, file_system: str = 'exfat', selected_isos: list[str] = None):
        super().__init__()
        self._disk_number = disk_number
        self._file_system = file_system
        self._selected_isos = selected_isos
        self._grub_src = GRUB_SRC
        self._last_error = ''
        self._log_path = ''

    def _log(self, msg: str):
        self.log.emit(msg)
        if self._log_path:
            ts = datetime.datetime.now().strftime('%H:%M:%S')
            try:
                with open(self._log_path, 'a', encoding='utf-8') as f:
                    f.write(f'[{ts}] {msg}\n')
            except Exception:
                pass

    def run(self):
        self._log_path = _create_log_file('flash')
        self._log(f'Kouprey Boot flash starting on disk #{self._disk_number}')
        self._log(f'Log file: {self._log_path}')
        self.progress.emit('Preparing disk...')

        sys_name = platform.system()
        try:
            if sys_name == 'Windows':
                ok = self._flash_windows()
            else:
                self._log('Linux support coming soon')
                ok = False

            if ok:
                self.progress.emit('Kouprey Boot installed successfully!')
                self._log('Kouprey Boot installed successfully!')
                self.finished.emit(True, f'Kouprey Boot installed. Log: {self._log_path}')
            else:
                err = self._last_error or 'Unknown error'
                self._log(f'Flash failed: {err}')
                self.finished.emit(False, f'Flash failed: {err}\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, str(e))
        finally:
            _restore_format_dialogs()
            self._log('Windows automount and AutoPlay restored')

    def _flash_windows(self) -> bool:
        disk = self._disk_number
        fs = self._file_system

        if platform.system() == 'Windows':
            try:
                import ctypes
                if not ctypes.windll.shell32.IsUserAnAdmin():
                    self._last_error = 'Administrator privileges required. Please run the app as Administrator.'
                    self._log(self._last_error)
                    return False
            except Exception:
                self._last_error = 'Could not check admin privileges.'
                self._log(self._last_error)
                return False

        self._log('Suppressing Windows automount and AutoPlay to hide format dialogs...')
        _suppress_format_dialogs()

        self._log(f'Step 1: Clearing disk #{disk}...')
        script = f'''
$disk = Get-Disk -Number {disk} -ErrorAction SilentlyContinue
if (-not $disk) {{ Write-Error "Disk #{disk} not found"; exit 1 }}

# Ensure disk is writable and online
Set-Disk -Number {disk} -IsOffline $false -ErrorAction SilentlyContinue
Set-Disk -Number {disk} -IsReadOnly $false -ErrorAction SilentlyContinue

# Try Clear-Disk first (failsafe if volumes are mounted)
$clearOk = $true
try {{
    Clear-Disk -Number {disk} -RemoveData -RemoveOEM -Confirm:$false -ErrorAction Stop
}} catch {{
    $clearOk = $false
}}

if (-not $clearOk) {{
    # Fallback: use diskpart for stubborn disks
    $scriptPath = "$env:TEMP\\clean_disk_{disk}.txt"
    "select disk {disk}`nclean`nconvert gpt" | Out-File -FilePath $scriptPath -Encoding ascii
    & diskpart /s $scriptPath | Out-Null
    Remove-Item $scriptPath -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}}

$disk | Update-Disk -ErrorAction SilentlyContinue
Set-Disk -Number {disk} -IsOffline $false -ErrorAction SilentlyContinue
Set-Disk -Number {disk} -IsReadOnly $false -ErrorAction SilentlyContinue
Write-Output "Disk cleared"
'''
        out, rc = _run_powershell(script, timeout=60)
        if rc != 0 or 'Error' in out:
            self._last_error = out or 'Clear-Disk failed (disk may be in use)'
            self._log(f'Clear-Disk failed: {self._last_error}')
            return False
        self._log('Disk cleared')

        self._log('Step 2: Initializing GPT...')
        script = f'''
$disk = Get-Disk -Number {disk} -ErrorAction SilentlyContinue
if (-not $disk) {{ Write-Error "Disk #{disk} not found"; exit 1 }}
$disk | Update-Disk -ErrorAction SilentlyContinue
Set-Disk -Number {disk} -IsOffline $false -ErrorAction SilentlyContinue
Set-Disk -Number {disk} -IsReadOnly $false -ErrorAction SilentlyContinue
if ($disk.PartitionStyle -eq 'RAW') {{
    Initialize-Disk -Number {disk} -PartitionStyle GPT -Confirm:$false -ErrorAction Stop
}} elseif ($disk.PartitionStyle -eq 'MBR') {{
    $sp = "$env:TEMP\\convert_gpt_{disk}.txt"
    "select disk {disk}`nclean`nconvert gpt" | Out-File -FilePath $sp -Encoding ascii
    & diskpart /s $sp | Out-Null
    Remove-Item $sp -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}}
Write-Output "GPT initialized"
'''
        out, rc = _run_powershell(script, timeout=30)
        if rc != 0 or 'Error' in out:
            self._last_error = out or 'Initialize-Disk failed'
            self._log(f'Initialize-Disk failed: {self._last_error}')
            return False
        self._log('GPT partition table created')
        self.progress.emit('Creating partitions...')

        self._log('Step 3: Creating DATA partition (Ventoy partition 1)...')
        out, rc = _run_diskpart(['create partition primary'], disk, timeout=60)
        if rc != 0:
            self._last_error = out or 'DATA partition creation failed'
            self._log(f'DATA partition creation failed: {self._last_error}')
            return False
        self._log('DATA partition created, shrinking to make room for ESP + BIOS Boot...')

        ps_shrink = f'''
$part = Get-Partition -DiskNumber {disk} | Sort-Object PartitionNumber | Select-Object -First 1
$newSize = $part.Size - 70MB
Resize-Partition -DiskNumber {disk} -PartitionNumber $part.PartitionNumber -Size $newSize -ErrorAction Stop
Set-Partition -DiskNumber {disk} -PartitionNumber $part.PartitionNumber -NoDefaultDriveLetter $true -ErrorAction SilentlyContinue
Write-Output "SHRINK=ok"
'''
        out, rc = _run_powershell(ps_shrink, timeout=30)
        if rc != 0 or 'Error' in out:
            self._last_error = out or 'Shrink DATA partition failed'
            self._log(f'Shrink DATA partition failed: {self._last_error}')
            return False
        self._log('DATA partition shrunk (freed 70 MB)')

        fs_map = {'exfat': 'EXFAT', 'ntfs': 'NTFS', 'fat32': 'FAT32'}
        fs_arg = fs_map.get(fs, 'EXFAT')
        ps_format = f'''
$part = Get-Partition -DiskNumber {disk} | Sort-Object PartitionNumber | Select-Object -First 1
        $part | Format-Volume -FileSystem {fs_arg} -NewFileSystemLabel "VTOYDATA" -Confirm:$false -ErrorAction Stop
        $used = (Get-Volume).DriveLetter | Where-Object {{ $_ }}
$tChar = if ($used -notcontains 'T') {{ 'T' }} else {{ 90..68 | ForEach-Object {{ [char]$_ }} | Where-Object {{ $_ -notin $used }} | Select-Object -First 1 }}
Set-Partition -DiskNumber {disk} -PartitionNumber $part.PartitionNumber -NewDriveLetter $tChar -ErrorAction Stop
$dataDrive = $tChar + ":\\"
Write-Output "DATA=$dataDrive"
'''
        out, rc = _run_powershell(ps_format, timeout=120)
        if rc != 0 or 'Error' in out or 'DATA=' not in out:
            self._last_error = out or 'DATA format failed'
            self._log(f'DATA format failed: {self._last_error}')
            return False
        data_drive = ''
        for line in out.split('\n'):
            if line.startswith('DATA='):
                data_drive = line.split('=', 1)[1].strip()
                break
        self._log(f'DATA formatted at {data_drive}')
        self.progress.emit('DATA created...')

        self._log('Step 4: Creating ESP partition (64 MB FAT32)...')
        out, rc = _run_diskpart(['create partition efi size=64'], disk, timeout=60)
        if rc != 0:
            self._last_error = out or 'ESP partition creation failed'
            self._log(f'ESP partition creation failed: {self._last_error}')
            return False
        self._log('ESP partition created (will format after BIOS Boot)')

        self._log('Step 5: Creating BIOS Boot Partition (2 MB, partition 3)...')
        out, rc = _run_diskpart([
            'create partition primary size=2',
            'set id=21686148-6449-6E6F-744E-656564454649 override',
            'gpt attributes=0x8000000000000000',
        ], disk, timeout=30)
        if rc != 0:
            self._last_error = out or 'BIOS Boot partition creation failed'
            self._log(f'BIOS Boot partition creation failed: {self._last_error}')
            return False
        self._log('BIOS Boot partition created (bios_grub type, no auto-drive-letter)')
        self.progress.emit('Creating partitions...')

        self._log('Step 5b: Querying BIOS Boot Partition geometry...')
        ps_bios_info = f'''
$part = Get-Partition -DiskNumber {disk} | Where-Object {{ $_.GptType -eq "{{21686148-6449-6E6F-744E-656564454649}}" }} | Select-Object -First 1
if (-not $part) {{ $part = Get-Partition -DiskNumber {disk} | Sort-Object PartitionNumber -Descending | Select-Object -First 1 }}
Write-Output "OFFSET=$($part.Offset)"
Write-Output "LBA=$([int]($part.Offset / 512))"
Write-Output "SECTORS=$($part.Size / 512)"
'''
        out, rc = _run_powershell(ps_bios_info, timeout=10)
        bios_lba = 34
        bios_offset = 0
        bios_sectors = 4096
        for line in out.split('\n'):
            line = line.strip()
            if line.startswith('OFFSET='):
                bios_offset = int(line.split('=', 1)[1].strip())
            elif line.startswith('LBA='):
                bios_lba = int(line.split('=', 1)[1].strip())
            elif line.startswith('SECTORS='):
                bios_sectors = int(float(line.split('=', 1)[1].strip()))
        self._log(f'BIOS Boot Partition: LBA={bios_lba}, offset={bios_offset}, sectors={bios_sectors}')

        self._log('Step 5c: Patching boot.img and writing to MBR...')
        boot_img_path = os.path.join(BOOT_SRC, 'boot.img')
        if os.path.isfile(boot_img_path):
            import struct
            with open(boot_img_path, 'rb') as f:
                boot_img_data = bytearray(f.read())
            struct.pack_into('<I', boot_img_data, 0x1AC, bios_lba)
            struct.pack_into('<I', boot_img_data, 0x1B0, 0)
            struct.pack_into('<I', boot_img_data, 0x1B8, bios_sectors)
            current_mbr = _read_raw_disk(disk, 512, byte_offset=0)
            merged = bytes(boot_img_data[:446]) + current_mbr[446:512]
            _write_raw_disk(disk, merged, byte_offset=0)
            self._log(f'boot.img patched with core LBA={bios_lba} and written to MBR')
        else:
            self._log(f'Warning: boot.img not found at {boot_img_path}')

        self._log('Step 5d: Writing core.img to BIOS Boot Partition...')
        core_xz_path = os.path.join(BOOT_SRC, 'core.img.xz')
        if os.path.isfile(core_xz_path) and bios_offset:
            with lzma.open(core_xz_path, 'rb') as f:
                core_data = f.read()
            # Pad to 512-byte sector boundary (required for physical disk writes)
            pad = (512 - len(core_data) % 512) % 512
            if pad:
                core_data += b'\x00' * pad
            _write_raw_disk(disk, core_data, byte_offset=bios_offset)
            self._log(f'core.img written to BIOS Boot Partition at LBA={bios_lba} ({len(core_data)} bytes, {len(core_data)//512} sectors)')
        else:
            if not os.path.isfile(core_xz_path):
                self._log(f'Warning: core.img.xz not found at {core_xz_path}')
            if not bios_offset:
                self._log('Warning: could not determine BIOS Boot Partition offset')

        self._log('Step 5e: Formatting and mounting ESP...')
        esp_mount = os.path.join(tempfile.gettempdir(), 'kp_esp')
        os.makedirs(esp_mount, exist_ok=True)
        ps_format = f'''
$part = Get-Partition -DiskNumber {disk} | Where-Object {{ $_.Type -eq "EFI" -or $_.GptType -eq "{{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}}" }} | Select-Object -First 1
if (-not $part) {{ $part = Get-Partition -DiskNumber {disk} | Sort-Object PartitionNumber | Select-Object -Skip 1 -First 1 }}
Set-Partition -DiskNumber {disk} -PartitionNumber $part.PartitionNumber -NoDefaultDriveLetter $true -ErrorAction SilentlyContinue
        $part | Format-Volume -FileSystem FAT32 -NewFileSystemLabel "VTOYEFI" -Confirm:$false -ErrorAction Stop
Add-PartitionAccessPath -DiskNumber {disk} -PartitionNumber $part.PartitionNumber -AccessPath "{esp_mount}" -ErrorAction Stop
Write-Output "ESP={esp_mount}"
'''
        out, rc = _run_powershell(ps_format, timeout=60)
        if rc != 0 or 'Error' in out or 'ESP=' not in out:
            self._last_error = out or 'ESP format/mount failed'
            self._log(f'ESP format/mount failed: {self._last_error}')
            return False
        esp_drive = ''
        for line in out.split('\n'):
            if line.startswith('ESP='):
                esp_drive = line.split('=', 1)[1].strip()
                break
        self._log('ESP formatted and mounted to folder (hidden from Explorer)')

        self._log('Step 6: Installing GRUB2...')
        self.progress.emit('Installing GRUB2...')
        ok = self._install_grub(esp_drive, data_drive)
        if not ok:
            return False

        self._log('Step 7: Creating ISOs directory and GRUB marker...')
        import time
        iso_dir = os.path.join(data_drive, 'ISOS')
        os.makedirs(iso_dir, exist_ok=True)
        dummy_path = os.path.join(iso_dir, 'DUMMY')
        if not os.path.isfile(dummy_path):
            with open(dummy_path, 'w', encoding='utf-8') as f:
                f.write('# Kouprey Boot ISO directory marker\n')
        self._log(f'Created {iso_dir}')

        disk_src = os.path.join(_base, 'assets', 'disk')
        if os.path.isdir(disk_src):
            items_to_copy = self._selected_isos if self._selected_isos is not None else os.listdir(disk_src)
            copied = 0
            for item in items_to_copy:
                s = os.path.join(disk_src, item)
                if not os.path.exists(s):
                    self._log(f'  Skipped (not found): {item}')
                    continue
                d = os.path.join(iso_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
                copied += 1
            self._log(f'Copied {copied} item(s) to ISOS')
        else:
            self._log(f'Warning: {disk_src} not found')

        themes_dir = os.path.join(data_drive, 'themes')
        os.makedirs(themes_dir, exist_ok=True)
        marker_path = os.path.join(themes_dir, '.marker')
        with open(marker_path, 'w', encoding='utf-8') as f:
            f.write('# Kouprey Boot DATA partition theme marker\n')
        self._log(f'DATA themes dir created: {themes_dir}')

        self._log('Generating ISO menu entries...')
        self._generate_iso_menu(data_drive)
        self._log('ISO menu generated')

        self._log('Step 8: Copying grub.cfg to ESP...')
        src_cfg = os.path.join(_base, 'assets', 'grub', 'grub', 'grub.cfg')
        cfg_main = os.path.join(esp_drive, 'grub', 'grub.cfg')
        cfg_fallback = os.path.join(esp_drive, 'EFI', 'BOOT', 'grub.cfg')
        shutil.copy2(src_cfg, cfg_main)
        os.makedirs(os.path.dirname(cfg_fallback), exist_ok=True)
        shutil.copy2(src_cfg, cfg_fallback)
        self._log('grub.cfg copied to ESP (grub/ + EFI/BOOT/)')

        self._log('Step 9: Removing ESP mount (hidden from Windows)...')
        if os.path.exists(esp_mount):
            ps_esp_part = f'''
$part = Get-Partition -DiskNumber {disk} | Where-Object {{ $_.Type -eq "EFI" -or $_.GptType -eq "{{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}}" }} | Select-Object -First 1
Write-Output "PART=$($part.PartitionNumber)"
'''
            out_esp, _ = _run_powershell(ps_esp_part, timeout=10)
            esp_part_num = 2
            for line in out_esp.split('\n'):
                if line.startswith('PART='):
                    esp_part_num = int(line.split('=', 1)[1].strip())
                    break
            out1, rc1 = _run_powershell(f'Remove-PartitionAccessPath -DiskNumber {disk} -PartitionNumber {esp_part_num} -AccessPath "{esp_mount}" -ErrorAction Stop', timeout=15)
            if rc1 != 0:
                subprocess.run(['mountvol', esp_mount, '/d'], capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                os.rmdir(esp_mount)
            except Exception:
                pass
        self._log('ESP mount removed (hidden from Windows Explorer)')

        self.progress.emit('Installation complete!')
        return True

    def _install_grub(self, esp_drive: str, data_drive: str) -> bool:
        src = self._grub_src
        if not src or not os.path.isdir(src):
            self._last_error = f'GRUB source not found at {src}'
            self._log(self._last_error)
            return False

        dest_efi = os.path.join(esp_drive, 'EFI', 'BOOT')
        dest_grub = os.path.join(esp_drive, 'grub')
        dest_themes = os.path.join(data_drive, 'themes')

        os.makedirs(dest_efi, exist_ok=True)
        os.makedirs(dest_grub, exist_ok=True)
        os.makedirs(dest_themes, exist_ok=True)

        self._log(f'Copying EFI/BOOT directory...')
        efi_boot_src = os.path.join(src, 'EFI', 'BOOT')
        if os.path.isdir(efi_boot_src):
            shutil.copytree(efi_boot_src, dest_efi, dirs_exist_ok=True)
        real_efi = os.path.join(dest_efi, 'grubx64_real.efi')
        if os.path.isfile(real_efi):
            shutil.copy2(real_efi, os.path.join(dest_efi, 'BOOTX64.EFI'))
            self._log('Replaced BOOTX64.EFI with standard GRUB (grubx64_real.efi)')
        real_efi_ia32 = os.path.join(dest_efi, 'grubia32_real.efi')
        if os.path.isfile(real_efi_ia32):
            shutil.copy2(real_efi_ia32, os.path.join(dest_efi, 'BOOTIA32.EFI'))
            self._log('Replaced BOOTIA32.EFI with standard GRUB (grubia32_real.efi)')

        self._log(f'Copying tool directory to EFI/BOOT...')
        tool_src = os.path.join(src, 'tool')
        if os.path.isdir(tool_src):
            shutil.copytree(tool_src, dest_efi, dirs_exist_ok=True)

        self._log(f'Copying ventoy directory to ESP root...')
        ventoy_src = os.path.join(src, 'ventoy')
        dest_ventoy = os.path.join(esp_drive, 'ventoy')
        if os.path.isdir(ventoy_src):
            shutil.copytree(ventoy_src, dest_ventoy, dirs_exist_ok=True)

        self._log(f'Copying Ventoy files to DATA partition...')
        dest_data_ventoy = os.path.join(data_drive, 'ventoy')
        os.makedirs(dest_data_ventoy, exist_ok=True)
        ventoy_cpio = os.path.join(src, 'ventoy', 'ventoy.cpio')
        if os.path.isfile(ventoy_cpio):
            shutil.copy2(ventoy_cpio, os.path.join(dest_data_ventoy, 'ventoy.cpio'))
        ventoy_json = os.path.join(dest_data_ventoy, 'ventoy.json')
        if not os.path.isfile(ventoy_json):
            with open(ventoy_json, 'w', encoding='utf-8') as f:
                f.write('{"control":[{"VTOY_DEFAULT_SEARCH_ROOT":"/ISOS"}]}\n')

        self._log(f'Copying MOK manager certificate...')
        cert_src = os.path.join(src, 'ENROLL_THIS_KEY_IN_MOKMANAGER.cer')
        if os.path.isfile(cert_src):
            shutil.copy2(cert_src, os.path.join(dest_efi, 'ENROLL_THIS_KEY_IN_MOKMANAGER.cer'))

        self._log(f'Copying GRUB directory...')
        grub_src = os.path.join(src, 'grub')
        if os.path.isdir(grub_src):
            shutil.copytree(grub_src, dest_grub, dirs_exist_ok=True)
            self._log(f'GRUB directory copied')

        self._log(f'Copying ventoy.disk to ESP root...')
        ventoy_src = os.path.join(self._grub_src, 'grub', 'ventoy.disk')
        if os.path.isfile(ventoy_src):
            shutil.copy2(ventoy_src, os.path.join(esp_drive, 'ventoy.disk'))
            self._log(f'ventoy.disk copied to ESP root')
        else:
            self._log('Warning: ventoy.disk not found')
            ventoy_src2 = os.path.join(self._grub_src, 'grub', 'ventoy.disk.img')
            if os.path.isfile(ventoy_src2):
                shutil.copy2(ventoy_src2, os.path.join(esp_drive, 'ventoy.disk.img'))
                self._log('ventoy.disk.img copied (fallback)')

        self._log(f'Copying boot.img and core.img.xz to ESP root...')
        boot_img_src = os.path.join(BOOT_SRC, 'boot.img')
        if os.path.isfile(boot_img_src):
            shutil.copy2(boot_img_src, os.path.join(esp_drive, 'boot.img'))
            self._log('boot.img copied to ESP root')
        else:
            self._log('Warning: boot.img not found')
        core_xz_src = os.path.join(BOOT_SRC, 'core.img.xz')
        if os.path.isfile(core_xz_src):
            shutil.copy2(core_xz_src, os.path.join(esp_drive, 'core.img.xz'))
            self._log('core.img.xz copied to ESP root')
        else:
            self._log('Warning: core.img.xz not found')

        self._log(f'Copying wimboot to ESP root...')
        wimboot_src = os.path.join(self._grub_src, 'grub', 'wimboot', 'wimboot.x86_64.xz')
        if os.path.isfile(wimboot_src):
            shutil.copy2(wimboot_src, os.path.join(esp_drive, 'wimboot'))
            self._log('wimboot copied to ESP root')
        else:
            self._log('Warning: wimboot.x86_64.xz not found')

        self._log(f'Copying default theme (Vimix)...')
        theme_src = os.path.join(_base, 'themes', 'Vimix-theme', 'themes')
        if os.path.isdir(theme_src):
            for fname in os.listdir(theme_src):
                s = os.path.join(theme_src, fname)
                d = os.path.join(dest_themes, fname)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
            self._log(f'Default theme copied to {dest_themes}')

        marker_path = os.path.join(dest_themes, '.marker')
        if not os.path.isfile(marker_path):
            with open(marker_path, 'w', encoding='utf-8') as f:
                f.write('# Kouprey Boot DATA partition theme marker\n')

        self._log('GRUB2 installed successfully')
        return True

    def _flash_linux(self) -> bool:
        self._log('Linux flash not yet implemented')
        return False

    @staticmethod
    def _detect_iso_type(fname: str) -> str:
        lower = fname.lower()
        if 'winpe' in lower or 'win11' in lower or 'win10' in lower or 'windows' in lower:
            return 'windows'
        if 'arch' in lower or 'cachyos' in lower or 'endeavouros' in lower or 'manjaro' in lower:
            return 'arch'
        if 'redorescue' in lower or 'systemrescue' in lower:
            return 'live'
        if 'ubuntu' in lower or 'linuxmint' in lower or 'pop' in lower or 'zorin' in lower or 'kubuntu' in lower:
            return 'ubuntu'
        if 'fedora' in lower or 'nobara' in lower or 'silverblue' in lower:
            return 'fedora'
        if 'debian' in lower:
            return 'debian'
        return 'generic'

    @staticmethod
    def _make_entry(fname: str, safe_name: str, itype: str) -> str:
        iso_path = f'/ISOS/{safe_name}'
        if itype == 'windows':
            return (
                f'menuentry "Boot {safe_name}" --class windows {{\n'
                f'    insmod loopback\n'
                f'    insmod iso9660\n'
                f'    insmod chain\n'
                f'    set isofile="{iso_path}"\n'
                f'    loopback loop ($data_root)$isofile\n'
                f'    chainloader (loop)/efi/boot/bootx64.efi\n'
                f'    boot\n'
                f'}}'
            )
        if itype == 'arch':
            return (
                f'menuentry "Boot {safe_name}" --class arch {{\n'
                f'    insmod loopback\n'
                f'    insmod iso9660\n'
                f'    set isofile="{iso_path}"\n'
                f'    loopback loop ($data_root)$isofile\n'
                f'    linux (loop)/arch/boot/x86_64/vmlinuz-linux img_loop=$isofile img_dev=/dev/disk/by-uuid/YOUR_UUID archisobasedir=arch\n'
                f'    initrd (loop)/arch/boot/x86_64/archiso.img\n'
                f'}}'
            )
        if itype == 'ubuntu':
            return (
                f'menuentry "Boot {safe_name}" --class ubuntu {{\n'
                f'    insmod loopback\n'
                f'    insmod iso9660\n'
                f'    set isofile="{iso_path}"\n'
                f'    loopback loop ($data_root)$isofile\n'
                f'    linux (loop)/casper/vmlinuz boot=casper iso-scan/filename=$isofile quiet splash ---\n'
                f'    initrd (loop)/casper/initrd.img\n'
                f'}}'
            )
        if itype == 'live':
            return (
                f'menuentry "Boot {safe_name}" --class live {{\n'
                f'    insmod loopback\n'
                f'    insmod iso9660\n'
                f'    set isofile="{iso_path}"\n'
                f'    loopback loop ($data_root)$isofile\n'
                f'    linux (loop)/live/vmlinuz boot=live findiso=$isofile components splash\n'
                f'    initrd (loop)/live/initrd.img\n'
                f'}}'
            )
        if itype == 'fedora':
            return (
                f'menuentry "Boot {safe_name}" --class fedora {{\n'
                f'    insmod loopback\n'
                f'    insmod iso9660\n'
                f'    insmod probe\n'
                f'    set isofile="{iso_path}"\n'
                f'    loopback loop ($data_root)$isofile\n'
                f'    probe --set isolabel --label (loop)\n'
                f'    linux (loop)/images/pxeboot/vmlinuz root=live:CDLABEL=$isolabel rd.live.image iso-scan/filename=$isofile quiet rhgb\n'
                f'    initrd (loop)/images/pxeboot/initrd.img\n'
                f'}}'
            )
        if itype == 'debian':
            return (
                f'menuentry "Boot {safe_name}" --class debian {{\n'
                f'    insmod loopback\n'
                f'    insmod iso9660\n'
                f'    set isofile="{iso_path}"\n'
                f'    loopback loop ($data_root)$isofile\n'
                f'    linux (loop)/install.amd/vmlinuz findiso=$isofile\n'
                f'    initrd (loop)/install.amd/initrd.img\n'
                f'}}'
            )
        return (
            f'menuentry "Boot {safe_name}" --class iso {{\n'
            f'    boot_iso "($data_root)" "{iso_path}"\n'
            f'}}'
        )

    @staticmethod
    def _generate_iso_menu(data_drive: str):
        iso_dir = os.path.join(data_drive, 'ISOS')
        menu_path = os.path.join(iso_dir, '.iso_menu.cfg')
        os.makedirs(iso_dir, exist_ok=True)
        entries = []
        for fname in sorted(os.listdir(iso_dir)):
            if fname == '.iso_menu.cfg':
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ('.iso', '.img'):
                continue
            safe_name = fname.replace('"', '\\"')
            itype = KoupreyFlashWorker._detect_iso_type(fname)
            entries.append(KoupreyFlashWorker._make_entry(fname, safe_name, itype))
        with open(menu_path, 'w', encoding='utf-8') as f:
            f.write('# Kouprey Boot ISO menu - auto-generated\n')
            f.write(f'# {len(entries)} ISO(s) found in /ISOS/\n')
            f.write('# Re-generate: python flash_headless.py -gen-iso-menu -disk N\n')
            f.write('#\n')
            f.write('# All entries reference ($data_root) — the DATA partition discovered by grub.cfg.\n')
            f.write('# Unknown ISO types use the boot_iso function (loopback.cfg → chainload → memdisk).\n')
            f.write('# If an entry fails, copy the template from:\n')
            f.write('#   assets/grub/grub/.iso_menu.cfg\n')
            f.write('# and customize kernel parameters for your ISO.\n')
            f.write('#\n')
            f.write('\n'.join(entries))
            f.write('\n')
        return len(entries)


def create_flash_worker(disk_number: int, file_system: str = 'exfat', selected_isos: list[str] = None):
    return KoupreyFlashWorker(disk_number, file_system, selected_isos)


class DeployWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int, mount_point: str, data_mount_point: str, grub_dir: str, options: dict):
        super().__init__()
        self._disk = disk_number
        self._mount = mount_point if mount_point.endswith('\\') else mount_point + '\\' if mount_point else ''
        self._data_mount = (data_mount_point if data_mount_point.endswith('\\') else data_mount_point + '\\') if data_mount_point else ''
        self._grub_dir = grub_dir
        self._options = options
        self._log_path = ''
        self._esp_mount = ''

    def _log(self, msg: str):
        self.log.emit(msg)
        if self._log_path:
            ts = datetime.datetime.now().strftime('%H:%M:%S')
            try:
                with open(self._log_path, 'a', encoding='utf-8') as f:
                    f.write(f'[{ts}] {msg}\n')
            except Exception:
                pass

    def _get_esp_partition_number(self) -> int:
        ps = f'$part = Get-Partition -DiskNumber {self._disk} | Where-Object {{ $_.GptType -eq "{{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}}" }} | Select-Object -First 1; if (-not $part) {{ $part = Get-Partition -DiskNumber {self._disk} | Sort-Object PartitionNumber | Select-Object -Skip 1 -First 1 }}; Write-Output $part.PartitionNumber'
        out, rc = _run_powershell(ps, timeout=10)
        if rc == 0 and out.strip().isdigit():
            return int(out.strip())
        return 2

    def _mount_esp(self) -> str:
        mount_path = os.path.join(tempfile.gettempdir(), 'kp_esp_d')
        os.makedirs(mount_path, exist_ok=True)
        part_num = self._get_esp_partition_number()
        ps = f'Add-PartitionAccessPath -DiskNumber {self._disk} -PartitionNumber {part_num} -AccessPath "{mount_path}" -ErrorAction Stop'
        out, rc = _run_powershell(ps, timeout=15)
        if rc == 0:
            return mount_path
        return ''

    def _unmount_esp(self):
        if self._esp_mount and os.path.exists(self._esp_mount):
            part_num = self._get_esp_partition_number()
            _run_powershell(f'Remove-PartitionAccessPath -DiskNumber {self._disk} -PartitionNumber {part_num} -AccessPath "{self._esp_mount}" -ErrorAction Stop', timeout=10)
            try:
                os.rmdir(self._esp_mount)
            except Exception:
                pass
            self._esp_mount = ''

    def run(self):
        self._log_path = _create_log_file('deploy')
        self._log(f'Deploy starting. Log: {self._log_path}')

        if platform.system() == 'Windows':
            try:
                import ctypes
                if not ctypes.windll.shell32.IsUserAnAdmin():
                    self._log('Administrator privileges required.')
                    self.finished.emit(False, 'Administrator privileges required. Please run the app as Administrator.')
                    return
            except Exception:
                pass

        _suppress_format_dialogs()

        try:
            theme_name = self._options.get('theme')
            theme_path = self._options.get('theme_path')
            if theme_name and theme_path:
                self.progress.emit(f'Applying theme: {theme_name}...')

                # Deploy theme to DATA partition
                if not self._data_mount:
                    self._log('DATA mount not available')
                    raise RuntimeError('DATA partition not found')
                themes_root = os.path.join(self._data_mount, 'themes')
                os.makedirs(themes_root, exist_ok=True)

                for item in os.listdir(themes_root):
                    if item == '.marker':
                        continue
                    item_path = os.path.join(themes_root, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)

                shutil.copytree(theme_path, themes_root, dirs_exist_ok=True)

                marker_path = os.path.join(themes_root, '.marker')
                if not os.path.isfile(marker_path):
                    with open(marker_path, 'w', encoding='utf-8') as f:
                        f.write('# Kouprey Boot DATA partition theme marker\n')

                self._log(f'Theme "{theme_name}" deployed to DATA: {themes_root}')

                # Mount ESP and verify grub.cfg exists
                if not self._mount:
                    mounted = self._mount_esp()
                    if mounted:
                        self._esp_mount = mounted
                        self._mount = mounted + '\\'
                        self._log(f'ESP mounted to {self._mount}')
                else:
                    self._esp_mount = self._mount.rstrip('\\')

                if self._esp_mount:
                    cfg_path = os.path.join(self._esp_mount, 'EFI', 'BOOT', 'grub.cfg')
                    if not os.path.isfile(cfg_path):
                        cfg_path = os.path.join(self._esp_mount, 'grub', 'grub.cfg')
                    if os.path.isfile(cfg_path):
                        self._log('grub.cfg verified on ESP')
                    else:
                        self._log('Warning: grub.cfg not found on ESP')

            self.finished.emit(True, f'Deployment complete!\nLog: {self._log_path}')

        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, f'{e}\nLog: {self._log_path}')
        finally:
            self._unmount_esp()
            _restore_format_dialogs()
