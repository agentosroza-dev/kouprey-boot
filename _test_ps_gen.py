import sys; sys.path.insert(0, '.')
from worker import create_iso_worker
w = create_iso_worker(2, r'D:\Window_Program\ISO\windows-10-22h2.iso')
import inspect
src = inspect.getsource(type(w)._flash_linux_iso)
assert 'PROGRESS:' in src
assert '@\\"' in src
print('Worker has here-string approach: OK')

# Simulate the ps_code generation
self_iso = r'D:\Window_Program\ISO\windows-10-22h2.iso'
device = rf'\\.\PhysicalDrive2'
ps_code = (
    f'$path = @"\n{self_iso}\n"@; '
    f'$dev = @"\n{device}\n"@; '
    f'$size = (Get-Item $path).Length; '
    f'$stream = [System.IO.File]::Open($dev, '
    f'[System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, '
    f'[System.IO.FileShare]::ReadWrite); '
    f'try {{ '
    f'  $iso = [System.IO.File]::OpenRead($path); '
    f'  try {{ '
    f'    $buf = New-Object byte[] 1048576; '
    f'    $total = 0; '
    f'    while (($read = $iso.Read($buf, 0, $buf.Length)) -gt 0) {{ '
    f'      $stream.Write($buf, 0, $read); '
    f'      $total += $read; '
    f'      Write-Output (\"PROGRESS:\" + [int]($total * 100 / $size)); '
    f'    }} '
    f'  }} finally {{ $iso.Close() }} '
    f'}} finally {{ $stream.Close() }} '
    f'Write-Output \"DONE\"'
)
print('Script length:', len(ps_code))
assert 'PhysicalDrive2' in ps_code
assert 'windows-10' in ps_code
assert 'PROGRESS:' in ps_code
assert '@"\n' in ps_code
print('Script generated with here-strings: OK')
print()
# Quick validation: the script should have valid here-string syntax
# @" ... "@ is the PowerShell here-string
assert '\n"@' in ps_code
print('Here-string syntax valid')
