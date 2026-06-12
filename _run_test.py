"""Test runner for main.py in headless environments."""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Patch admin check
import main
main._is_admin = lambda: True
main._elevate = lambda: None

# Add quit timer
import ui_main
orig_init = ui_main.KoupreyBootFlashWindow.__init__
def patched_init(self, lang, theme_mgr):
    orig_init(self, lang, theme_mgr)
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    QTimer.singleShot(3000, QApplication.instance().quit)
ui_main.KoupreyBootFlashWindow.__init__ = patched_init

print('Starting main...', flush=True)
main.main()
print('Exited cleanly.', flush=True)
