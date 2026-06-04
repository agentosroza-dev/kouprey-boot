"""Elevate and run flash_headless.py."""
import sys, os, ctypes

script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flash_headless.py')
args = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else '-disk 2 -fs exfat'

ctypes.windll.shell32.ShellExecuteW(
    None, 'runas', sys.executable, f'"{script}" {args}',
    os.path.dirname(script), 1
)
