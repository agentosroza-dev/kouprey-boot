import os
import sys
import subprocess
import shutil
import platform
import tempfile
import datetime
import time

from PyQt6.QtCore import QThread, pyqtSignal


def _create_log_file(prefix: str) -> str:
    log_dir = os.path.join(tempfile.gettempdir(), 'kouprey-boot')
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(log_dir, f'{prefix}_{ts}.log')


_base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
GRUB_SRC = os.path.join(_base, 'assets', 'boot')


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

        self._log('Step 3: Creating ESP partition (64 MB FAT32)...')
        out, rc = _run_diskpart(['create partition efi size=64'], disk, timeout=60)
        if rc != 0:
            self._last_error = out or 'ESP partition creation failed'
            self._log(f'ESP partition creation failed: {self._last_error}')
            return False
        self._log('ESP partition created')

        self._log('Step 4: Creating DATA partition...')
        out, rc = _run_diskpart(['create partition primary'], disk, timeout=60)
        if rc != 0:
            self._last_error = out or 'DATA partition creation failed'
            self._log(f'DATA partition creation failed: {self._last_error}')
            return False
        self._log('DATA partition created')

        fs_map = {'exfat': 'EXFAT', 'ntfs': 'NTFS', 'fat32': 'FAT32'}
        fs_arg = fs_map.get(fs, 'EXFAT')
        ps_format = f'''
$part = Get-Partition -DiskNumber {disk} | Where-Object {{ $_.GptType -eq "{{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}}" }} | Select-Object -First 1
if (-not $part) {{ $part = Get-Partition -DiskNumber {disk} | Where-Object {{ $_.Type -eq "Basic" }} | Select-Object -First 1 }}
$part | Format-Volume -FileSystem {fs_arg} -NewFileSystemLabel "KOUPREYDATA" -Confirm:$false -ErrorAction Stop
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

        self._log('Step 5: Formatting and mounting ESP...')
        esp_mount = os.path.join(tempfile.gettempdir(), 'kp_esp')
        os.makedirs(esp_mount, exist_ok=True)
        ps_format = f'''
