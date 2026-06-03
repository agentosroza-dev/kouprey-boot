import os
import sys
import subprocess
import shutil
import json
import platform
import time
import threading

from PyQt6.QtCore import QThread, pyqtSignal


_base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
GRUB_SRC = os.path.join(_base, 'assets', 'grub')


def _run_powershell(script: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ''


def _hide_windows_by_pid(pid, timeout=10):
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_callback(hwnd, _lparam):
            wp = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
            if wp.value == pid:
                user32.ShowWindow(hwnd, 0)
            return True
        callback = WNDENUMPROC(enum_callback)
        deadline = time.time() + timeout
        while time.time() < deadline:
            user32.EnumWindows(callback, 0)
            time.sleep(0.3)
    except Exception:
        pass


def _run_process(args, log_callback, progress_callback, hide_window=False, stdin_data=''):
    kwargs = dict(
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if platform.system() == 'Windows':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(args, **kwargs)

    if hide_window and platform.system() == 'Windows':
        threading.Thread(target=_hide_windows_by_pid, args=(proc.pid,), daemon=True).start()

    if stdin_data:
        threading.Thread(
            target=lambda: (proc.stdin.write(stdin_data), proc.stdin.close()),
            daemon=True,
        ).start()

    for line in iter(proc.stdout.readline, ''):
        line = line.strip()
        if not line:
            continue
        log_callback(line)
    proc.wait()
    return proc.returncode


def _grub_cfg_content(data_part_uuid: str = '', persist_uuid: str = '') -> str:
    return f'''set default=0
set timeout=30
set gfxmode=auto
set gfxpayload=keep

if loadfont $prefix/fonts/unicode.pf2; then
  set gfxmode=auto
  terminal_output gfxterm
fi

set theme=$prefix/themes/starfield/theme.txt

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

menuentry "Kouprey Boot" --class kouprey {{
  echo "Welcome to Kouprey Boot"
}}

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
    for iso in $data_root/ISOS/*.iso $data_root/ISOS/*.ISO ; do
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
  search --set=data_root --file /ISOS/DUMMY

  if [ "$data_root" != "" ] ; then
    for iso in $data_root/ISOS/*.iso $data_root/ISOS/*.ISO ; do
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

menuentry "Boot from next device" {{
  exit
}}
'''


def _build_grub_cfg(data_part_uuid: str = '', persist_uuid: str = '') -> str:
    return _grub_cfg_content(data_part_uuid, persist_uuid)


def _get_grub_dir() -> str:
    return GRUB_SRC


def find_grub_directory() -> str:
    if os.path.isdir(GRUB_SRC):
        return GRUB_SRC
    return ''


def get_grub_version() -> str:
    return '2.14'


def get_platform_name() -> str:
    return platform.system()


def check_usb_has_grub(mount_point: str) -> bool:
    efi_path = os.path.join(mount_point, 'EFI', 'BOOT', 'BOOTX64.EFI')
    return os.path.isfile(efi_path)


class KoupreyFlashWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int, file_system: str = 'exfat',
                 persistence_size_mb: int = 0):
        super().__init__()
        self._disk_number = disk_number
        self._file_system = file_system
        self._persist_mb = persistence_size_mb
        self._grub_src = _get_grub_dir()

    def run(self):
        sys_name = platform.system()
        try:
            self.log.emit(f'Kouprey Boot flash starting on disk #{self._disk_number}')
            self.progress.emit('Preparing disk...')

            if sys_name == 'Windows':
                ok = self._flash_windows()
            else:
                self.log.emit('Linux support coming soon')
                ok = False

            if ok:
                self.progress.emit('Kouprey Boot installed successfully!')
                self.finished.emit(True, 'Kouprey Boot has been installed on the USB drive.')
            else:
                self.finished.emit(False, 'Flash failed — check the log for details.')
        except Exception as e:
            self.finished.emit(False, str(e))

    def _flash_windows(self) -> bool:
        disk = self._disk_number
        fs = self._file_system
        pmb = self._persist_mb

        self.log.emit(f'Step 1: Clearing disk #{disk}...')
        script = f'''
$disk = Get-Disk -Number {disk} -ErrorAction SilentlyContinue
if (-not $disk) {{ Write-Error "Disk #{disk} not found"; exit 1 }}
Clear-Disk -Number {disk} -RemoveData -RemoveOEM -Confirm:$false -ErrorAction Stop
Write-Output "Disk cleared"
'''
        out = _run_powershell(script, timeout=60)
        if 'Error' in out:
            self.log.emit(f'Clear-Disk failed: {out}')
            return False
        self.log.emit('Disk cleared')

        self.log.emit('Step 2: Initializing GPT...')
        script = f'''
Initialize-Disk -Number {disk} -PartitionStyle GPT -Confirm:$false -ErrorAction Stop
Write-Output "GPT initialized"
'''
        out = _run_powershell(script, timeout=30)
        if 'Error' in out:
            self.log.emit(f'Initialize-Disk failed: {out}')
            return False
        self.log.emit('GPT partition table created')
        self.progress.emit('Creating partitions...')

        self.log.emit('Step 3: Creating ESP (512 MB FAT32)...')
        script = f'''
$esp = New-Partition -DiskNumber {disk} -Size 512MB -IsActive -ErrorAction Stop
$esp | Format-Volume -FileSystem FAT32 -NewFileSystemLabel "Kouprey Boot" -Confirm:$false -ErrorAction Stop
$espDrive = ($esp | Get-Volume).DriveLetter + ":\\"
Write-Output "ESP=$espDrive"
'''
        out = _run_powershell(script, timeout=60)
        if 'Error' in out or 'ESP=' not in out:
            self.log.emit(f'ESP creation failed: {out}')
            return False
        esp_drive = ''
        for line in out.split('\n'):
            if line.startswith('ESP='):
                esp_drive = line.split('=', 1)[1].strip()
                break
        self.log.emit(f'ESP created at {esp_drive}')
        self.progress.emit('ESP created...')

        self.log.emit('Step 4: Creating DATA partition...')
        if pmb > 0:
            script = f'''
$data = New-Partition -DiskNumber {disk} -UseMaximumSize -ErrorAction Stop
Write-Output "DATA_PART=$($data.PartitionNumber)"
'''
        else:
            script = f'''
$data = New-Partition -DiskNumber {disk} -UseMaximumSize -ErrorAction Stop
Write-Output "DATA_PART=$($data.PartitionNumber)"
'''
        out = _run_powershell(script, timeout=30)
        if 'Error' in out:
            self.log.emit(f'DATA partition creation failed: {out}')
            return False
        self.progress.emit('Formatting DATA...')

        fs_map = {'exfat': 'EXFAT', 'ntfs': 'NTFS', 'fat32': 'FAT32'}
        fs_arg = fs_map.get(fs, 'EXFAT')
        script = f'''
$dataVol = Get-Partition -DiskNumber {disk} -PartitionNumber 2 -ErrorAction Stop
$dataVol | Format-Volume -FileSystem {fs_arg} -NewFileSystemLabel "Kouprey Data" -Confirm:$false -ErrorAction Stop
$dataDrive = ($dataVol | Get-Volume).DriveLetter + ":\\"
Write-Output "DATA=$dataDrive"
'''
        out = _run_powershell(script, timeout=120)
        if 'Error' in out or 'DATA=' not in out:
            self.log.emit(f'DATA format failed: {out}')
            return False
        data_drive = ''
        for line in out.split('\n'):
            if line.startswith('DATA='):
                data_drive = line.split('=', 1)[1].strip()
                break
        self.log.emit(f'DATA formatted at {data_drive}')
        self.progress.emit('Formatting done...')

        if pmb > 0:
            self.log.emit(f'Step 5: Creating PERSIST partition ({pmb} MB ext4)...')
            self.log.emit('Persistence partition requires manual ext4 formatting on Windows')
            self.progress.emit('Persistence not supported on Windows (ext4)')

        self.log.emit('Step 6: Installing GRUB2...')
        self.progress.emit('Installing GRUB2...')
        ok = self._install_grub(esp_drive, data_drive)
        if not ok:
            return False

        self.log.emit('Step 7: Creating ISOs directory...')
        iso_dir = os.path.join(data_drive, 'ISOS')
        os.makedirs(iso_dir, exist_ok=True)
        self.log.emit(f'Created {iso_dir}')

        self.log.emit('Step 8: Writing grub.cfg...')
        cfg_content = _build_grub_cfg()
        cfg_path = os.path.join(esp_drive, 'EFI', 'BOOT', 'grub.cfg')
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, 'w', encoding='utf-8') as f:
            f.write(cfg_content)
        self.log.emit('grub.cfg written')

        self.progress.emit('Installation complete!')
        return True

    def _install_grub(self, esp_drive: str, data_drive: str) -> bool:
        src = self._grub_src
        if not src or not os.path.isdir(src):
            self.log.emit(f'GRUB source not found at {src}')
            return False

        dest_efi = os.path.join(esp_drive, 'EFI', 'BOOT')
        dest_grub = os.path.join(esp_drive, 'grub')
        dest_themes = os.path.join(esp_drive, 'themes')

        os.makedirs(dest_efi, exist_ok=True)
        os.makedirs(dest_grub, exist_ok=True)
        os.makedirs(dest_themes, exist_ok=True)

        self.log.emit(f'Copying BOOTX64.EFI...')
        shutil.copy2(os.path.join(src, 'EFI', 'BOOT', 'BOOTX64.EFI'),
                     os.path.join(dest_efi, 'BOOTX64.EFI'))

        self.log.emit(f'Copying wimboot...')
        wimboot_src = os.path.join(src, 'EFI', 'BOOT', 'wimboot')
        if os.path.isfile(wimboot_src):
            shutil.copy2(wimboot_src, os.path.join(dest_efi, 'wimboot'))

        self.log.emit(f'Copying GRUB2 modules...')
        mod_src = os.path.join(src, 'grub', 'x86_64-efi')
        if os.path.isdir(mod_src):
            mod_dst = os.path.join(dest_grub, 'x86_64-efi')
            os.makedirs(mod_dst, exist_ok=True)
            for fname in os.listdir(mod_src):
                if fname.endswith('.mod'):
                    shutil.copy2(os.path.join(mod_src, fname),
                                 os.path.join(mod_dst, fname))
            self.log.emit(f'Modules copied ({len(os.listdir(mod_dst))} files)')

        self.log.emit(f'Copying fonts...')
        font_src = os.path.join(src, 'grub', 'fonts')
        if os.path.isdir(font_src):
            font_dst = os.path.join(dest_grub, 'fonts')
            os.makedirs(font_dst, exist_ok=True)
            for fname in os.listdir(font_src):
                shutil.copy2(os.path.join(font_src, fname),
                             os.path.join(font_dst, fname))

        self.log.emit(f'Copying themes...')
        theme_src = os.path.join(src, 'themes')
        if os.path.isdir(theme_src):
            if os.path.isdir(dest_themes):
                shutil.rmtree(dest_themes)
            shutil.copytree(theme_src, dest_themes)

        self.log.emit('GRUB2 installed successfully')
        return True

    def _flash_linux(self) -> bool:
        self.log.emit('Linux flash not yet implemented')
        return False


