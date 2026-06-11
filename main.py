import os
import sys
import platform
import ctypes

os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
os.environ['QT_SCALE_FACTOR'] = '1'

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui_main import KoupreyBootFlashWindow
from theme import ThemeManager
from language import LanguageManager


def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _elevate():
    script = os.path.abspath(sys.argv[0])
    ctypes.windll.shell32.ShellExecuteW(
        None, 'runas', sys.executable, f'"{script}"',
        os.path.dirname(script), 1
    )


def main():
    sys_name = platform.system()

    if sys_name == 'Windows' and not _is_admin():
        _elevate()
        return

    lang_dir = os.path.join(os.path.dirname(__file__), 'assets', 'lang')
    lang = LanguageManager(lang_dir)
    lang.switch_to('km')

    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    if sys_name not in ('Windows', 'Linux'):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle(lang.get('unsupported_os_title'))
        msg.setText(lang.get('unsupported_os_msg'))
        msg.exec()
        return

    base = os.path.dirname(__file__)
    ico_path = os.path.join(base, 'assets', 'icons', 'Kouprey Logo Variations.ico')
    if os.path.exists(ico_path):
        icon = QIcon(ico_path)
        app.setWindowIcon(icon)

    app.setApplicationName('Kouprey-Boot-Flash')
    app.setOrganizationName('Kouprey')

    if sys_name == 'Linux':
        font = QFont('Ubuntu', 11)
        font.setFamilies(['Ubuntu', 'Noto Sans', 'sans-serif'])
    else:
        font = QFont('Leelawadee UI', 11)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    theme_mgr = ThemeManager(app)
    theme_mgr.set_mode('light')

    window = KoupreyBootFlashWindow(lang, theme_mgr)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
