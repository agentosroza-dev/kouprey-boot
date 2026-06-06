"""Headless flash and deploy script for Kouprey Boot.
Usage:
  flash_headless.py -disk 2 -fs exfat              # Flash USB
  flash_headless.py -deploy -disk 2 -theme Vimix    # Deploy theme
  flash_headless.py -deploy -disk 2 -theme Bigsur   # Deploy theme
  flash_headless.py -deploy -disk 2 -theme Window11 # Deploy theme
"""
import os, sys, argparse, datetime, tempfile, shutil, re

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '0'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '0'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from worker import create_flash_worker, DeployWorker

LOG_DIR = os.path.join(tempfile.gettempdir(), 'kouprey-boot')

def log(msg, log_path=None):
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    if log_path:
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

def do_flash(disk_number, file_system):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f'flash_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    log(f'=== FLASH: Disk #{disk_number}, FS={file_system} ===', log_path)

    app = QApplication(sys.argv)
    result = {'ok': False, 'msg': ''}

    def on_progress(msg):
        log(f'  {msg}', log_path)

    def on_log(msg):
        log(f'  {msg}', log_path)

    def on_finished(ok, msg):
        result['ok'] = ok
        result['msg'] = msg
        log(f'  FINISHED: ok={ok}', log_path)
        app.quit()

    worker = create_flash_worker(disk_number, file_system)
    worker.progress.connect(on_progress)
    worker.log.connect(on_log)
    worker.finished.connect(on_finished)

    log(f'Starting...', log_path)
    worker.start()

    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(500)
    app.exec()

    log(f'Flash complete: {result["ok"]}', log_path)
    if not result['ok']:
        log(f'ERROR: {result["msg"]}', log_path)
    return result['ok'], result['msg']

