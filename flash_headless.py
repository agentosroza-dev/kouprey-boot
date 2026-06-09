"""Headless flash and deploy script for Kouprey Boot (Ventoy).
Usage:
  flash_headless.py -disk 2              # Flash USB with Ventoy
  flash_headless.py -deploy -disk 2 -theme Vimix    # Deploy theme
  flash_headless.py -deploy -disk 2 -theme Bigsur   # Deploy theme
  flash_headless.py -deploy -disk 2 -theme Window11 # Deploy theme
  flash_headless.py -rename -disk 2      # Rename data partition to KOUPREYDATA
"""
import os, sys, argparse, datetime, tempfile, json, subprocess

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '0'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '0'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from worker import create_flash_worker, create_deploy_worker

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


def do_flash(disk_number):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f'flash_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    log(f'=== FLASH: Disk #{disk_number} ===', log_path)

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

    worker = create_flash_worker(disk_number)
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

    themes = list_available_themes(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'themes'))
    theme_map = {t.name: t.path for t in themes}
    if theme_name not in theme_map:
        log(f'ERROR: Theme "{theme_name}" not found. Available: {list(theme_map.keys())}', log_path)
        return False, f'Theme "{theme_name}" not found'

    theme_source = theme_map[theme_name]
    log(f'Theme source: {theme_source}', log_path)

    proc = subprocess.run(['powershell', '-NoProfile', '-Command', f'''
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
    '''], capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW)

    if proc.returncode != 0:
        log(f'ERROR: Could not query disk #{disk_number}', log_path)
        return False, 'Could not query disk'

    partitions = json.loads(proc.stdout) if proc.stdout.strip() else []
    if not isinstance(partitions, list):
        partitions = [partitions]
    data_mount = ''
    for p in partitions:
        label = p.get('Label', '')
        letter = p.get('DriveLetter', '')
        if label not in ('VTOYEFI', '') and letter and not data_mount:
            data_mount = letter.rstrip('\\')

    if not data_mount:
        log('ERROR: No data partition found', log_path)
        return False, 'No data partition found'

    log(f'  data_mount="{data_mount}"', log_path)

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

    worker = create_deploy_worker(disk_number, data_mount, theme_name, theme_source)
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


def do_rename(disk_number, label='KOUPREYDATA'):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f'rename_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    log(f'=== RENAME: Disk #{disk_number} -> {label} ===', log_path)

    proc = subprocess.run(['powershell', '-NoProfile', '-Command', f'''
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
    '''], capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW)

    if proc.returncode != 0:
        log(f'ERROR: Could not query disk #{disk_number}', log_path)
        return False, 'Could not query disk'

    partitions = json.loads(proc.stdout) if proc.stdout.strip() else []
    if not isinstance(partitions, list):
        partitions = [partitions]
    drive_letter = ''
    for p in partitions:
        label_val = p.get('Label', '')
        letter = p.get('DriveLetter', '')
        if label_val not in ('VTOYEFI', '') and letter:
            drive_letter = letter.rstrip(':\\')
            break

    if not drive_letter:
        log('ERROR: No data partition with drive letter found', log_path)
        return False, 'No data partition found'

    log(f'  Renaming drive {drive_letter}: to {label}', log_path)
    rename_proc = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f'Set-Volume -DriveLetter "{drive_letter}" -NewFileSystemLabel "{label}"'],
        capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW)

    ok = rename_proc.returncode == 0
    if ok:
        log(f'Rename successful: {drive_letter}: -> {label}', log_path)
    else:
        log(f'Rename failed: {rename_proc.stderr}', log_path)
    return ok, f'Renamed to {label}' if ok else 'Rename failed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Kouprey Boot Flash/Deploy Tool')
    parser.add_argument('-disk', type=int, default=2, help='Disk number')
    parser.add_argument('-deploy', action='store_true', help='Deploy theme mode')
    parser.add_argument('-rename', action='store_true', help='Rename data partition to KOUPREYDATA')
    parser.add_argument('-theme', default='Vimix', help='Theme name to deploy')

    args = parser.parse_args()

    if args.deploy:
        ok, msg = do_deploy(args.disk, args.theme)
    elif args.rename:
        ok, msg = do_rename(args.disk)
    else:
        ok, msg = do_flash(args.disk)

    sys.exit(0 if ok else 1)
