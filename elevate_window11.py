"""Elevate and run deploy_window11.py."""
import os, sys, ctypes

script = r'C:\Users\Agentos\AppData\Local\Temp\opencode\deploy_window11.py'

ctypes.windll.shell32.ShellExecuteW(
    None, 'runas', sys.executable, f'"{script}"',
    os.path.dirname(__file__), 1
)
