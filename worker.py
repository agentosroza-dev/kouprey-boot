import os
import sys
import subprocess
import shutil
import datetime
import tempfile
import json

from PyQt6.QtCore import QThread, pyqtSignal


def _create_log_file(prefix: str) -> str:
    log_dir = os.path.join(tempfile.gettempdir(), 'kouprey-boot')
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(log_dir, f'{prefix}_{ts}.log')


_base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
VENTOY_DIR = os.path.join(_base, 'assets', 'ventoy-1.1.12')
VENTOY_EXE = os.path.join(VENTOY_DIR, 'altexe', 'Ventoy2Disk_X64.exe')
if not os.path.isfile(VENTOY_EXE):
    VENTOY_EXE = os.path.join(VENTOY_DIR, 'Ventoy2Disk.exe')


class VentoyFlashWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int):
        super().__init__()
        self._disk_number = disk_number
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
        self._log(f'Ventoy flash starting on disk #{self._disk_number}')
        self._log(f'Log file: {self._log_path}')
        self.progress.emit('Installing Ventoy...')

        try:
            ok = self._flash()
            if ok:
                self.progress.emit('Ventoy installed successfully!')
                self._log('Ventoy installed successfully!')
                self.finished.emit(True, f'Ventoy installed.\nLog: {self._log_path}')
            else:
                self.finished.emit(False, f'Flash failed.\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, str(e))

    def _flash(self) -> bool:
        disk = self._disk_number
        exe = VENTOY_EXE

        if not os.path.isfile(exe):
            self._log(f'Ventoy2Disk not found at {exe}')
            return False

        self._log(f'Running: {exe} -I -s -g {disk}')
        self.progress.emit(f'Running Ventoy2Disk on disk #{disk}...')

        try:
            result = subprocess.run(
                [exe, '-I', '-s', '-g', str(disk)],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            if stdout:
                for line in stdout.splitlines():
                    self._log(line)
            if stderr:
                self._log(f'STDERR: {stderr}')

            if result.returncode == 0:
                self._log('Ventoy2Disk completed successfully')
                return True
            else:
                self._log(f'Ventoy2Disk exited with code {result.returncode}')
                return False
        except subprocess.TimeoutExpired:
            self._log('Ventoy2Disk timed out (5 min)')
            return False
        except Exception as e:
            self._log(f'Error running Ventoy2Disk: {e}')
            return False


class VentoyDeployWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    log = pyqtSignal(str)

    def __init__(self, disk_number: int, data_mount: str, theme_name: str, theme_source: str):
        super().__init__()
        self._disk = disk_number
        self._data_mount = data_mount
        self._theme_name = theme_name
        self._theme_source = theme_source
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
        self._log_path = _create_log_file('deploy')
        self._log(f'Theme deploy starting. Log: {self._log_path}')

        try:
            ok = self._deploy()
            if ok:
                self.progress.emit(f'Theme "{self._theme_name}" deployed!')
                self.finished.emit(True, f'Theme "{self._theme_name}" deployed.\nLog: {self._log_path}')
            else:
                self.finished.emit(False, f'Deploy failed.\nLog: {self._log_path}')
        except Exception as e:
            self._log(f'Exception: {e}')
            self.finished.emit(False, f'{e}\nLog: {self._log_path}')

    def _deploy(self) -> bool:
        data_mount = self._data_mount
        if not data_mount or not os.path.isdir(data_mount):
            self._log(f'Data mount point not found: {data_mount}')
            return False

        ventoy_dir = os.path.join(data_mount, 'ventoy')
        theme_dir = os.path.join(ventoy_dir, 'theme')
        os.makedirs(theme_dir, exist_ok=True)

        for item in os.listdir(theme_dir):
            item_path = os.path.join(theme_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

        if not self._theme_source or not os.path.isdir(self._theme_source):
            self._log(f'Theme source not found: {self._theme_source}')
            return False

        self._log(f'Copying theme from {self._theme_source} to {theme_dir}')
        for item in os.listdir(self._theme_source):
            s = os.path.join(self._theme_source, item)
            d = os.path.join(theme_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
        self._log('Theme files copied to ventoy/theme/')

        plugin_src = os.path.join(VENTOY_DIR, 'plugin', 'ventoy', 'ventoy.json')
        plugin_dst = os.path.join(ventoy_dir, 'ventoy.json')
        if os.path.isfile(plugin_src):
            shutil.copy2(plugin_src, plugin_dst)
            self._log(f'ventoy.json deployed from plugin')
        else:
            default_json = {
                "theme": {
                    "file": "/ventoy/theme/theme.txt",
                    "display_mode": "GUI",
                    "ventoy_left": "5%",
                    "ventoy_top": "95%",
                    "ventoy_color": "#ffffff"
                }
            }
            with open(plugin_dst, 'w', encoding='utf-8') as f:
                json.dump(default_json, f, indent=4)
            self._log('Default ventoy.json created')

        self.progress.emit('Theme deployment complete!')
        return True


def create_flash_worker(disk_number: int) -> VentoyFlashWorker:
    return VentoyFlashWorker(disk_number)


def create_deploy_worker(disk_number: int, data_mount: str, theme_name: str, theme_source: str) -> VentoyDeployWorker:
    return VentoyDeployWorker(disk_number, data_mount, theme_name, theme_source)
