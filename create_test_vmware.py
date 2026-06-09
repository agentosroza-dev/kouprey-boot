"""Creates a VHD test disk flashed with Kouprey Boot for VMware testing.
Uses diskpart + PowerShell for all operations (no Hyper-V dependency).

Usage:
  python create_test_vmware.py                              # 8GB default
  python create_test_vmware.py --size 16                    # 16 GB
  python create_test_vmware.py --output D:\test.vhd         # Custom path
  python create_test_vmware.py --isos .\assets\disk         # Include ISOs
"""
import os, sys, subprocess, tempfile, time, shutil, datetime, re

OUTPUT_VHD = os.path.abspath('kouprey_test.vhd')
SIZE_GB = 8
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

GRUB_SRC = os.path.join(BASE_DIR, 'assets', 'boot')

LOG_FILE = os.path.join(tempfile.gettempdir(),
    f'kptest_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

def log(msg):
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except: pass

def run_diskpart(cmds):
    """Run diskpart with given commands, return stdout."""
    spath = os.path.join(tempfile.gettempdir(), f'kpdp_{os.getpid()}_{id(cmds)}.txt')
    try:
        text = '\r\n'.join(cmds) + '\r\nexit\r\n'
        with open(spath, 'w', encoding='ascii') as f:
            f.write(text)
        r = subprocess.run(
            ['diskpart', '/s', spath],
            capture_output=True, text=True, timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.stdout
    finally:
        try: os.remove(spath)
        except: pass

def ps(script, timeout=90):
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.stdout.strip()
    except Exception as e:
        return ''

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Create Kouprey Boot VHD for VMware testing')
    parser.add_argument('--size', type=int, default=SIZE_GB, help=f'Size in GB (default: {SIZE_GB})')
    parser.add_argument('--output', default=OUTPUT_VHD, help=f'Output VHD path')
    parser.add_argument('--isos', default=None, help='Folder with ISO files to include')
    args = parser.parse_args()

    vhd_path = os.path.abspath(args.output)
    size_gb = args.size
    iso_src = os.path.abspath(args.isos) if args.isos else None
    disk_num = None

    log('=== Kouprey Boot VMware Test VHD Creator ===')
    log(f'Output: {vhd_path}')
    log(f'Size:   {size_gb} GB')

    try:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            log('ERROR: Must run as Administrator.')
            sys.exit(1)
    except: pass
    log(f'Log: {LOG_FILE}')

    # ---- Step 1: Create VHD (diskpart) ----
    log('Step 1/6: Creating VHD...')
    # Dismount & remove old
    run_diskpart([f'select vdisk file="{vhd_path}"', 'detach vdisk'])
    time.sleep(2)
    try: os.remove(vhd_path)
    except: pass

    size_mb = size_gb * 1024
    out = run_diskpart([f'create vdisk file="{vhd_path}" type=fixed maximum={size_mb}'])
    if not os.path.exists(vhd_path):
        log(f'ERROR: VHD not created. diskpart output:\n{out[:500]}')
        sys.exit(1)
    log(f'  VHD: {size_gb} GB fixed')

    # ---- Step 2: Attach VHD & find disk number ----
    log('Step 2/6: Attaching VHD...')
    run_diskpart([f'select vdisk file="{vhd_path}"', 'attach vdisk'])
    time.sleep(3)

    # Find disk number via detail vdisk
    out = run_diskpart([f'select vdisk file="{vhd_path}"', 'detail vdisk'])
    m = re.search(r'Associated\s+disk#?\s*:\s*(\d+)', out, re.IGNORECASE)
    if not m:
        m = re.search(r'(?:Disk|Device)\s*[ID]+\s*:\s*(\d+)', out, re.IGNORECASE)
    if m:
        disk_num = int(m.group(1))
        log(f'  Disk #{disk_num}')
    else:
        # Fallback: match by VHD file size
        vhd_bytes = os.path.getsize(vhd_path)
        vhd_disk = vhd_bytes - 512  # subtract footer
        for i in range(20):
            out2 = ps(f'Get-Disk | Where-Object {{ $_.Size -eq {vhd_disk} }} | Select-Object -First 1 Number | Write-Output')
            if out2.strip().isdigit():
                disk_num = int(out2.strip())
                log(f'  Disk #{disk_num} (by size)')
                break
            time.sleep(1)

    if disk_num is None:
        log('ERROR: Could not find attached VHD disk number')
        log(f'diskpart detail output:\n{out[:500]}')
        sys.exit(1)

    # ---- Step 3: Partition (diskpart) ----
    log('Step 3/6: Partitioning...')
    run_diskpart([
        f'select disk {disk_num}',
        'clean',
        'convert gpt',
        'create partition efi size=64',
        'create partition primary',
    ])
    log('  Partitions: ESP(64MB) + DATA')

    # ---- Step 4: Format ----
    log('Step 4/6: Formatting...')

    # Format DATA on the Basic data partition
    ps(f'''
$p = Get-Partition -DiskNumber {disk_num} | Where-Object {{ $_.GptType -eq "{{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}}" }} | Select-Object -First 1
if (-not $p) {{ $p = Get-Partition -DiskNumber {disk_num} | Where-Object {{ $_.Type -eq "Basic" }} | Select-Object -First 1 }}
$p | Format-Volume -FileSystem FAT32 -NewFileSystemLabel "KOUPREYDATA" -Confirm:$false -ErrorAction Stop | Out-Null
$used = (Get-Volume).DriveLetter | Where-Object {{ $_ }}
$letter = if ($used -notcontains "T") {{ "T" }} else {{ 90..68 | ForEach-Object {{ [char]$_ }} | Where-Object {{ $_ -notin $used }} | Select-Object -First 1 }}
Set-Partition -DiskNumber {disk_num} -PartitionNumber $p.PartitionNumber -NewDriveLetter $letter -ErrorAction Stop | Out-Null
''', timeout=180)
    log('  DATA: FAT32 formatted')

    # Format ESP on the EFI System partition
    run_diskpart([
        f'select disk {disk_num}',
        'select partition 2',
        'format fs=fat32 label=KPEFI quick',
    ])

    # Mount ESP to a folder
    esp_mount = os.path.join(tempfile.gettempdir(), 'kp_esp_test')
    os.makedirs(esp_mount, exist_ok=True)
    ps(f'''
$p = Get-Partition -DiskNumber {disk_num} | Where-Object {{ $_.GptType -eq "{{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}}" -or $_.Type -eq "EFI" -or $_.Type -eq "System" }} | Select-Object -First 1
Add-PartitionAccessPath -DiskNumber {disk_num} -PartitionNumber $p.PartitionNumber -AccessPath "{esp_mount}" -ErrorAction Stop | Out-Null
''')
    log(f'  ESP: {esp_mount}')

    # ---- Step 5: Install GRUB files ----
    log('Step 5/6: Installing GRUB files...')

    if os.path.isdir(esp_mount):
        dest_efi = os.path.join(esp_mount, 'EFI', 'BOOT')
        dest_grub = os.path.join(esp_mount, 'grub')
        os.makedirs(dest_efi, exist_ok=True)
        os.makedirs(dest_grub, exist_ok=True)

        efi_src = os.path.join(GRUB_SRC, 'EFI', 'BOOT')
        if os.path.isdir(efi_src):
            shutil.copytree(efi_src, dest_efi, dirs_exist_ok=True)
        grub_src = os.path.join(GRUB_SRC, 'grub')
        if os.path.isdir(grub_src):
            shutil.copytree(grub_src, dest_grub, dirs_exist_ok=True)

        cfg = os.path.join(grub_src, 'grub.cfg')
        if os.path.isfile(cfg):
            shutil.copy2(cfg, os.path.join(dest_grub, 'grub.cfg'))
            shutil.copy2(cfg, os.path.join(dest_efi, 'grub.cfg'))

        cert = os.path.join(GRUB_SRC, 'ENROLL_THIS_KEY_IN_MOKMANAGER.cer')
        if os.path.isfile(cert): shutil.copy2(cert, os.path.join(dest_efi, 'ENROLL_THIS_KEY_IN_MOKMANAGER.cer'))

        log('  GRUB2 installed')

        # Unmount ESP
        ps(f'''
$p = Get-Partition -DiskNumber {disk_num} | Where-Object {{ $_.GptType -eq "{{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}}" -or $_.Type -eq "EFI" -or $_.Type -eq "System" }} | Select-Object -First 1
Remove-PartitionAccessPath -DiskNumber {disk_num} -PartitionNumber $p.PartitionNumber -AccessPath "{esp_mount}" -ErrorAction SilentlyContinue | Out-Null
''')
        try: os.rmdir(esp_mount)
        except: pass
        log('  ESP unmounted')
    else:
        log('  WARNING: ESP not mounted, cannot install GRUB')

    # Mount DATA partition to folder + copy ISOs/theme + generate menu via PowerShell
    log('  Setting up DATA partition...')
    data_mount = os.path.join(tempfile.gettempdir(), 'kp_data_test')
    os.makedirs(data_mount, exist_ok=True)

    iso_items = ''
    if iso_src and os.path.isdir(iso_src):
        for item in sorted(os.listdir(iso_src)):
            if item.lower().endswith(('.iso','.img')):
                s = os.path.join(iso_src, item).replace('\\', '\\\\')
                iso_items += f'Copy-Item -Path "{s}" -Destination ("$dm" + "\\\\ISOS\\\\{item}") -ErrorAction SilentlyContinue\n'
                log(f'  ISO: {item}')

    theme_items = ''
    vs = os.path.join(BASE_DIR, 'themes', 'Vimix-theme', 'themes')
    if os.path.isdir(vs):
        for item in os.listdir(vs):
            s = os.path.join(vs, item).replace('\\', '\\\\')
            theme_items += f'Copy-Item -Path "{s}" -Destination ("$dm" + "\\\\themes\\\\{item}") -Recurse -Force -ErrorAction SilentlyContinue\n'

    ps(f'''
$p = Get-Partition -DiskNumber {disk_num} | Where-Object {{ $_.GptType -eq "{{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}}" }} | Select-Object -First 1
$dm = "{data_mount}"
# Mount DATA to folder
Add-PartitionAccessPath -DiskNumber {disk_num} -PartitionNumber $p.PartitionNumber -AccessPath $dm -ErrorAction Stop | Out-Null
# ISOS
New-Item -ItemType Directory -Path ($dm + "\\ISOS") -Force -ErrorAction SilentlyContinue | Out-Null
{iso_items}
if (-not (Get-ChildItem ($dm + "\\ISOS\\*.iso") -ErrorAction SilentlyContinue)) {{
    New-Item -ItemType File -Path ($dm + "\\ISOS\\DUMMY") -Force -ErrorAction SilentlyContinue | Out-Null
}}
# Theme
New-Item -ItemType Directory -Path ($dm + "\\themes") -Force -ErrorAction SilentlyContinue | Out-Null
{theme_items}
New-Item -ItemType File -Path ($dm + "\\themes\\.marker") -Force -ErrorAction SilentlyContinue | Out-Null
# Generate ISO menu using Python
Write-Output "MOUNTED=$dm"
''', timeout=180)

    # Generate ISO menu via Python using the mount path
    if os.path.isdir(data_mount):
        log(f'  Generating ISO menu on {data_mount}...')
        from worker import KoupreyFlashWorker
        KoupreyFlashWorker._generate_iso_menu(data_mount + '\\')
        log('  ISO entries generated')
    else:
        log('  WARNING: DATA mount not accessible')

    # Unmount DATA
    ps(f'''
$p = Get-Partition -DiskNumber {disk_num} | Sort-Object PartitionNumber | Select-Object -First 1
Remove-PartitionAccessPath -DiskNumber {disk_num} -PartitionNumber $p.PartitionNumber -AccessPath "{data_mount}" -ErrorAction SilentlyContinue | Out-Null
''')
    try: os.rmdir(data_mount)
    except: pass

    # ---- Step 6: Detach ----
    log('Step 6/6: Detaching VHD...')
    run_diskpart([f'select vdisk file="{vhd_path}"', 'detach vdisk'])
    time.sleep(2)
    log('  Done')

    # ---- Create VMDK + VMX ----
    log('Creating VMware files...')

    disk_size = os.path.getsize(vhd_path) - 512
    total_s = disk_size // 512
    heads, spt = 16, 63
    cyl = total_s // (heads * spt)

    vmdk_path = os.path.splitext(vhd_path)[0] + '.vmdk'
    with open(vmdk_path, 'w') as f:
        f.write(f'''# Disk DescriptorFile
version=1
CID=ffffffff
parentCID=ffffffff
createType="monolithicFlat"

# Extent description
RW {total_s} FLAT "{os.path.basename(vhd_path)}" 0

# The disk Data Base
#DDB

ddb.vendor = "VMware"
ddb.toolsVersion = "0"
ddb.encoding = "windows-1252"
ddb.geometry.cylinders = "{cyl}"
ddb.geometry.heads = "{heads}"
ddb.geometry.sectors = "{spt}"
ddb.uuid = "60 00 C2 9A 78 A3 7A 4B-A5 2C 5A 71 82 9F 51 EF"
ddb.longContentID = "ffffffffffffffffffffffffffffffff"
''')

    vm_name = os.path.splitext(os.path.basename(vhd_path))[0]
    vmx_path = os.path.splitext(vhd_path)[0] + '.vmx'
    with open(vmx_path, 'w') as f:
        f.write(f'''# {vm_name} - Kouprey Boot Test VM
.encoding = "windows-1252"
config.version = "8"
virtualHW.version = "21"
displayName = "{vm_name}"
guestOS = "ubuntu-64"
memsize = "2048"
numvcpus = "2"
firmware = "efi"
scsi0.virtualDev = "lsisas1068"
scsi0.present = "TRUE"
scsi0:0.present = "TRUE"
scsi0:0.fileName = "{os.path.basename(vmdk_path)}"
scsi0:0.deviceType = "scsi-hardDisk"
ethernet0.present = "TRUE"
ethernet0.virtualDev = "e1000"
ethernet0.connectionType = "nat"
''')

    log('')
    log('=' * 60)
    log('SUCCESS!')
    log('=' * 60)
    log(f'')
    log(f'  VHD:  {vhd_path}')
    log(f'  VMDK: {vmdk_path}')
    log(f'  VMX:  {vmx_path}')
    log(f'')
    log('To test in VMware Workstation:')
    log(f'  File -> Open -> {vmx_path}')
    log(f'  Power on (press Esc to select boot device)')
    log(f'')
    log('To add ISOs later:')
    log(f'  diskpart -> select vdisk -> attach vdisk')
    log(f'  Copy .iso to T:\\ISOS\\')
    log(f'  Run: python flash_headless.py -gen-iso-menu -disk <N>')
    log(f'  diskpart -> select vdisk -> detach vdisk')

if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        log(f'FATAL: {e}')
        log(traceback.format_exc())
        sys.exit(1)
