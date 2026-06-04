import os
import sys
import subprocess
import shutil
import platform
import tempfile
import datetime

from PyQt6.QtCore import QThread, pyqtSignal


def _create_log_file(prefix: str) -> str:
    log_dir = os.path.join(tempfile.gettempdir(), 'kouprey-boot')
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(log_dir, f'{prefix}_{ts}.log')


_base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
GRUB_SRC = os.path.join(_base, 'assets', 'grub')


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


def _grub_cfg_content(data_part_uuid: str = '', persist_uuid: str = '') -> str:
    return f'''set default=0
set timeout=30
set gfxmode=auto
set gfxpayload=keep

if loadfont $prefix/fonts/unicode.pf2; then
  set gfxmode=auto
  terminal_output gfxterm
fi

insmod all_video
insmod part_gpt
insmod part_msdos
insmod fat
insmod exfat
insmod ntfs
insmod ext2
insmod iso9660
insmod udf
insmod loopback
insmod search
insmod search_fs_uuid
insmod gfxterm_background
insmod png
insmod jpeg
insmod gfxmenu
insmod chain
insmod boot

search --no-floppy --set=data_root --file /themes/.marker

if [ "$data_root" = "" ] ; then
  search --no-floppy --set=data_root --file /themes/.marker
fi

set theme=($data_root)/themes/theme.txt

submenu "Boot ISO" {{
  set data_root=""
  search --set=data_root --file /ISOS/DUMMY

  if [ "$data_root" = "" ] ; then
    search --set=data_root --file /ISOS/DUMMY
  fi

  if [ "$data_root" = "" ] ; then
    search --set=data_root --file /ISOS/DUMMY  
  fi

  if [ "$data_root" != "" ] ; then
    for iso in ($data_root)/ISOS/*.iso ($data_root)/ISOS/*.ISO ; do
      if [ -f "$iso" ] ; then
        menuentry "${{iso##*/}}" --class iso {{
          loopback loop "$iso"
          if [ -f (loop)/casper/vmlinuz ]; then
            linux (loop)/casper/vmlinuz boot=casper iso-scan/filename="$iso" quiet splash ---
            initrd (loop)/casper/initrd
          elif [ -f (loop)/casper/vmlinuz.efi ]; then
            linux (loop)/casper/vmlinuz.efi boot=casper iso-scan/filename="$iso" quiet splash ---
            initrd (loop)/casper/initrd
          elif [ -f (loop)/live/vmlinuz ]; then
            linux (loop)/live/vmlinuz boot=live findiso="$iso" quiet splash ---
            initrd (loop)/live/initrd.img
          elif [ -f (loop)/live/vmlinuz64 ]; then
            linux (loop)/live/vmlinuz64 boot=live findiso="$iso" quiet splash ---
            initrd (loop)/live/initrd64.img
          elif [ -f (loop)/install/vmlinuz ]; then
            linux (loop)/install/vmlinuz iso-scan/filename="$iso" quiet ---
            initrd (loop)/install/initrd.gz
          elif [ -f (loop)/images/pxeboot/vmlinuz ]; then
            linux (loop)/images/pxeboot/vmlinuz iso-scan/filename="$iso" quiet ---
            initrd (loop)/images/pxeboot/initrd.img
          elif [ -f (loop)/isolinux/vmlinuz ]; then
            linux (loop)/isolinux/vmlinuz iso-scan/filename="$iso" quiet ---
            initrd (loop)/isolinux/initrd.img
          else
            echo "Unknown ISO type: $iso"
          fi
        }}
      fi
    done
  fi

  menuentry "Rescan ISOs" {{
    configfile $prefix/grub.cfg
  }}
}}

submenu "Boot Windows ISO" {{
  set data_root=""
  search --no-floppy --set=data_root --file /ISOS/DUMMY

  if [ "$data_root" != "" ] ; then
    for iso in ($data_root)/ISOS/*.iso ($data_root)/ISOS/*.ISO ; do
      if [ -f "$iso" ] ; then
        menuentry "${{iso##*/}}" --class windows {{
          loopback loop "$iso"
          insmod ntfs
          insmod chain
          ntboot --efi=$prefix/wimboot "$iso"
        }}
      fi
    done
  fi
}}

submenu "Advanced" {{
  menuentry "Reboot" {{
    reboot
  }}
  menuentry "Shutdown" {{
    halt
  }}
  menuentry "EFI Firmware Setup" {{
    fwsetup
  }}
}}
'''


def _build_grub_cfg(data_part_uuid: str = '', persist_uuid: str = '') -> str:
    return _grub_cfg_content(data_part_uuid, persist_uuid)


class KoupreyFlashWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int, file_system: str = 'exfat'):
        super().__init__()
        self._disk_number = disk_number
        self._file_system = file_system
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

        self._log('Step 3: Creating ESP (512 MB FAT32)...')
        out, rc = _run_diskpart(['create partition efi size=512'], disk, timeout=60)
        if rc != 0:
            self._last_error = out or 'ESP partition creation failed'
            self._log(f'ESP partition creation failed: {self._last_error}')
            return False
        self._log('ESP partition created, formatting...')

        esp_mount = os.path.join(tempfile.gettempdir(), 'kp_esp')
        os.makedirs(esp_mount, exist_ok=True)
        ps_format = f'''
$part = Get-Partition -DiskNumber {disk} | Where-Object {{ $_.Type -eq "EFI" -or $_.GptType -eq "{{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}}" }} | Select-Object -First 1
if (-not $part) {{ $part = Get-Partition -DiskNumber {disk} | Sort-Object PartitionNumber | Select-Object -First 1 }}
$part | Format-Volume -FileSystem FAT32 -NewFileSystemLabel "KoupreyBoot" -Confirm:$false -ErrorAction Stop
Add-PartitionAccessPath -DiskNumber {disk} -PartitionNumber $part.PartitionNumber -AccessPath "{esp_mount}" -ErrorAction Stop
Write-Output "ESP={esp_mount}"
'''
        out, rc = _run_powershell(ps_format, timeout=60)
        if rc != 0 or 'Error' in out or 'ESP=' not in out:
            self._last_error = out or 'ESP creation failed'
            self._log(f'ESP creation failed: {self._last_error}')
            return False
        esp_drive = ''
        for line in out.split('\n'):
            if line.startswith('ESP='):
                esp_drive = line.split('=', 1)[1].strip()
                break
        self._log('ESP mounted to folder (hidden from Explorer)')
        self.progress.emit('ESP created...')

        self._log('Step 4: Creating DATA partition...')
        out, rc = _run_diskpart(['create partition primary'], disk, timeout=60)
        if rc != 0:
            self._last_error = out or 'DATA partition creation failed'
            self._log(f'DATA partition creation failed: {self._last_error}')
            return False
        self._log('DATA partition created, formatting...')

        fs_map = {'exfat': 'EXFAT', 'ntfs': 'NTFS', 'fat32': 'FAT32'}
        fs_arg = fs_map.get(fs, 'EXFAT')
        ps_format = f'''
$part = Get-Partition -DiskNumber {disk} | Sort-Object PartitionNumber -Descending | Select-Object -First 1
$part | Format-Volume -FileSystem {fs_arg} -NewFileSystemLabel "KoupreyData" -Confirm:$false -ErrorAction Stop
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
        self.progress.emit('Formatting done...')

        self._log('Step 5: Installing GRUB2...')
        self.progress.emit('Installing GRUB2...')
        ok = self._install_grub(esp_drive, data_drive)
        if not ok:
            return False

        self._log('Step 6: Creating ISOs directory and GRUB marker...')
        import time
        iso_dir = os.path.join(data_drive, 'ISOS')
        os.makedirs(iso_dir, exist_ok=True)
        dummy_path = os.path.join(iso_dir, 'DUMMY')
        if not os.path.isfile(dummy_path):
            with open(dummy_path, 'w', encoding='utf-8') as f:
                f.write('# Kouprey Boot ISO directory marker\n')
        self._log(f'Created {iso_dir}')
        themes_dir = os.path.join(data_drive, 'themes')
        os.makedirs(themes_dir, exist_ok=True)
        marker_path = os.path.join(themes_dir, '.marker')
        with open(marker_path, 'w', encoding='utf-8') as f:
            f.write('# Kouprey Boot theme directory marker\n')
        if os.path.isfile(marker_path):
            self._log(f'GRUB marker created: {marker_path} ({os.path.getsize(marker_path)} bytes)')
        else:
            self._log(f'Warning: could not create GRUB marker (GRUB needs this file)')
        self._log(f'Created {themes_dir}')

        self._log('Step 7: Writing grub.cfg...')
        cfg_content = _build_grub_cfg()
        cfg_path = os.path.join(esp_drive, 'EFI', 'BOOT', 'grub.cfg')
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, 'w', encoding='utf-8') as f:
            f.write(cfg_content)
        self._log('grub.cfg written')

        self._log('Step 8: Removing ESP mount (hidden from Windows)...')
        if os.path.exists(esp_mount):
            out1, rc1 = _run_powershell(f'Remove-PartitionAccessPath -DiskNumber {disk} -PartitionNumber 1 -AccessPath "{esp_mount}" -ErrorAction Stop', timeout=15)
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

        self._log(f'Copying BOOTX64.EFI...')
        shutil.copy2(os.path.join(src, 'EFI', 'BOOT', 'BOOTX64.EFI'),
                     os.path.join(dest_efi, 'BOOTX64.EFI'))

        self._log(f'Copying wimboot...')
        wimboot_src = os.path.join(src, 'EFI', 'BOOT', 'wimboot')
        if os.path.isfile(wimboot_src):
            shutil.copy2(wimboot_src, os.path.join(dest_efi, 'wimboot'))

        self._log(f'Copying GRUB2 modules...')
        mod_src = os.path.join(src, 'grub', 'x86_64-efi')
        if os.path.isdir(mod_src):
            mod_dst = os.path.join(dest_grub, 'x86_64-efi')
            os.makedirs(mod_dst, exist_ok=True)
            for fname in os.listdir(mod_src):
                if fname.endswith('.mod'):
                    shutil.copy2(os.path.join(mod_src, fname),
                                 os.path.join(mod_dst, fname))
            self._log(f'Modules copied ({len(os.listdir(mod_dst))} files)')

        self._log(f'Copying fonts...')
        font_src = os.path.join(src, 'grub', 'fonts')
        if os.path.isdir(font_src):
            font_dst = os.path.join(dest_grub, 'fonts')
            os.makedirs(font_dst, exist_ok=True)
            for fname in os.listdir(font_src):
                shutil.copy2(os.path.join(font_src, fname),
                             os.path.join(font_dst, fname))

        self._log(f'Copying default theme (Vimix)...')
        theme_src = os.path.join(src, 'themes', 'Vimix')
        if os.path.isdir(theme_src):
            for fname in os.listdir(theme_src):
                s = os.path.join(theme_src, fname)
                d = os.path.join(dest_themes, fname)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
            self._log(f'Default theme copied to {dest_themes}')

        old_marker = os.path.join(data_drive, 'THEMES')
        if os.path.isfile(old_marker):
            os.remove(old_marker)
            self._log(f'Removed old THEMES marker (now using themes/.marker)')

        marker_path = os.path.join(dest_themes, '.marker')
        if not os.path.isfile(marker_path):
            with open(marker_path, 'w', encoding='utf-8') as f:
                f.write('# Kouprey Boot GRUB data partition marker\n')

        self._log('GRUB2 installed successfully')
        return True

    def _flash_linux(self) -> bool:
        self._log('Linux flash not yet implemented')
        return False


def create_flash_worker(disk_number: int, file_system: str = 'exfat'):
    return KoupreyFlashWorker(disk_number, file_system)


class DeployWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int, mount_point: str, data_mount_point: str, grub_dir: str, options: dict):
        super().__init__()
        self._disk = disk_number
        self._mount = mount_point if mount_point.endswith('\\') else mount_point + '\\' if mount_point else ''
        self._data_mount = (data_mount_point if data_mount_point.endswith('\\') else data_mount_point + '\\') if data_mount_point else self._mount
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

    def _mount_esp(self) -> str:
        self._esp_mount = os.path.join(tempfile.gettempdir(), 'kp_esp_d')
        os.makedirs(self._esp_mount, exist_ok=True)
        ps = f'Add-PartitionAccessPath -DiskNumber {self._disk} -PartitionNumber 1 -AccessPath "{self._esp_mount}" -ErrorAction Stop'
        out, rc = _run_powershell(ps, timeout=15)
        if rc == 0:
            return self._esp_mount
        return ''

    def _unmount_esp(self):
        if self._esp_mount and os.path.exists(self._esp_mount):
            _run_powershell(f'Remove-PartitionAccessPath -DiskNumber {self._disk} -PartitionNumber 1 -AccessPath "{self._esp_mount}" -ErrorAction Stop', timeout=10)
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

        try:
            theme_name = self._options.get('theme')
            if theme_name and self._options.get('theme_path'):
                self.progress.emit(f'Applying theme: {theme_name}...')

                themes_root = os.path.join(self._data_mount, 'themes')
                old_marker = os.path.join(self._data_mount, 'THEMES')
                if os.path.isfile(old_marker):
                    os.remove(old_marker)
                    self._log('Removed old THEMES marker file')
                if os.path.isfile(themes_root):
                    os.remove(themes_root)
                    self._log('Removed file blocking themes/ directory')
                os.makedirs(themes_root, exist_ok=True)

                # Preserve .marker, clear everything else
                marker_path = os.path.join(themes_root, '.marker')
                marker_content = ''
                if os.path.isfile(marker_path):
                    with open(marker_path, 'r', encoding='utf-8') as f:
                        marker_content = f.read()
                for item in os.listdir(themes_root):
                    if item == '.marker':
                        continue
                    item_path = os.path.join(themes_root, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)

                shutil.copytree(self._options['theme_path'], themes_root, dirs_exist_ok=True)
                with open(marker_path, 'w', encoding='utf-8') as f:
                    f.write(marker_content or '# Kouprey Boot GRUB data partition marker\n')
                self._log(f'Theme "{theme_name}" deployed to {themes_root}')

            self.finished.emit(True, f'Deployment complete!\nLog: {self._log_path}')

        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, f'{e}\nLog: {self._log_path}')
        finally:
            pass