def do_deploy(disk_number, theme_name):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f'deploy_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    log(f'=== DEPLOY: Disk #{disk_number}, Theme={theme_name} ===', log_path)

    from scanner import list_available_themes
    import os as _os

    themes = list_available_themes(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'themes'))
    theme_map = {t.name: t.path for t in themes}
    if theme_name not in theme_map:
        log(f'ERROR: Theme "{theme_name}" not found. Available: {list(theme_map.keys())}', log_path)
        return False, f'Theme "{theme_name}" not found'

    theme_path = theme_map[theme_name]
    log(f'Theme path: {theme_path}', log_path)

    # Determine mount points from the USB drive
    import subprocess, json
    ps_script = f'''
    $disk = Get-Disk -Number {disk_number} -ErrorAction SilentlyContinue
    if (-not $disk) {{ exit 1 }}
    $parts = Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue
    $result = @()
    foreach ($part in $parts) {{
        $vol = Get-Volume -Partition $part -ErrorAction SilentlyContinue
        $letter = if ($vol.DriveLetter) {{ $vol.DriveLetter + ":\\" }} else {{ "" }}
        $label = if ($vol.FileSystemLabel) {{ $vol.FileSystemLabel }} else {{ "" }}
        $result += [PSCustomObject]@{{
            Number = $part.PartitionNumber
            DriveLetter = $letter
            Label = $label
        }}
    }}
    $result | ConvertTo-Json
    '''
    proc = subprocess.run(['powershell', '-NoProfile', '-Command', ps_script],
                          capture_output=True, text=True, timeout=15,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode != 0:
        log(f'ERROR: Could not query disk #{disk_number}', log_path)
        return False, 'Could not query disk'

    partitions = json.loads(proc.stdout) if proc.stdout.strip() else []
    data_mount = ''
    esp_mount = ''
    esp_part_num = 0
    for p in partitions:
        letter = p.get('DriveLetter', '')
        label = p.get('Label', '')
        num = p.get('Number', 0)
        if label == 'KOUPREYDATA':
            data_mount = letter.rstrip('\\')
        elif label == 'KOUPREYESP':
            esp_part_num = num
            if letter:
                esp_mount = letter.rstrip('\\')

    log(f'  data_mount="{data_mount}" esp_part_num={esp_part_num}', log_path)

    if not data_mount:
        # Try fallback: first partition with a letter
        for p in partitions:
            letter = p.get('DriveLetter', '')
            if letter:
                data_mount = letter.rstrip('\\')
                break

    if not data_mount:
        log('ERROR: No mounted DATA partition found', log_path)
        return False, 'No mounted DATA partition found'

    app = QApplication(sys.argv)
    result = {'ok': False, 'msg': ''}

    def on_progress(msg):
        log(f'  {msg}', log_path)

    def on_log(msg):
        log(f'  {msg}', log_path)

    def on_finished(ok, msg):
        result['ok'] = ok
        result['msg'] = msg
        app.quit()

    options = {'theme': theme_name, 'theme_path': theme_path}
    worker = DeployWorker(disk_number, esp_mount, data_mount, '', options)
    worker.progress.connect(on_progress)
    worker.log.connect(on_log)
    worker.finished.connect(on_finished)

    log('Starting deploy...', log_path)
    worker.start()

    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(500)
    app.exec()

    log(f'Deploy complete: {result["ok"]}', log_path)
    if not result['ok']:
        log(f'ERROR: {result["msg"]}', log_path)
    return result['ok'], result['msg']

def do_gen_iso_menu(disk_number):
    """Regenerate .iso_menu.cfg on an already-flashed USB."""
    import subprocess, json
    ps_script = f'''
    $disk = Get-Disk -Number {disk_number} -ErrorAction SilentlyContinue
    if (-not $disk) {{ exit 1 }}
    $parts = Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue
    $result = @()
    foreach ($part in $parts) {{
        $vol = Get-Volume -Partition $part -ErrorAction SilentlyContinue
        $letter = if ($vol.DriveLetter) {{ $vol.DriveLetter + ":\\" }} else {{ "" }}
        $label = if ($vol.FileSystemLabel) {{ $vol.FileSystemLabel }} else {{ "" }}
        $result += [PSCustomObject]@{{
            DriveLetter = $letter
            Label = $label
        }}
    }}
    $result | ConvertTo-Json
    '''
    proc = subprocess.run(['powershell', '-NoProfile', '-Command', ps_script],
                          capture_output=True, text=True, timeout=15,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode != 0:
        print('ERROR: Could not query disk')
        return False

    partitions = json.loads(proc.stdout) if proc.stdout.strip() else []
    data_drive = ''
    for p in partitions:
        label = p.get('Label', '')
        letter = p.get('DriveLetter', '')
        if label == 'KOUPREYDATA' and letter:
            data_drive = letter
            break
    if not data_drive:
        print('ERROR: DATA partition not found')
        return False

    from worker import KoupreyFlashWorker
    data_path = data_drive if data_drive.endswith('\\') else data_drive + '\\'
    KoupreyFlashWorker._generate_iso_menu(data_path)
    print(f'OK: ISO menu regenerated on {data_drive}')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Kouprey Boot Flash/Deploy Tool')
    parser.add_argument('-disk', type=int, default=2, help='Disk number')
    parser.add_argument('-fs', default='exfat', choices=['exfat', 'ntfs', 'fat32'], help='File system')
    parser.add_argument('-deploy', action='store_true', help='Deploy theme mode')
    parser.add_argument('-theme', default='Vimix', help='Theme name to deploy')
    parser.add_argument('-gen-iso-menu', action='store_true', help='Regenerate ISO menu on DATA partition')

    args = parser.parse_args()

    if args.gen_iso_menu:
        ok = do_gen_iso_menu(args.disk)
    elif args.deploy:
        ok, msg = do_deploy(args.disk, args.theme)
    else:
        ok, msg = do_flash(args.disk, args.fs)

    sys.exit(0 if ok else 1)
