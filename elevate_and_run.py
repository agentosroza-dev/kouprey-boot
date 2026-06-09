"""Elevate and run a script with admin privileges."""
import sys, os, ctypes

script = os.path.join(os.path.dirname(os.path.abspath(__file__)), sys.argv[1] if len(sys.argv) > 1 else 'flash_headless.py')
args = ' '.join(f'"{a}"' if ' ' in a else a for a in sys.argv[2:]) if len(sys.argv) > 2 else ''

ctypes.windll.shell32.ShellExecuteW(
    None, 'runas', sys.executable, f'"{script}" {args}',
    os.path.dirname(script), 1
)