def create_flash_worker(disk_number: int, file_system: str = 'exfat',
                        persistence_size_mb: int = 0):
    return KoupreyFlashWorker(disk_number, file_system, persistence_size_mb)


class DeployWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, mount_point: str, grub_dir: str, options: dict):
        super().__init__()
        self._mount = mount_point.rstrip('\\')
        self._grub_dir = grub_dir
        self._options = options

    def run(self):
        try:
            theme_name = self._options.get('theme')
            if theme_name and self._options.get('theme_path'):
                self.progress.emit(f'Applying theme: {theme_name}...')
                esp_path = None
                for chk in ('EFI\\BOOT\\grub.cfg', 'EFI/BOOT/grub.cfg'):
                    p = os.path.join(self._mount, chk)
                    if os.path.isfile(p):
                        esp_path = os.path.dirname(p)
                        break
                if not esp_path:
                    esp_path = os.path.join(self._mount, 'EFI', 'BOOT')
                    os.makedirs(esp_path, exist_ok=True)

                theme_dest = os.path.join(esp_path, '..', '..', 'themes', theme_name)
                theme_dest = os.path.normpath(theme_dest)
                if os.path.isdir(theme_dest):
                    shutil.rmtree(theme_dest)
                shutil.copytree(self._options['theme_path'], theme_dest)
                self.log.emit(f'Theme "{theme_name}" deployed to {theme_dest}')

                cfg_path = os.path.join(esp_path, 'grub.cfg')
                if os.path.isfile(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        cfg = f.read()
                    old = 'set theme=$prefix/themes/starfield/theme.txt'
                    new = f'set theme=$prefix/themes/{theme_name}/theme.txt'
                    if old in cfg:
                        cfg = cfg.replace(old, new)
                        with open(cfg_path, 'w', encoding='utf-8') as f:
                            f.write(cfg)
                        self.log.emit('grub.cfg theme updated')

            self.finished.emit(True, 'Deployment complete!')

        except Exception as e:
            self.finished.emit(False, str(e))