$part = Get-Partition -DiskNumber {disk} | Where-Object {{ $_.Type -eq "EFI" -or $_.GptType -eq "{{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}}" }} | Select-Object -First 1
Set-Partition -DiskNumber {disk} -PartitionNumber $part.PartitionNumber -NoDefaultDriveLetter $true -ErrorAction SilentlyContinue
$part | Format-Volume -FileSystem FAT32 -NewFileSystemLabel "KPEFI" -Confirm:$false -ErrorAction Stop
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
        src_cfg = os.path.join(_base, 'assets', 'boot', 'grub', 'grub.cfg')
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


        self._log(f'Copying MOK manager certificate...')
        cert_src = os.path.join(src, 'ENROLL_THIS_KEY_IN_MOKMANAGER.cer')
        if os.path.isfile(cert_src):
            shutil.copy2(cert_src, os.path.join(dest_efi, 'ENROLL_THIS_KEY_IN_MOKMANAGER.cer'))

        self._log(f'Copying GRUB directory...')
        grub_src = os.path.join(src, 'grub')
        if os.path.isdir(grub_src):
            shutil.copytree(grub_src, dest_grub, dirs_exist_ok=True)
            self._log(f'GRUB directory copied')


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
        if any(k in lower for k in ('winpe', 'win11', 'win10', 'win8', 'win7',
                                    'windows', 'winxp', 'win2008', 'win2012',
                                    'win2016', 'win2019', 'win2022', 'win2025',
                                    'server', 'windows11', 'windows10', 'windows8',
                                    'windows7', 'longhorn', 'vista', 'dlc')):
            return 'windows'
        if any(k in lower for k in ('manjaro',)):
            return 'manjaro'
        if any(k in lower for k in ('arch', 'cachyos', 'endeavouros',
                                    'arcolinux', 'garuda', 'artix', 'archbang',
                                    'archlabs', 'rebornos', 'anarchy', 'blackarch',
                                    'parabola', 'hyperbola', 'archman')):
            return 'arch'
        if any(k in lower for k in ('ubuntu', 'linuxmint', 'pop', 'zorin', 'kubuntu',
                                    'xubuntu', 'lubuntu', 'ubuntu-mate', 'ubuntu-budgie',
                                    'ubuntu-studio', 'edubuntu', 'mythbuntu', 'elementary',
                                    'neon', 'kde neon', 'peppermint', 'regolith',
                                    'pop!_os', 'bubuntu', 'rhino', 'vanilla')):
            return 'ubuntu'
        if any(k in lower for k in ('fedora', 'nobara', 'silverblue', 'kinetic',
                                    'sericea', 'serpentine', 'budgie', 'workstation',
                                    'fedora-coreos', 'fedora-iot', 'fedora-labs',
                                    'fedora-spins', 'fedora-everything')):
            return 'fedora'
        if any(k in lower for k in ('debian', 'devuan', 'sparkylinux', 'mx', 'mxlinux',
                                    'antix', 'kali', 'parrot', 'tails', 'deepin',
                                    'pureos', 'kanotix', 'siduction', 'lmde',
                                    'debian-live', 'raspberry')):
            return 'debian'
        if any(k in lower for k in ('opensuse', 'suse', 'sles', 'leap', 'tumbleweed',
                                    'microos')):
            return 'opensuse'
        if any(k in lower for k in ('void', 'voidlinux')):
            return 'void'
        if any(k in lower for k in ('gentoo', 'calculate', 'funtoo', 'redcore')):
            return 'gentoo'
        if any(k in lower for k in ('slax', 'porteus', 'wifislax')):
            return 'slax'
        if any(k in lower for k in ('puppy', 'fossa', 'bionicpup', 'xenialpup',
                                    'focalpup', 'tahrpup')):
            return 'puppy'
        if any(k in lower for k in ('clonezilla', 'gparted', 'partedmagic', 'pmagic',
                                    'systemrescue', 'systemrescuecd', 'rescatux',
                                    'redorescue', 'redobackup', 'hiren', 'hdt',
                                    'memtest', 'memtest86', 'testdisk')):
            return 'rescue'
        if any(k in lower for k in ('solus', 'soluslive')):
            return 'solus'
        if any(k in lower for k in ('nixos', 'nix')):
            return 'nixos'
        if any(k in lower for k in ('alpine',)):
            return 'alpine'
        if any(k in lower for k in ('photon', 'photonos')):
            return 'photon'
        if any(k in lower for k in ('freebsd', 'ghostbsd', 'nomadbsd', 'furybsd',
                                    'midnightbsd', 'hellosystem', 'trident',
                                    'freenas', 'truenas', 'pfsense', 'opnsense')):
            return 'freebsd'
        if any(k in lower for k in ('proxmox', 'xcp-ng', 'xenserver', 'xcp')):
            return 'proxmox'
        if any(k in lower for k in ('esxi', 'vmware', 'vsphere')):
            return 'esxi'
        if any(k in lower for k in ('macos', 'mac_os', 'macosx', 'osx', 'mac os',
                                    'hackintosh', 'bigsur', 'monterey', 'ventura',
                                    'sonoma', 'sequoia', 'catalina', 'mojave',
                                    'high sierra', 'sierra', 'el capitan',
                                    'yosemite', 'mavericks', 'mountain lion',
                                    'lion', 'snow leopard', 'leopard')):
            return 'macos'
        if any(k in lower for k in ('rocky', 'rockylinux', 'almalinux', 'alma',
                                    'rhel', 'redhat', 'oraclelinux', 'oracle',
                                    'centos', 'fedepel', 'springdal')):
            return 'rhel'
        if any(k in lower for k in ('slackware', 'slacko', 'salix', 'zenwalk',
                                    'vectorlinux')):
            return 'slackware'
        if any(k in lower for k in ('mageia', 'mandriva', 'mandrake', 'rosa')):
            return 'mageia'
        if any(k in lower for k in ('netbsd', 'openbsd', 'dragonfly')):
            return 'bsd'
        if any(k in lower for k in ('tails', 'whonix', 'qubes', 'subgraph')):
            return 'security'
        if any(k in lower for k in ('android', 'androidx86', 'phoenixos', 'blissos',
                                    'primeos')):
            return 'android'
        return 'generic'

    @staticmethod
    def _make_entry(fname: str, safe_name: str, itype: str) -> str:
        iso_path = f'/ISOS/{safe_name}'
        h = (
            f'menuentry "Boot {safe_name}" --class {itype} {{\n'
            f'    set iso_file="{iso_path}"\n'
            f'    search --set=iso_partition --no-floppy --file $iso_file\n'
            f'    if [ -z "$iso_partition" ]; then\n'
            f'        set iso_partition=$data_root\n'
            f'    fi\n'
            f'    probe --set=iso_partition_uuid --fs-uuid $iso_partition\n'
            f'    loopback loop ($iso_partition)$iso_file\n'
        )
        if itype == 'windows':
            return (
                f'{h}'
                f'    insmod chain\n'
                f'    if [ -f (loop)/efi/boot/bootx64.efi ]; then\n'
                f'        if chainloader (loop)/efi/boot/bootx64.efi; then boot; fi\n'
                f'    elif [ -f (loop)/EFI/BOOT/BOOTX64.EFI ]; then\n'
                f'        if chainloader (loop)/EFI/BOOT/BOOTX64.EFI; then boot; fi\n'
                f'    elif [ -f (loop)/efi/microsoft/boot/bootmgfw.efi ]; then\n'
                f'        if chainloader (loop)/efi/microsoft/boot/bootmgfw.efi; then boot; fi\n'
                f'    elif [ -f (loop)/sources/boot.wim ]; then\n'
                f'        echo "Windows WIM-based ISO detected, using boot_iso fallback"\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'macos':
            return (
                f'{h}'
                f'    insmod chain\n'
                f'    insmod hfsplus\n'
                f'    if [ -f (loop)/System/Library/CoreServices/boot.efi ]; then\n'
                f'        chainloader (loop)/System/Library/CoreServices/boot.efi; boot\n'
                f'    elif [ -f (loop)/usr/standalone/i386/boot.efi ]; then\n'
                f'        chainloader (loop)/usr/standalone/i386/boot.efi; boot\n'
                f'    elif [ -f (loop)/efi/boot/bootx64.efi ]; then\n'
                f'        if chainloader (loop)/efi/boot/bootx64.efi; then boot; fi\n'
                f'    elif [ -f (loop)/EFI/BOOT/BOOTX64.EFI ]; then\n'
                f'        if chainloader (loop)/EFI/BOOT/BOOTX64.EFI; then boot; fi\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'manjaro':
            return (
                f'{h}'
                f'    set img_dev="/dev/disk/by-uuid/$iso_partition_uuid"\n'
                f'    if [ -f (loop)/boot/vmlinuz-x86_64 ] && [ -f (loop)/boot/initramfs-x86_64.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz-x86_64 img_dev=$img_dev img_loop=$iso_file\n'
                f'        initrd (loop)/boot/intel_ucode.img (loop)/boot/amd_ucode.img (loop)/boot/initramfs-x86_64.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/boot/vmlinuz-5.15-x86_64 ] && [ -f (loop)/boot/initramfs-5.15-x86_64.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz-5.15-x86_64 img_dev=$img_dev img_loop=$iso_file\n'
                f'        initrd (loop)/boot/intel_ucode.img (loop)/boot/amd_ucode.img (loop)/boot/initramfs-5.15-x86_64.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/boot/vmlinuz-6.1-x86_64 ] && [ -f (loop)/boot/initramfs-6.1-x86_64.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz-6.1-x86_64 img_dev=$img_dev img_loop=$iso_file\n'
                f'        initrd (loop)/boot/intel_ucode.img (loop)/boot/amd_ucode.img (loop)/boot/initramfs-6.1-x86_64.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'arch':
            return (
                f'{h}'
                f'    set img_dev="UUID=$iso_partition_uuid"\n'
                f'    if [ -f (loop)/arch/boot/x86_64/vmlinuz-linux ] && [ -f (loop)/arch/boot/x86_64/initramfs-linux.img ]; then\n'
                f'        linux (loop)/arch/boot/x86_64/vmlinuz-linux img_dev=$img_dev img_loop=$iso_file archisobasedir=arch\n'
                f'        initrd (loop)/arch/boot/intel-ucode.img (loop)/arch/boot/amd-ucode.img (loop)/arch/boot/x86_64/initramfs-linux.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/arch/boot/x86_64/vmlinuz-linux-lts ] && [ -f (loop)/arch/boot/x86_64/initramfs-linux-lts.img ]; then\n'
                f'        linux (loop)/arch/boot/x86_64/vmlinuz-linux-lts img_dev=$img_dev img_loop=$iso_file archisobasedir=arch\n'
                f'        initrd (loop)/arch/boot/x86_64/initramfs-linux-lts.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/arch/boot/x86_64/vmlinuz-linux-zen ] && [ -f (loop)/arch/boot/x86_64/initramfs-linux-zen.img ]; then\n'
                f'        linux (loop)/arch/boot/x86_64/vmlinuz-linux-zen img_dev=$img_dev img_loop=$iso_file archisobasedir=arch\n'
                f'        initrd (loop)/arch/boot/x86_64/initramfs-linux-zen.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/arch/boot/x86_64/vmlinuz-linux-hardened ] && [ -f (loop)/arch/boot/x86_64/initramfs-linux-hardened.img ]; then\n'
                f'        linux (loop)/arch/boot/x86_64/vmlinuz-linux-hardened img_dev=$img_dev img_loop=$iso_file archisobasedir=arch\n'
                f'        initrd (loop)/arch/boot/x86_64/initramfs-linux-hardened.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/boot/vmlinuz-x86_64 ] && [ -f (loop)/boot/initramfs-x86_64.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz-x86_64 img_dev=$img_dev img_loop=$iso_file\n'
                f'        initrd (loop)/boot/initramfs-x86_64.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'ubuntu':
            return (
                f'{h}'
                f'    set gfxpayload=keep\n'
                f'    if [ -f (loop)/casper/vmlinuz ]; then\n'
                f'        linux (loop)/casper/vmlinuz iso-scan/filename=$iso_file boot=casper quiet splash ---\n'
                f'        if [ -f (loop)/casper/initrd ]; then\n'
                f'            initrd (loop)/casper/initrd\n'
                f'        elif [ -f (loop)/casper/initrd.img ]; then\n'
                f'            initrd (loop)/casper/initrd.img\n'
                f'        fi\n'
                f'        boot\n'
                f'    elif [ -f (loop)/casper/vmlinuz.efi ]; then\n'
                f'        linux (loop)/casper/vmlinuz.efi iso-scan/filename=$iso_file boot=casper quiet splash ---\n'
                f'        if [ -f (loop)/casper/initrd ]; then\n'
                f'            initrd (loop)/casper/initrd\n'
                f'        elif [ -f (loop)/casper/initrd.lz ]; then\n'
                f'            initrd (loop)/casper/initrd.lz\n'
                f'        fi\n'
                f'        boot\n'
                f'    elif [ -f (loop)/live/vmlinuz ] && [ -f (loop)/live/initrd.img ]; then\n'
                f'        linux (loop)/live/vmlinuz boot=live findiso=$iso_file components splash\n'
                f'        initrd (loop)/live/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'debian':
            return (
                f'{h}'
                f'    if [ -f (loop)/live/vmlinuz ] && [ -f (loop)/live/initrd.img ]; then\n'
                f'        linux (loop)/live/vmlinuz boot=live buuid=$iso_partition_uuid findiso=$iso_file components\n'
                f'        initrd (loop)/live/initrd.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/install.amd/vmlinuz ] && [ -f (loop)/install.amd/initrd.gz ]; then\n'
                f'        linux (loop)/install.amd/vmlinuz boot=live buuid=$iso_partition_uuid findiso=$iso_file vga=788\n'
                f'        initrd (loop)/install.amd/initrd.gz\n'
                f'        boot\n'
                f'    elif [ -f (loop)/install.amd/vmlinuz ] && [ -f (loop)/install.amd/gtk/initrd.gz ]; then\n'
                f'        linux (loop)/install.amd/vmlinuz boot=live buuid=$iso_partition_uuid findiso=$iso_file vga=788\n'
                f'        initrd (loop)/install.amd/gtk/initrd.gz\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'fedora':
            return (
                f'{h}'
                f'    probe --set=isolabel --label (loop)\n'
                f'    if [ -f (loop)/images/pxeboot/vmlinuz ] && [ -f (loop)/images/pxeboot/initrd.img ]; then\n'
                f'        linux (loop)/images/pxeboot/vmlinuz root=live:CDLABEL=$isolabel rd.live.image iso-scan/filename=$iso_file quiet rhgb\n'
                f'        initrd (loop)/images/pxeboot/initrd.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/isolinux/vmlinuz ] && [ -f (loop)/isolinux/initrd.img ]; then\n'
                f'        linux (loop)/isolinux/vmlinuz root=live:CDLABEL=$isolabel rd.live.image iso-scan/filename=$iso_file quiet rhgb\n'
                f'        initrd (loop)/isolinux/initrd.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/LiveOS/squashfs.img ]; then\n'
                f'        linux (loop)/isolinux/vmlinuz root=live:CDLABEL=$isolabel rd.live.image quiet rhgb\n'
                f'        initrd (loop)/isolinux/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'rhel':
            return (
                f'{h}'
                f'    if [ -f (loop)/images/pxeboot/vmlinuz ] && [ -f (loop)/images/pxeboot/initrd.img ]; then\n'
                f'        linux (loop)/images/pxeboot/vmlinuz repo=hd:UUID=$iso_partition_uuid:/ quiet rhgb\n'
                f'        initrd (loop)/images/pxeboot/initrd.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/isolinux/vmlinuz ] && [ -f (loop)/isolinux/initrd.img ]; then\n'
                f'        linux (loop)/isolinux/vmlinuz repo=hd:UUID=$iso_partition_uuid:/ quiet rhgb\n'
                f'        initrd (loop)/isolinux/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        probe --set=isolabel --label (loop)\n'
                f'        if [ -f (loop)/images/pxeboot/vmlinuz ] && [ -f (loop)/images/pxeboot/initrd.img ]; then\n'
                f'            linux (loop)/images/pxeboot/vmlinuz root=live:CDLABEL=$isolabel rd.live.image quiet rhgb\n'
                f'            initrd (loop)/images/pxeboot/initrd.img\n'
                f'            boot\n'
                f'        elif [ -f (loop)/isolinux/vmlinuz ] && [ -f (loop)/isolinux/initrd.img ]; then\n'
                f'            linux (loop)/isolinux/vmlinuz root=live:CDLABEL=$isolabel rd.live.image quiet rhgb\n'
                f'            initrd (loop)/isolinux/initrd.img\n'
                f'            boot\n'
                f'        else\n'
                f'            boot_iso "($iso_partition)" "$iso_file"\n'
                f'        fi\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'opensuse':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/x86_64/loader/linux ] && [ -f (loop)/boot/x86_64/loader/initrd ]; then\n'
                f'        linux (loop)/boot/x86_64/loader/linux splash=silent quiet isofrom_device=$iso_partition isofrom_system=$iso_file\n'
                f'        initrd (loop)/boot/x86_64/loader/initrd\n'
                f'        boot\n'
                f'    elif [ -f (loop)/boot/x86_64/loader/linux ] && [ -f (loop)/boot/x86_64/loader/initrd.gz ]; then\n'
                f'        linux (loop)/boot/x86_64/loader/linux splash=silent quiet isofrom_device=$iso_partition isofrom_system=$iso_file\n'
                f'        initrd (loop)/boot/x86_64/loader/initrd.gz\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'void':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/vmlinuz ] && [ -f (loop)/boot/initrd ]; then\n'
                f'        linux (loop)/boot/vmlinuz img_dev=$iso_partition img_loop=$iso_file\n'
                f'        initrd (loop)/boot/initrd\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'gentoo':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/gentoo ] && [ -f (loop)/boot/gentoo.igz ]; then\n'
                f'        linux (loop)/boot/gentoo dokeymap looptype=squashfs loop=/image.squashfs cdroot=/dev/loop0\n'
                f'        initrd (loop)/boot/gentoo.igz\n'
                f'        boot\n'
                f'    elif [ -f (loop)/isolinux/gentoo ] && [ -f (loop)/isolinux/gentoo.igz ]; then\n'
                f'        linux (loop)/isolinux/gentoo dokeymap looptype=squashfs loop=/image.squashfs cdroot=/dev/loop0\n'
                f'        initrd (loop)/isolinux/gentoo.igz\n'
                f'        boot\n'
                f'    elif [ -f (loop)/boot/vmlinuz ] && [ -f (loop)/boot/initrd.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz cdroot\n'
                f'        initrd (loop)/boot/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'rescue':
            return (
                f'{h}'
                f'    if [ -f (loop)/live/vmlinuz ] && [ -f (loop)/live/initrd.img ]; then\n'
                f'        linux (loop)/live/vmlinuz boot=live findiso=$iso_file components\n'
                f'        initrd (loop)/live/initrd.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/sysresccd/boot/x86_64/vmlinuz ] && [ -f (loop)/sysresccd/boot/x86_64/sysresccd.img ]; then\n'
                f'        linux (loop)/sysresccd/boot/x86_64/vmlinuz archisobasedir=sysresccd archisolabel=SYSRESCUECD\n'
                f'        initrd (loop)/sysresccd/boot/x86_64/sysresccd.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/pmagic/bzImage ] && [ -f (loop)/pmagic/initrd.img ]; then\n'
                f'        linux (loop)/pmagic/bzImage edd=off noapic\n'
                f'        initrd (loop)/pmagic/initrd.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/clonezilla/live/vmlinuz ] && [ -f (loop)/clonezilla/live/initrd.img ]; then\n'
                f'        linux (loop)/clonezilla/live/vmlinuz boot=live findiso=$iso_file components\n'
                f'        initrd (loop)/clonezilla/live/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'slax':
            return (
                f'{h}'
                f'    if [ -f (loop)/slax/boot/vmlinuz ] && [ -f (loop)/slax/boot/initrfs.img ]; then\n'
                f'        linux (loop)/slax/boot/vmlinuz from=$iso_file slax_dir=/slax load_ramdisk=1 prompt_ramdisk=0\n'
                f'        initrd (loop)/slax/boot/initrfs.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/boot/vmlinuz ] && [ -f (loop)/boot/initrfs.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz from=$iso_file load_ramdisk=1 prompt_ramdisk=0\n'
                f'        initrd (loop)/boot/initrfs.img\n'
                f'        boot\n'
                f'    elif [ -f (loop)/porteus/boot/vmlinuz ] && [ -f (loop)/porteus/boot/initrd.xz ]; then\n'
                f'        linux (loop)/porteus/boot/vmlinuz from=$iso_file\n'
                f'        initrd (loop)/porteus/boot/initrd.xz\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'puppy':
            return (
                f'{h}'
                f'    if [ -f (loop)/vmlinuz ] && [ -f (loop)/initrd.gz ]; then\n'
                f'        linux (loop)/vmlinuz pmedia=cd\n'
                f'        initrd (loop)/initrd.gz\n'
                f'        boot\n'
                f'    elif [ -f (loop)/vmlinuz ] && [ -f (loop)/initrd.img ]; then\n'
                f'        linux (loop)/vmlinuz pmedia=cd\n'
                f'        initrd (loop)/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'solus':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/vmlinuz ] && [ -f (loop)/boot/initrd.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz iso-scan/filename=$iso_file boot=live quiet splash\n'
                f'        initrd (loop)/boot/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'nixos':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/vmlinuz ] && [ -f (loop)/boot/initrd ]; then\n'
                f'        linux (loop)/boot/vmlinuz findiso=$iso_file\n'
                f'        initrd (loop)/boot/initrd\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'alpine':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/vmlinuz-lts ] && [ -f (loop)/boot/initramfs-lts ]; then\n'
                f'        linux (loop)/boot/vmlinuz-lts alpine_dev=$iso_partition:$iso_file modloop=$iso_partition:$iso_file modules=loop,squashfs quiet\n'
                f'        initrd (loop)/boot/initramfs-lts\n'
                f'        boot\n'
                f'    elif [ -f (loop)/boot/vmlinuz-virt ] && [ -f (loop)/boot/initramfs-virt ]; then\n'
                f'        linux (loop)/boot/vmlinuz-virt alpine_dev=$iso_partition:$iso_file modloop=$iso_partition:$iso_file modules=loop,squashfs quiet\n'
                f'        initrd (loop)/boot/initramfs-virt\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'photon':
            return (
                f'{h}'
                f'    if [ -f (loop)/isolinux/vmlinuz ] && [ -f (loop)/isolinux/initrd.img ]; then\n'
                f'        linux (loop)/isolinux/vmlinuz root=/dev/cdrom\n'
                f'        initrd (loop)/isolinux/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'freebsd':
            return (
                f'{h}'
                f'    insmod chain\n'
                f'    insmod hfsplus\n'
                f'    if [ -f (loop)/efi/boot/bootx64.efi ]; then\n'
                f'        if chainloader (loop)/efi/boot/bootx64.efi; then boot; fi\n'
                f'    elif [ -f (loop)/EFI/BOOT/BOOTX64.EFI ]; then\n'
                f'        if chainloader (loop)/EFI/BOOT/BOOTX64.EFI; then boot; fi\n'
                f'    elif [ -f (loop)/boot/kernel/kernel ]; then\n'
                f'        kfreebsd (loop)/boot/kernel/kernel\n'
                f'        if [ -f (loop)/boot/device.hints ]; then\n'
                f'            kfreebsd_loadenv (loop)/boot/device.hints\n'
                f'        fi\n'
                f'        set kFreeBSD.vfs.root.mountfrom=cd9660:/dev/iso9660/ISO\n'
                f'        kfreebsd_module (loop)/boot/kernel/geom_uzip.ko\n'
                f'        if [ -f (loop)/boot/kernel/initrd ]; then\n'
                f'            kfreebsd_module (loop)/boot/kernel/initrd type=rootfs\n'
                f'        fi\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'bsd':
            return (
                f'{h}'
                f'    insmod chain\n'
                f'    if [ -f (loop)/efi/boot/bootx64.efi ]; then\n'
                f'        if chainloader (loop)/efi/boot/bootx64.efi; then boot; fi\n'
                f'    elif [ -f (loop)/EFI/BOOT/BOOTX64.EFI ]; then\n'
                f'        if chainloader (loop)/EFI/BOOT/BOOTX64.EFI; then boot; fi\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'proxmox':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/linux26 ] && [ -f (loop)/boot/initrd.img ]; then\n'
                f'        linux (loop)/boot/linux26\n'
                f'        initrd (loop)/boot/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'esxi':
            return (
                f'{h}'
                f'    if [ -f (loop)/efi/boot/bootx64.efi ]; then\n'
                f'        if chainloader (loop)/efi/boot/bootx64.efi; then boot; fi\n'
                f'    elif [ -f (loop)/EFI/BOOT/BOOTX64.EFI ]; then\n'
                f'        if chainloader (loop)/EFI/BOOT/BOOTX64.EFI; then boot; fi\n'
                f'    elif [ -f (loop)/isolinux/vmlinuz ] && [ -f (loop)/isolinux/initrd.img ]; then\n'
                f'        linux (loop)/isolinux/vmlinuz\n'
                f'        initrd (loop)/isolinux/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'slackware':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/vmlinuz ] && [ -f (loop)/boot/initrd.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz load_ramdisk=1 prompt_ramdisk=0 rw SLACK_KERNEL=vmlinuz\n'
                f'        initrd (loop)/boot/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'mageia':
            return (
                f'{h}'
                f'    if [ -f (loop)/boot/vmlinuz ] && [ -f (loop)/boot/initrd.img ]; then\n'
                f'        linux (loop)/boot/vmlinuz iso-scan/filename=$iso_file\n'
                f'        initrd (loop)/boot/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'security':
            return (
                f'{h}'
                f'    if [ -f (loop)/live/vmlinuz ] && [ -f (loop)/live/initrd.img ]; then\n'
                f'        linux (loop)/live/vmlinuz boot=live findiso=$iso_file components\n'
                f'        initrd (loop)/live/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        if itype == 'android':
            return (
                f'{h}'
                f'    insmod chain\n'
                f'    if [ -f (loop)/efi/boot/bootx64.efi ]; then\n'
                f'        if chainloader (loop)/efi/boot/bootx64.efi; then boot; fi\n'
                f'    elif [ -f (loop)/EFI/BOOT/BOOTX64.EFI ]; then\n'
                f'        if chainloader (loop)/EFI/BOOT/BOOTX64.EFI; then boot; fi\n'
                f'    elif [ -f (loop)/kernel ] && [ -f (loop)/initrd.img ]; then\n'
                f'        linux (loop)/kernel root=/dev/ram0 androidboot.hardware=android_x86\n'
                f'        initrd (loop)/initrd.img\n'
                f'        boot\n'
                f'    else\n'
                f'        boot_iso "($iso_partition)" "$iso_file"\n'
                f'    fi\n'
                f'}}'
            )
        return (
            f'{h}'
            f'    boot_iso "($iso_partition)" "$iso_file"\n'
            f'}}'
        )

    @staticmethod
    def _generate_iso_menu(data_drive: str):
        iso_dir = os.path.join(data_drive, 'ISOS')
        menu_path = os.path.join(iso_dir, '.iso_menu.cfg')
        os.makedirs(iso_dir, exist_ok=True)

        dummy_path = os.path.join(iso_dir, 'DUMMY')
        if not os.path.isfile(dummy_path):
            with open(dummy_path, 'w', encoding='utf-8') as f:
                f.write('# Kouprey Boot ISO directory marker\n')

        entries = []
        type_counts = {}
        for fname in sorted(os.listdir(iso_dir)):
            if fname == '.iso_menu.cfg':
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ('.iso', '.img'):
                continue
            safe_name = fname.replace('"', '\\"')
            itype = KoupreyFlashWorker._detect_iso_type(fname)
            entries.append(KoupreyFlashWorker._make_entry(fname, safe_name, itype))
            type_counts[itype] = type_counts.get(itype, 0) + 1
        type_summary = ', '.join(f'{k}={v}' for k, v in sorted(type_counts.items()))
        with open(menu_path, 'w', encoding='utf-8') as f:
            f.write('# Kouprey Boot ISO menu - auto-generated\n')
            f.write(f'# {len(entries)} ISO(s) found in /ISOS/\n')
            f.write(f'# Types: {type_summary}\n')
            f.write('# Re-generate: python flash_headless.py -gen-iso-menu -disk N\n')
            f.write('#\n')
            f.write('# ISO boot strategy:\n')
            f.write('#  1. Specific entries for known distro families use hardcoded\n')
            f.write('#     kernel/initrd paths for reliable booting:\n')
            f.write('#     windows, macos, manjaro, arch, ubuntu, debian, fedora,\n')
            f.write('#     rhel, opensuse, void, gentoo, rescue, slax, puppy, solus,\n')
            f.write('#     nixos, alpine, photon, freebsd, proxmox, esxi, slackware,\n')
            f.write('#     mageia, security (tails/qubes), android\n')
            f.write('#  2. Generic entries delegate to boot_iso() which tries:\n')
            f.write('#     a) loopback.cfg / grub.cfg from inside the ISO (most distros)\n')
            f.write("#     b) chainload ISO's own bootx64.efi (UEFI)\n")
            f.write('#     c) memdisk fallback (Legacy BIOS)\n')
            f.write('#  3. All kernels/initrds are READ FROM INSIDE THE ISO via\n')
            f.write('#     GRUB loopback mount - no separate download needed.\n')
            f.write('#\n')
            f.write('# If a specific entry fails, comment it out and the\n')
            f.write('# generic boot_iso fallback will handle it automatically.\n')
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
